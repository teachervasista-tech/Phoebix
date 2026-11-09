import tkinter as tk
from tkinter import ttk

from ..services.core import ServiceError
from .theme import DataTable, card
from .widgets import FormDialog, Page, guarded


class RewardsPage(Page):
    title = "Rewards & Offers"
    subtitle = "Points, redemption limits and discount offers"

    def build(self):
        self.header([("+ New offer", self.add_offer, True)])
        self.stats = {}
        tiles = ttk.Frame(self)
        tiles.pack(fill="x")
        for index, (key, caption) in enumerate([("earned", "Points earned this month"),
                                                ("redeemed", "Points redeemed this month"),
                                                ("visit", "Customers with a purchase")]):
            tile = card(tiles)
            tile.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 12, 0))
            tiles.columnconfigure(index, weight=1, uniform="r")
            ttk.Label(tile, text=caption, style="CardMuted.TLabel").pack(anchor="w")
            self.stats[key] = ttk.Label(tile, text="—", style="Stat.TLabel")
            self.stats[key].pack(anchor="w")
        lower = ttk.Frame(self)
        lower.pack(fill="both", expand=True, pady=(14, 0))
        lower.columnconfigure(0, weight=2, uniform="x")
        lower.columnconfigure(1, weight=3, uniform="x")
        lower.rowconfigure(0, weight=1)

        rules = card(lower)
        rules.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        ttk.Label(rules, text="Earning & redemption", style="CardH2.TLabel").pack(anchor="w")
        self.vars = {k: tk.StringVar() for k in ("earnPer", "pointsPerRupee", "redeemMaxPercent")}
        for key, label in (("earnPer", "Spend (₹) per step"), ("pointsPerRupee", "Points earned per step"),
                           ("redeemMaxPercent", "Max % of bill payable with points")):
            ttk.Label(rules, text=label, style="Card.TLabel").pack(anchor="w", pady=(10, 0))
            ttk.Entry(rules, textvariable=self.vars[key], width=12).pack(anchor="w")
        self.save_button = ttk.Button(rules, text="Save rules", style="Primary.TButton", command=self.save_rules)
        self.save_button.pack(anchor="w", pady=(12, 8))
        self.toggles = {}
        for key, label in (("birthday", "Birthday bonus points"), ("wellness", "Wellness programme points"),
                           ("refill", "Refill reminder bonus")):
            var = tk.BooleanVar()
            check = ttk.Checkbutton(rules, text=label, variable=var, command=lambda k=key: self.toggle_rule(k))
            check.pack(anchor="w", pady=2)
            self.toggles[key] = (var, check)
        ttk.Label(rules, text="1 point = ₹1 when redeemed.", style="CardMuted.TLabel").pack(anchor="w", pady=(10, 0))

        offers = card(lower)
        offers.grid(row=0, column=1, sticky="nsew")
        ttk.Label(offers, text="Offers", style="CardH2.TLabel").pack(anchor="w")
        self.table = DataTable(offers, [("name", "Offer", 180, "w"), ("value", "Discount", 90, "e"),
                                        ("end", "Valid until", 100, "w"), ("state", "Status", 80, "w")], height=10)
        self.table.pack(fill="both", expand=True, pady=(8, 8))
        row = ttk.Frame(offers, style="Card.TFrame")
        row.pack(anchor="w")
        self.toggle_button = ttk.Button(row, text="Enable / disable", command=self.toggle_offer)
        self.toggle_button.pack(side="left")
        self.delete_button = ttk.Button(row, text="Delete", command=self.delete_offer)
        self.delete_button.pack(side="left", padx=6)
        self.offers = []

    def refresh(self):
        stats = self.svc.loyalty.stats()
        self.stats["earned"].configure(text=f"{stats['earned']:,}")
        self.stats["redeemed"].configure(text=f"{stats['redeemed']:,}")
        self.stats["visit"].configure(text=f"{stats['memberVisitPercent']}%")
        rules = self.svc.loyalty.rules()
        for key, var in self.vars.items():
            var.set(str(rules[key]))
        for key, (var, _check) in self.toggles.items():
            var.set(rules[key])
        self.offers = self.svc.loyalty.offers()
        self.table.set_rows([(o["id"], (o["name"], f"{o['discount']:g}%" if o["type"] == "percent" else f"₹{o['discount']:g}",
                                         o["end"], "Active" if o["enabled"] else "Off"), None if o["enabled"] else "muted")
                             for o in self.offers])
        state = "normal" if self.svc.session.is_admin else "disabled"
        for widget in (self.save_button, self.toggle_button, self.delete_button):
            widget.configure(state=state)
        for _var, check in self.toggles.values():
            check.configure(state=state)

    def save_rules(self):
        ok, _ = guarded(self, lambda: self.svc.loyalty.save_rules({k: v.get() for k, v in self.vars.items()}))
        if ok:
            self.app.toast("Reward rules saved.")
        self.refresh()

    def toggle_rule(self, key):
        guarded(self, lambda: self.svc.loyalty.toggle_rule(key))
        self.refresh()

    def add_offer(self):
        def save(values):
            self.svc.loyalty.add_offer(values["name"], values["discount"], values["type"], values["end"])
            self.refresh()
        FormDialog(self, "New offer", [("name", "Offer name *", "text", None, ""),
                                       ("discount", "Discount *", "text", None, "10"),
                                       ("type", "Type", "combo", ["percent", "fixed"], "percent"),
                                       ("end", "Valid until", "date", None, "")], save, "Create offer",
                   note="Administrators only.")

    def toggle_offer(self):
        if self.table.selected():
            guarded(self, lambda: self.svc.loyalty.toggle_offer(self.table.selected()))
            self.refresh()

    def delete_offer(self):
        if self.table.selected():
            guarded(self, lambda: self.svc.loyalty.delete_offer(self.table.selected()))
            self.refresh()
