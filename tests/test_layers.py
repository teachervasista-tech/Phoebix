import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from phx.services.container import Services
from phx.services.core import AuthError, ServiceError

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_state.json"


class FakeGateway:
    def __init__(self, state="COMPLETED", amount=None, mode="UPI_QR"):
        self.state, self.amount, self.mode, self.created = state, amount, mode, []

    def is_configured(self):
        return True

    def create_order(self, order_id, amount, reference):
        self.created.append((order_id, amount))
        return "https://pay.example/checkout", "OMO1"

    def order_status(self, order_id):
        amount = self.amount if self.amount is not None else self.created[-1][1]
        return {"state": self.state, "amount": amount, "transactionId": "TX1", "mode": self.mode}


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gateway = FakeGateway()
        self.svc = Services(Path(self.tmp.name) / "t.sqlite3", SAMPLE, self.gateway)
        self.addCleanup(self.tmp.cleanup)

    def admin(self):
        self.svc.auth.login("admin", "admin123")

    def staff(self):
        self.svc.auth.login("cashier", "cashier123")

    def request(self, **extra):
        product = self.svc.inventory.products()[0]
        batch = next(b for b in product["batches"] if b["stock"] > 5)
        return {"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 2}], **extra}, product, batch


class AuthTests(ServiceTestCase):
    def test_login_and_lockout(self):
        with self.assertRaises(AuthError):
            self.svc.auth.login("admin", "wrong")
        user = self.svc.auth.login("admin", "admin123")
        self.assertTrue(user["mustChangePassword"])
        self.assertNotIn("passwordHash", user)
        self.svc.auth.logout()
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.auth.login("cashier", "nope")
        with self.assertRaises(AuthError) as ctx:
            self.svc.auth.login("cashier", "cashier123")
        self.assertIn("Too many", str(ctx.exception))

    def test_change_password_clears_forced_flag(self):
        self.admin()
        user = self.svc.auth.change_password("admin123", "a-much-better-pass")
        self.assertFalse(user["mustChangePassword"])
        self.svc.auth.logout()
        self.svc.auth.login("admin", "a-much-better-pass")

    def test_staff_cannot_manage_users_or_bank(self):
        self.staff()
        with self.assertRaises(AuthError):
            self.svc.users.list()
        with self.assertRaises(AuthError):
            self.svc.settings.save_bank({"accountHolder": "X"})

    def test_admin_cannot_demote_self(self):
        self.admin()
        me = self.svc.session.user
        with self.assertRaises(ServiceError):
            self.svc.users.update(me["id"], me["name"], "staff", True)

    def test_unauthenticated_calls_rejected(self):
        with self.assertRaises(AuthError):
            self.svc.customers.add({"name": "A", "phone": "9876543210"})


class BillingTests(ServiceTestCase):
    def test_sale_reduces_stock_and_stamps_cashier(self):
        self.staff()
        request, product, batch = self.request()
        sale = self.svc.billing.checkout(request, "Cash")
        self.assertEqual(sale["soldBy"]["username"], "cashier")
        self.assertEqual(sale["id"], "INV-1049")
        after = next(p for p in self.svc.inventory.products() if p["id"] == product["id"])
        self.assertEqual(next(b for b in after["batches"] if b["id"] == batch["id"])["stock"], batch["stock"] - 2)

    def test_loyalty_earn_redeem_and_totals(self):
        self.admin()
        customer = self.svc.customers.list()[0]
        request, _, _ = self.request(customerId=customer["id"], redeem=5)
        totals = self.svc.billing.quote(request)
        self.assertEqual(totals["redeem"], 5)
        sale = self.svc.billing.checkout(request, "Cash")
        after = next(c for c in self.svc.customers.list() if c["id"] == customer["id"])
        self.assertEqual(after["points"], customer["points"] - 5 + sale["earned"])
        self.assertEqual(after["visits"], customer["visits"] + 1)

    def test_insufficient_stock_rejected_without_side_effects(self):
        self.admin()
        request, product, batch = self.request()
        request["lines"][0]["qty"] = batch["stock"] + 1
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "Cash")
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_credit_needs_customer_and_card_needs_gateway(self):
        self.admin()
        request, _, _ = self.request()
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "Credit")
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "UPI")

    def test_invoice_has_gst_split_and_bank(self):
        self.admin()
        self.svc.settings.save_bank({"accountHolder": "Phoebix", "bankName": "HDFC", "accountNumber": "123456789012",
                                     "ifsc": "HDFC0001234", "accountType": "Current"})
        request, _, _ = self.request()
        sale = self.svc.billing.checkout(request, "Cash")
        invoice = self.svc.billing.invoice(sale["id"])
        self.assertTrue(invoice["intra"])
        self.assertTrue(invoice["hasBank"])
        self.assertAlmostEqual(sum(l["cgst"] + l["sgst"] for l in invoice["lines"]), sale["totals"]["tax"], places=1)


