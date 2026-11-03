from tkinter import filedialog, ttk

from .theme import DataTable, card, inr, inr0
from .widgets import Page


class ReportsPage(Page):
    title = "Reports"
    subtitle = "Sales, payments and stock value"

    def build(self):
        self.header([("Export sales CSV", self.export, True)])
        tiles = ttk.Frame(self)
        tiles.pack(fill="x")
        self.labels = {}
        for index, (key, caption) in enumerate([("revenue", "Total sales"), ("invoices", "Invoices"),
                                                ("average", "Average basket"), ("stock", "Inventory value")]):
            tile = card(tiles)
            tile.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 12, 0))
            tiles.columnconfigure(index, weight=1, uniform="q")
            ttk.Label(tile, text=caption, style="CardMuted.TLabel").pack(anchor="w")
            self.labels[key] = ttk.Label(tile, text="—", style="Stat.TLabel")
            self.labels[key].pack(anchor="w")
        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(14, 0))
        for column in (0, 1):
            lower.columnconfigure(column, weight=1, uniform="z")
        lower.rowconfigure(0, weight=1)
        left = card(lower)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(left, text="Payment mix", style="CardH2.TLabel").pack(anchor="w")
        self.mix = DataTable(left, [("method", "Method", 120, "w"), ("amount", "Amount", 120, "e"),
                                    ("share", "Share", 80, "e")], height=6)
        self.mix.pack(fill="x", pady=(8, 12))
        ttk.Label(left, text="Inventory value by category", style="CardH2.TLabel").pack(anchor="w")
        self.categories = DataTable(left, [("category", "Category", 160, "w"), ("value", "Value", 120, "e")], height=6)
        self.categories.pack(fill="both", expand=True, pady=(8, 0))
        right = card(lower)
        right.grid(row=0, column=1, sticky="nsew")
        ttk.Label(right, text="All invoices (double-click to open)", style="CardH2.TLabel").pack(anchor="w")
        self.sales = DataTable(right, [("id", "Invoice", 80, "w"), ("date", "Date", 90, "w"),
                                       ("customer", "Customer", 130, "w"), ("payment", "Pay", 60, "w"),
                                       ("by", "Sold by", 80, "w"), ("total", "Total", 90, "e")], height=14,
                               on_double=lambda sale_id: sale_id and self.app.open_invoice(sale_id))
        self.sales.pack(fill="both", expand=True, pady=(8, 0))

    def refresh(self):
        data = self.svc.reports.reports()
        self.labels["revenue"].configure(text=inr0(data["revenue"]))
        self.labels["invoices"].configure(text=str(data["invoices"]))
        self.labels["average"].configure(text=inr0(data["average"]))
        self.labels["stock"].configure(text=inr0(data["inventoryValue"]))
        total = data["revenue"] or 1
        self.mix.set_rows([(m, (m, inr(v), f"{100 * v / total:.0f}%"), None) for m, v in data["paymentMix"].items()])
        self.categories.set_rows([(c, (c, inr0(v)), None) for c, v in sorted(data["byCategory"].items())])
        self.sales.set_rows([(s["id"], (s["id"], s["date"], s["customerName"], s["payment"],
                                        (s["soldBy"] or {}).get("username", "—"), inr(s["total"])), None)
                             for s in self.svc.billing.sales()])

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="phoebix-sales.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.svc.reports.export_sales(path)
            self.app.toast(f"Saved {path}")
