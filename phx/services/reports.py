"""Dashboard, reports and CSV exports."""
import csv
from datetime import date, timedelta

from ..domain import rules
from .catalog import InventoryService


class ReportService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def _load(self):
        with self.db.unit_of_work() as repos:
            return repos.products.all(), repos.customers.all(), repos.sales.all()

    def dashboard(self):
        products, customers, sales = self._load()
        today = rules.today()
        todays = [s for s in sales if s["date"] == today]
        days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
        return {
            "todayTotal": sum(s["total"] for s in todays), "todayCount": len(todays),
            "todayItems": sum(s["items"] for s in todays),
            "week": [(d, sum(s["total"] for s in sales if s["date"] == d)) for d in days],
            "alerts": InventoryService.alerts(products), "recent": sales[:5],
            "customerCount": len(customers), "productCount": len(products),
            "creditDue": sum(s["total"] for s in sales if s["status"] == "Credit"),
        }

    def reports(self):
        products, customers, sales = self._load()
        by_category, mix = {}, {m: 0.0 for m in rules.PAYMENT_METHODS}
        for p in products:
            by_category[p["category"]] = by_category.get(p["category"], 0) + p["stock"] * p["price"]
        for s in sales:
            mix[s["payment"]] = mix.get(s["payment"], 0) + s["total"]
        revenue = sum(s["total"] for s in sales)
        return {"revenue": revenue, "invoices": len(sales), "average": revenue / len(sales) if sales else 0,
                "inventoryValue": sum(by_category.values()), "byCategory": by_category, "paymentMix": mix,
                "expiredStock": sum(b["stock"] for p in products for b in p["batches"] if rules.is_expired(b["expiry"]))}

    def export_inventory(self, path):
        products, _, _ = self._load()
        rows = [["Product", "Category", "HSN", "GST %", "Batch", "Expiry", "Stock", "Reorder level", "Price", "MRP"]]
        for p in products:
            for b in p["batches"] or [{"batch": "", "expiry": "", "stock": 0}]:
                rows.append([p["name"], p["category"], p["hsn"], p["gst"], b["batch"], b["expiry"], b["stock"],
                             p["reorder"], p["price"], p["mrp"]])
        self._write(path, rows)

    def export_customers(self, path):
        _, customers, _ = self._load()
        self._write(path, [["Name", "Phone", "Email", "Tier", "Points", "Spent INR", "Visits", "Joined"]] + [
            [c["name"], c["phone"], c["email"], c["tier"], c["points"], c["spent"], c["visits"], c["joined"]]
            for c in customers])

    def export_sales(self, path):
        _, _, sales = self._load()
        self._write(path, [["Invoice", "Date", "Customer", "Items", "Payment", "Status", "Total INR",
                            "Sold by (login ID)"]] + [
            [s["id"], s["date"], s["customerName"], s["items"], s["payment"], s["status"], s["total"],
             (s["soldBy"] or {}).get("username", "")] for s in sales])

    @staticmethod
    def _write(path, rows):
        with open(path, "w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerows(rows)
