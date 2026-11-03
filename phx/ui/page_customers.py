import tkinter as tk
from tkinter import filedialog, ttk

from .page_pos import open_customer_form
from .theme import DataTable, inr0
from .widgets import FormDialog, Page


class CustomersPage(Page):
    title = "Customers"
    subtitle = "Profiles, loyalty tier and points"

    def build(self):
        self.header([("Export CSV", self.export, False), ("Adjust points", self.adjust, False),
                     ("+ New customer", self.add, True)])
        self.search = tk.StringVar()
        ttk.Entry(self, textvariable=self.search, width=34).pack(anchor="w", pady=(0, 10))
        self.search.trace_add("write", lambda *_: self.fill())
        self.table = DataTable(self, [("name", "Customer", 190, "w"), ("phone", "Phone", 120, "w"),
                                      ("email", "Email", 180, "w"), ("state", "State", 100, "w"),
                                      ("tier", "Tier", 70, "w"), ("points", "Points", 70, "e"),
                                      ("spent", "Total spent", 100, "e"), ("visits", "Visits", 60, "e"),
                                      ("joined", "Joined", 90, "w")], height=18)
        self.table.pack(fill="both", expand=True)
        self.customers = []

    def refresh(self):
        self.customers = self.svc.customers.list()
        self.fill()

    def fill(self):
        text = self.search.get().strip().lower()
        rows = [(c["id"], (c["name"], c["phone"], c["email"], c["state"] or "—", c["tier"], c["points"],
                           inr0(c["spent"]), c["visits"], c["joined"]), None)
                for c in self.customers if not text or text in f"{c['name']} {c['phone']} {c['email']}".lower()]
        self.table.set_rows(rows)

    def add(self):
        def save(values):
            customer = self.svc.customers.add(values)
            self.app.toast(f"{customer['name']} added.")
            self.refresh()
        open_customer_form(self, save)

    def adjust(self):
        customer = next((c for c in self.customers if c["id"] == self.table.selected()), None)
        if not customer:
            self.app.toast("Select a customer first.")
            return

        def save(values):
            try:
                delta = int(values["delta"])
            except ValueError:
                from ..services.core import ServiceError
                raise ServiceError("Enter a whole number of points (negative to deduct).") from None
            self.svc.customers.adjust_points(customer["id"], delta)
            self.refresh()
        FormDialog(self, "Adjust points", [
            ("customer", "Customer", "readonly", None, f"{customer['name']} ({customer['points']} pts)"),
            ("delta", "Points to add / deduct", "text", None, "0")], save, "Apply",
            note="Administrators only. Use a negative number to deduct.")

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="phoebix-customers.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.svc.reports.export_customers(path)
            self.app.toast(f"Saved {path}")