class PaymentTests(ServiceTestCase):
    def test_completed_payment_records_sale_once(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.assertTrue(started["redirectUrl"].startswith("https://"))
        first = self.svc.payments.check(started["merchantOrderId"])
        second = self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first["sale"]["id"], second["sale"]["id"])
        self.assertEqual(first["sale"]["soldBy"]["username"], "cashier")
        self.assertEqual(len(self.svc.billing.sales()), 7)

    def test_pending_does_not_record(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "Card")
        self.gateway.state = "PENDING"
        self.assertEqual(self.svc.payments.check(started["merchantOrderId"])["status"], "PENDING")
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_amount_mismatch_never_records(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.gateway.amount = 100
        with self.assertRaises(ServiceError):
            self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_stock_change_during_payment_needs_reconciliation(self):
        self.staff()
        request, product, batch = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.svc.billing.checkout({"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": batch["stock"]}]}, "Cash")
        result = self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(result["status"], "RECONCILIATION_REQUIRED")


class CatalogTests(ServiceTestCase):
    def test_add_customer_validates_and_persists(self):
        self.staff()
        customer = self.svc.customers.add({"name": "Ravi Kumar", "phone": "98765 43210", "state": "Telangana"})
        self.assertEqual(customer["initials"], "RK")
        with self.assertRaises(ServiceError):
            self.svc.customers.add({"name": "Dup", "phone": "9876543210"})
        with self.assertRaises(ServiceError):
            self.svc.customers.add({"name": "Bad", "phone": "123"})
        self.assertIn("Ravi Kumar", [c["name"] for c in self.svc.customers.list()])

    def test_inventory_add_and_receive(self):
        self.staff()
        product = self.svc.inventory.add_product({"name": "Test Syrup", "price": 50, "mrp": 60, "gst": 12,
                                                  "stock": 10, "batch": "B1", "expiry": "2099-01-01"})
        updated = self.svc.inventory.receive_stock(product["id"], "B2", "2098-01-01", 5)
        self.assertEqual(updated["stock"], 15)
        self.assertEqual(updated["batches"][0]["batch"], "B2")
        with self.assertRaises(ServiceError):
            self.svc.inventory.receive_stock(product["id"], "B1", "2099-06-01", 1)
        with self.assertRaises(ServiceError):
            self.svc.inventory.add_product({"name": "Bad", "price": 70, "mrp": 60, "gst": 5})

    def test_bank_details_validation(self):
        self.admin()
        with self.assertRaises(ServiceError):
            self.svc.settings.save_bank({"accountHolder": "A", "bankName": "B", "accountNumber": "12", "ifsc": "HDFC0001234"})
        bank = self.svc.settings.save_bank({"accountHolder": "A", "bankName": "B", "accountNumber": "123456789",
                                            "ifsc": "hdfc0001234", "upiId": "shop@okhdfc"})
        self.assertEqual(bank["ifsc"], "HDFC0001234")

    def test_offer_applies_discount(self):
        self.admin()
        self.svc.loyalty.add_offer("Ten off", 10, "percent", "2099-01-01")
        offer = self.svc.loyalty.usable_offers()[0]
        request, _, _ = self.request(offerId=offer["id"])
        totals = self.svc.billing.quote(request)
        self.assertAlmostEqual(totals["discount"], totals["subtotal"] * 0.1, places=2)

    def test_reports_and_exports(self):
        self.admin()
        path = Path(self.tmp.name) / "sales.csv"
        self.svc.reports.export_sales(path)
        self.assertIn("INV-1048", path.read_text(encoding="utf-8-sig"))
        self.assertEqual(self.svc.reports.reports()["invoices"], 6)
        self.assertIn("week", self.svc.reports.dashboard())


class LayeringTests(unittest.TestCase):
    """Enforce: ui -> services -> domain/data, domain and data stay independent."""

    FORBIDDEN = {
        "domain": ("phx.data", "phx.services", "phx.ui", "sqlite3", "tkinter"),
        "data": ("phx.services", "phx.ui", "phx.domain", "tkinter"),
        "services": ("phx.ui", "tkinter", "sqlite3"),
        "ui": ("phx.data", "phx.domain", "sqlite3"),
    }

    def imports(self, path, package):
        names = []
        parts = ["phx", package]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = parts[: max(0, len(parts) - node.level + 1)]
                    names.append(".".join(base + ([node.module] if node.module else [])))
                elif node.module:
                    names.append(node.module)
        return names

    def test_layer_dependencies(self):
        for package, banned in self.FORBIDDEN.items():
            for path in (ROOT / "phx" / package).glob("*.py"):
                for name in self.imports(path, package):
                    for bad in banned:
                        self.assertFalse(name == bad or name.startswith(bad + "."),
                                         f"{path.name} ({package}) must not import {name}")

if __name__ == "__main__":
    unittest.main()
