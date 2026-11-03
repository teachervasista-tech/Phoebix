import tkinter as tk
from tkinter import ttk

from ..services import lookups
from . import theme
from .theme import card
from .widgets import Page, guarded

STORE_FIELDS = [("name", "Store name"), ("branch", "Branch"), ("address", "Address"), ("city", "City"),
                ("state", "State"), ("pincode", "PIN code"), ("phone", "Phone"), ("gstin", "GSTIN"),
                ("drugLicense", "Drug licence no."), ("invoicePrefix", "Invoice prefix")]
BANK_FIELDS = [("accountHolder", "Account holder"), ("bankName", "Bank name"), ("branch", "Branch"),
               ("accountNumber", "Account number"), ("ifsc", "IFSC"), ("upiId", "UPI ID")]


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Store profile and the bank account payments are made to"

    def build(self):
        self.header()
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        for column in (0, 1):
            body.columnconfigure(column, weight=1, uniform="s")
        self.store_vars = self.panel(body, 0, "Store profile", STORE_FIELDS, self.save_store)
        self.bank_vars = self.panel(body, 1, "Bank details for payments", BANK_FIELDS, self.save_bank, bank=True)

    def panel(self, parent, column, title, fields, command, bank=False):
        box = card(parent)
        box.grid(row=0, column=column, sticky="new", padx=(0 if column == 0 else 12, 0))
        ttk.Label(box, text=title, style="CardH2.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        variables = {}
        for row, (key, label) in enumerate(fields, start=1):
            ttk.Label(box, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            variables[key] = tk.StringVar()
            ttk.Entry(box, textvariable=variables[key], width=32).grid(row=row, column=1, sticky="ew", pady=4)
        row = len(fields) + 1
        if bank:
            ttk.Label(box, text="Account type", style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4)
            variables["accountType"] = tk.StringVar(value="Current")
            ttk.Combobox(box, textvariable=variables["accountType"], values=list(lookups.ACCOUNT_TYPES),
                         state="readonly").grid(row=row, column=1, sticky="ew", pady=4)
            row += 1
            self.bank_note = ttk.Label(box, text="", style="CardMuted.TLabel", wraplength=340)
            self.bank_note.grid(row=row, column=0, columnspan=2, sticky="w")
            row += 1
        button = ttk.Button(box, text="Save", style="Primary.TButton", command=command)
        button.grid(row=row, column=0, columnspan=2, sticky="e", pady=(12, 0))
        if bank:
            self.bank_button = button
        box.columnconfigure(1, weight=1)
        return variables

    def refresh(self):
        for key, value in self.svc.settings.store().items():
            if key in self.store_vars:
                self.store_vars[key].set(value)
        for key, value in self.svc.settings.bank().items():
            if key in self.bank_vars:
                self.bank_vars[key].set(value)
        admin = self.svc.session.is_admin
        self.bank_button.configure(state="normal" if admin else "disabled")
        self.bank_note.configure(text="Shown on invoices as 'Pay to'." if admin else
                                 "Only an administrator can change bank details.")

    def save_store(self):
        ok, _ = guarded(self, lambda: self.svc.settings.save_store({k: v.get() for k, v in self.store_vars.items()}))
        if ok:
            self.app.toast("Store profile saved.")

    def save_bank(self):
        ok, _ = guarded(self, lambda: self.svc.settings.save_bank({k: v.get() for k, v in self.bank_vars.items()}))
        if ok:
            self.app.toast("Bank details saved.")
            self.refresh()
