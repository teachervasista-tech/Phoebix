import tkinter as tk
from datetime import date
from tkinter import ttk

from . import theme
from .theme import DataTable, card, inr0
from .widgets import Page


class DashboardPage(Page):
    title = "Dashboard"

    def build(self):
        self.header([("New sale", lambda: self.app.navigate("pos"), True)])
        self.tiles = ttk.Frame(self)
        self.tiles.pack(fill="x")
        self.labels = {}
        for index, (key, caption) in enumerate([("sales", "Today's sales"), ("bills", "Bills today"),
                                                ("customers", "Customers"), ("credit", "Credit outstanding")]):
            tile = card(self.tiles)
            tile.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 12, 0))
            self.tiles.columnconfigure(index, weight=1, uniform="tile")
            ttk.Label(tile, text=caption, style="CardMuted.TLabel").pack(anchor="w")
            self.labels[key] = ttk.Label(tile, text="—", style="Stat.TLabel")
            self.labels[key].pack(anchor="w", pady=(6, 0))
        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(14, 0))
        lower.columnconfigure(0, weight=3, uniform="c")
        lower.columnconfigure(1, weight=2, uniform="c")
        lower.rowconfigure(0, weight=1)
        chart = card(lower)
        chart.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(chart, text="Sales — last 7 days", style="CardH2.TLabel").pack(anchor="w")
        self.canvas = tk.Canvas(chart, background=theme.CARD, highlightthickness=0, height=200)
        self.canvas.pack(fill="both", expand=True, pady=(8, 0))
        self.canvas.bind("<Configure>", lambda _e: self.draw())
        right = ttk.Frame(lower)
        right.grid(row=0, column=1, sticky="nsew")
        right.rowconfigure((0, 1), weight=1)
        right.columnconfigure(0, weight=1)
        alerts = card(right)
        alerts.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        ttk.Label(alerts, text="Stock alerts", style="CardH2.TLabel").pack(anchor="w")
        self.alerts = DataTable(alerts, [("name", "Product", 190, "w"), ("stock", "Stock", 60, "e"),
                                         ("note", "Alert", 110, "w")], height=4)
        self.alerts.pack(fill="both", expand=True, pady=(8, 0))
        recent = card(right)
        recent.grid(row=1, column=0, sticky="nsew")
        ttk.Label(recent, text="Recent transactions", style="CardH2.TLabel").pack(anchor="w")
        self.recent = DataTable(recent, [("id", "Invoice", 80, "w"), ("customer", "Customer", 130, "w"),
                                         ("total", "Total", 80, "e")], height=4,
                                on_double=lambda sale_id: sale_id and self.app.open_invoice(sale_id))
        self.recent.pack(fill="both", expand=True, pady=(8, 0))
        self.week = []

    def refresh(self):
        data = self.svc.reports.dashboard()
        self.labels["sales"].configure(text=inr0(data["todayTotal"]))
        self.labels["bills"].configure(text=str(data["todayCount"]))
        self.labels["customers"].configure(text=str(data["customerCount"]))
        self.labels["credit"].configure(text=inr0(data["creditDue"]))
        rows = []
        for product in data["alerts"]:
            note = "Low stock" if product["stock"] <= product["reorder"] else "Near expiry"
            rows.append((product["id"], (product["name"], product["stock"], note), "warn"))
        self.alerts.set_rows(rows)
        self.recent.set_rows([(s["id"], (s["id"], s["customerName"], inr0(s["total"])), None) for s in data["recent"]])
        self.week = data["week"]
        self.draw()

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        if not self.week:
            return
        width, height = canvas.winfo_width(), canvas.winfo_height()
        top = max(max(v for _d, v in self.week), 1)
        slot = width / len(self.week)
        for index, (day, value) in enumerate(self.week):
            bar = (height - 44) * value / top
            x = index * slot + slot * 0.2
            canvas.create_rectangle(x, height - 22 - bar, x + slot * 0.6, height - 22, fill=theme.GREEN, outline="")
            canvas.create_text(x + slot * 0.3, height - 10, text=date.fromisoformat(day).strftime("%a"), fill=theme.MUTED)
            if value:
                canvas.create_text(x + slot * 0.3, height - 30 - bar, text=inr0(value), fill=theme.INK, font=(theme.FONT, 8))
