import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..services import lookups
from . import theme
from .theme import card
from .widgets import Page, ScrollFrame, guarded

STORE_FIELDS = [("name", "Store name"), ("branch", "Branch"), ("address", "Address"), ("city", "City"),
                ("state", "State"), ("pincode", "PIN code"), ("phone", "Phone"), ("gstin", "GSTIN"),
                ("drugLicense", "Drug licence no."), ("invoicePrefix", "Invoice prefix")]
BANK_FIELDS = [("accountHolder", "Account holder"), ("bankName", "Bank name"), ("branch", "Branch"),
               ("accountNumber", "Account number"), ("ifsc", "IFSC"), ("upiId", "UPI ID")]


class SettingsPage(Page):
    title = "Settings"
    subtitle = "Store profile, bank account for payments, and backups · administrators only"
    admin_only = True

    def build(self):
        self.header()
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        body = self.scroller.inner
        body.configure(padding=(0, 0, 12, 12))
        for column in (0, 1):
            body.columnconfigure(column, weight=1, uniform="s")
        self.store_vars = self.panel(body, 0, "Store profile", STORE_FIELDS, self.save_store)
        self.bank_vars = self.panel(body, 1, "Bank details for payments", BANK_FIELDS, self.save_bank, bank=True)
        self.backup_panel(body)

    # ---- backup & restore ----------------------------------------------
    def backup_panel(self, parent):
        box = card(parent)
        box.grid(row=1, column=0, columnspan=2, sticky="new", pady=(12, 0))
        box.columnconfigure(1, weight=1)
        ttk.Label(box, text="Backup & Restore", style="CardH2.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(box, text="Backups are taken automatically on start (once a day) and when Phoebix closes. "
                            "For a cloud copy, choose a folder inside Google Drive or OneDrive on this PC — "
                            "their desktop app uploads it.", style="CardMuted.TLabel", wraplength=760,
                  justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 6))
        self.backup_vars = {k: tk.StringVar() for k in ("localDir", "cloudDir", "keep")}
        self.backup_auto = tk.BooleanVar(value=True)
        rows = [("localDir", "Local backup folder"), ("cloudDir", "Cloud-synced folder (optional)")]
        for row, (key, label) in enumerate(rows, start=2):
            ttk.Label(box, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
            ttk.Entry(box, textvariable=self.backup_vars[key]).grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Button(box, text="Browse…", command=lambda k=key: self.pick_folder(k)).grid(row=row, column=2, padx=(6, 0))
        ttk.Label(box, text="Backups to keep", style="Card.TLabel").grid(row=4, column=0, sticky="w", pady=4)
        keep_row = ttk.Frame(box, style="Card.TFrame")
        keep_row.grid(row=4, column=1, sticky="w")
        ttk.Entry(keep_row, textvariable=self.backup_vars["keep"], width=6).pack(side="left")
        ttk.Checkbutton(keep_row, text="Automatic backups", variable=self.backup_auto).pack(side="left", padx=12)
        self.cloud_hint = ttk.Label(box, text="", style="CardMuted.TLabel", wraplength=760, justify="left")
        self.cloud_hint.grid(row=5, column=0, columnspan=3, sticky="w")
        self.backup_status = ttk.Label(box, text="", style="Card.TLabel", wraplength=760, justify="left")
        self.backup_status.grid(row=6, column=0, columnspan=3, sticky="w", pady=(6, 0))
        buttons = ttk.Frame(box, style="Card.TFrame")
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Restore from backup…", command=self.restore_backup).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Open backup folder", command=self.open_backup_folder).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Backup now", command=self.backup_now).pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Save", style="Primary.TButton", command=self.save_backup).pack(side="left")

    def refresh_backup(self):
        s = self.svc.backup.settings()
        self.backup_vars["localDir"].set(s["localDir"] or s["effectiveLocalDir"])
        self.backup_vars["cloudDir"].set(s["cloudDir"])
        self.backup_vars["keep"].set(str(s["keep"]))
        self.backup_auto.set(bool(s.get("auto", True)))
        suggestions = self.svc.backup.cloud_suggestions()
        self.cloud_hint.configure(text=("Suggested cloud folder: " + suggestions[0]) if suggestions and not s["cloudDir"]
                                  else ("" if s["cloudDir"] else
                                        "No Google Drive / OneDrive folder found on this PC. Install the Drive or "
                                        "OneDrive desktop app, then choose a folder inside it."))
        last = s.get("lastOk") or "never"
        status = s.get("lastStatus") or "—"
        self.backup_status.configure(text=f"Last successful backup: {last.replace('T', ' ')}   ·   Last result: {status}")

    def pick_folder(self, key):
        path = filedialog.askdirectory(parent=self, initialdir=self.backup_vars[key].get() or None,
                                       title="Choose backup folder")
        if path:
            self.backup_vars[key].set(os.path.normpath(path))

    def backup_values(self):
        return {"localDir": self.backup_vars["localDir"].get(), "cloudDir": self.backup_vars["cloudDir"].get(),
                "keep": self.backup_vars["keep"].get(), "auto": self.backup_auto.get()}

    def save_backup(self):
        ok, _ = guarded(self, lambda: self.svc.backup.save_settings(self.backup_values()))
        if ok:
            self.app.toast("Backup settings saved.")
            self.refresh_backup()

    def backup_now(self):
        ok, _ = guarded(self, lambda: self.svc.backup.save_settings(self.backup_values()))
        if not ok:
            return
        self.configure(cursor="watch")
        self.update_idletasks()
        try:
            ok, result = guarded(self, lambda: self.svc.backup.backup_now())
        finally:
            self.configure(cursor="")
        if ok:
            if result["cloudError"]:
                messagebox.showwarning("Phoebix", f"Saved locally:\n{result['file']}\n\nCloud copy failed:\n"
                                       f"{result['cloudError']}", parent=self.winfo_toplevel())
            else:
                self.app.toast(f"Backup saved: {result['file']}" + (" (and cloud folder)" if result["cloudFile"] else ""))
        self.refresh_backup()

    def open_backup_folder(self):
        folder = self.svc.backup.settings()["effectiveLocalDir"]
        if os.path.isdir(folder) and hasattr(os, "startfile"):
            os.startfile(folder)  # noqa: S606 - opens Explorer on a local folder
        else:
            self.app.toast("No backups have been saved yet.")

    def restore_backup(self):
        folder = self.svc.backup.settings()["effectiveLocalDir"]
        path = filedialog.askopenfilename(parent=self, title="Choose a Phoebix backup",
                                          initialdir=folder if os.path.isdir(folder) else None,
                                          filetypes=[("Phoebix backup", "*.zip *.sqlite3"), ("All files", "*.*")])
        if not path:
            return
        if not messagebox.askyesno(
                "Restore backup",
                f"Replace ALL current data with this backup?\n\n{os.path.basename(path)}\n\n"
                "A safety backup of the current data is taken first. Phoebix will close afterwards; "
                "open it again to continue.", icon="warning", parent=self.winfo_toplevel()):
            return
        ok, result = guarded(self, lambda: self.svc.backup.restore(path))
        if ok:
            messagebox.showinfo("Phoebix", "Backup restored. Phoebix will now close — please open it again.\n\n"
                                f"Safety backup of the previous data:\n{result['safetyBackup']}",
                                parent=self.winfo_toplevel())
            self.app.on_close(backup=False)

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
        self.refresh_backup()
        self.bank_note.configure(text="Shown on invoices as 'Pay to'.")

    def save_store(self):
        ok, _ = guarded(self, lambda: self.svc.settings.save_store({k: v.get() for k, v in self.store_vars.items()}))
        if ok:
            self.app.toast("Store profile saved.")

    def save_bank(self):
        ok, _ = guarded(self, lambda: self.svc.settings.save_bank({k: v.get() for k, v in self.bank_vars.items()}))
        if ok:
            self.app.toast("Bank details saved.")
            self.refresh()
