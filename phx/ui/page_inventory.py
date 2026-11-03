import tkinter as tk
from tkinter import filedialog, ttk

from ..services import lookups
from ..services.core import ServiceError
from .theme import DataTable, card, inr
from .widgets import FormDialog, Page, guarded


class InventoryPage(Page):
    title = "Inventory"
    subtitle = "Batches, expiry and reorder levels"

    def build(self):
        self.header([("Export CSV", self.export, False), ("Receive stock", self.receive, False),
                     ("+ Add product", self.add, True)])
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 10))
        self.search, self.filter = tk.StringVar(), tk.StringVar(value="All")
        ttk.Entry(bar, textvariable=self.search, width=34).pack(side="left")
        ttk.Combobox(bar, textvariable=self.filter, state="readonly", width=16,
                     values=["All", "Low stock", "Near expiry", "Expired"]).pack(side="left", padx=8)
        self.search.trace_add("write", lambda *_: self.fill())
        self.filter.trace_add("write", lambda *_: self.fill())
        self.summary = ttk.Label(bar, text="", style="Muted.TLabel")
        self.summary.pack(side="right")
        self.table = DataTable(self, [("name", "Product", 250, "w"), ("category", "Category", 100, "w"),
                                      ("hsn", "HSN", 80, "w"), ("gst", "GST", 50, "e"), ("batch", "Batch", 90, "w"),
                                      ("expiry", "Expiry", 90, "w"), ("stock", "Stock", 70, "e"),
                                      ("reorder", "Reorder", 70, "e"), ("price", "Price", 80, "e"),
                                      ("mrp", "MRP", 80, "e")], height=18)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text="Each batch is listed on its own row; the earliest-expiry batch is billed first.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self.products = []

    def refresh(self):
        self.products = self.svc.inventory.products()
        self.fill()

    def fill(self):
        text, mode = self.search.get().strip().lower(), self.filter.get()
        rows, low, near = [], 0, 0
        for p in self.products:
            if text and text not in f"{p['name']} {p['brand']} {p['category']} {p['hsn']}".lower():
                continue
            is_low = p["stock"] <= p["reorder"]
            low += is_low
            for b in p["batches"] or [{"id": "none", "batch": "—", "expiry": "—", "stock": 0}]:
                expired = b["expiry"] != "—" and lookups.is_expired(b["expiry"])
                near_expiry = b["stock"] > 0 and b["expiry"] != "—" and lookups.is_near_expiry(b["expiry"])
                near += near_expiry
                if (mode == "Low stock" and not is_low) or (mode == "Near expiry" and not near_expiry) or (
                        mode == "Expired" and not expired):
                    continue
                tag = "warn" if (is_low or expired or near_expiry) else None
                rows.append((f"{p['id']}|{b['id']}", (p["name"], p["category"], p["hsn"], f"{p['gst']}%", b["batch"],
                                                     b["expiry"], b["stock"], p["reorder"], inr(p["price"]),
                                                     inr(p["mrp"])), tag))
        self.table.set_rows(rows)
        self.summary.configure(text=f"{len(self.products)} products · {low} low stock · {near} batches near expiry")

    def add(self):
        def save(values):
            product = self.svc.inventory.add_product(values)
            self.app.toast(f"{product['name']} added.")
            self.refresh()
        FormDialog(self, "Add product", [
            ("name", "Product name *", "text", None, ""), ("brand", "Brand · pack", "text", None, ""),
            ("category", "Category", "combo", ["Tablets", "Syrups", "Injections", "Ointments", "Devices", "Others"], "Tablets"),
            ("hsn", "HSN code", "text", None, ""), ("price", "Selling price *", "text", None, ""),
            ("mrp", "MRP *", "text", None, ""), ("gst", "GST % *", "combo", [str(g) for g in lookups.GST_RATES], "12"),
            ("reorder", "Reorder level", "text", None, "10"), ("stock", "Opening stock", "text", None, "0"),
            ("batch", "Batch no. (if stock)", "text", None, ""), ("expiry", "Expiry YYYY-MM-DD (if stock)", "text", None, ""),
        ], save, "Add product")

    def receive(self):
        selected = self.table.selected()
        product = next((p for p in self.products if selected and p["id"] == selected.split("|")[0]), None)
        if not product:
            self.app.toast("Select a product row first.")
            return

        def save(values):
            self.svc.inventory.receive_stock(product["id"], values["batch"], values["expiry"], values["quantity"])
            self.app.toast(f"Stock received for {product['name']}.")
            self.refresh()
        FormDialog(self, "Receive stock", [
            ("product", "Product", "readonly", None, product["name"]), ("batch", "Batch no. *", "text", None, ""),
            ("expiry", "Expiry YYYY-MM-DD *", "text", None, ""), ("quantity", "Quantity *", "text", None, "")],
            save, "Receive")

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="phoebix-inventory.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.svc.reports.export_inventory(path)
            self.app.toast(f"Saved {path}")
