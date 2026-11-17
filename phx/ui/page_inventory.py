import tkinter as tk
from tkinter import filedialog, ttk

from ..services import lookups
from . import theme
from .theme import DataTable, card, inr
from .widgets import FormDialog, Page, center_on_main, guarded


class InventoryPage(Page):
    title = "Inventory"
    subtitle = "Batches, expiry and reorder levels"

    def build(self):
        self.header([("Export CSV", self.export, False), ("Edit product", self.edit_product, False),
                     ("Receive stock", self.receive_selected, False), ("+ Add product", lambda: self.add(), True)])
        scan_bar = card(self, padding=(14, 10))
        scan_bar.pack(fill="x", pady=(0, 10))
        ttk.Label(scan_bar, text="▮▯▮▮▯▮  Scan barcode", style="Card.TLabel",
                  font=(theme.FONT, 10, "bold")).pack(side="left")
        self.scan_text = tk.StringVar()
        self.scan_entry = ttk.Entry(scan_bar, textvariable=self.scan_text, width=40)
        self.scan_entry.pack(side="left", padx=10)
        self.scan_entry.bind("<Return>", lambda _e: self.on_scan())
        ttk.Button(scan_bar, text="Find", command=self.on_scan).pack(side="left")
        ttk.Label(scan_bar, text="Scan a pack, or type its code + Enter",
                  style="CardMuted.TLabel").pack(side="left", padx=10)
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
                                      ("expiry", "Expiry", 90, "w"), ("pack", "Per strip", 65, "e"),
                                      ("stock", "Stock", 130, "e"),
                                      ("reorder", "Reorder", 70, "e"), ("price", "Price", 80, "e"),
                                      ("mrp", "MRP", 80, "e")], height=18)
        self.table.pack(fill="both", expand=True)
        ttk.Label(self, text="Each batch is listed on its own row; the earliest-expiry batch is billed first.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        self.products = []

    def refresh(self):
        self.products = self.svc.inventory.products()
        self.fill()
        self.after_idle(self.focus_scan)

    def focus_scan(self):
        # Keep the scan box ready so a scanner "types" into it, unless a dialog is open.
        if self.winfo_ismapped() and self.grab_current() is None:
            self.scan_entry.focus_set()

    def fill(self):
        text, mode = self.search.get().strip().lower(), self.filter.get()
        rows, low, near = [], 0, 0
        for p in self.products:
            if text and text not in f"{p['name']} {p['brand']} {p['category']} {p['hsn']} {p['barcode']}".lower():
                continue
            is_low = lookups.is_low_stock(p)
            per_pack = lookups.pack_size(p)
            pack_text = f"{per_pack}{' · loose' if p.get('allowLoose') else ''}" if per_pack > 1 else "—"
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
                                                     b["expiry"], pack_text, lookups.format_stock(b["stock"], per_pack),
                                                     p["reorder"], inr(p["price"]),
                                                     inr(p["mrp"])), tag))
        self.table.set_rows(rows)
        self.summary.configure(text=f"{len(self.products)} products · {low} low stock · {near} batches near expiry")

    # ---- barcode scanning ------------------------------------------------
    def on_scan(self):
        text = self.scan_text.get()
        self.scan_text.set("")
        if not text.strip():
            return
        ok, scan = guarded(self, lambda: self.svc.inventory.lookup_scan(text))
        if not ok:
            return
        if scan["product"]:
            self.app.toast(f"Found {scan['product']['name']}.")
            self.receive(scan["product"], scan)
        else:
            UnknownBarcodeDialog(self, scan)

    def link_and_receive(self, product, scan):
        ok, updated = guarded(self, lambda: self.svc.inventory.link_barcode(product["id"], scan["code"]))
        if ok:
            self.refresh()
            self.app.toast(f"Barcode {scan['code']} linked to {updated['name']}.")
            self.receive(updated, scan)

    # ---- dialogs ---------------------------------------------------------
    def selected_product(self):
        selected = self.table.selected()
        product = next((p for p in self.products if selected and p["id"] == selected.split("|")[0]), None)
        if not product:
            self.app.toast("Select a product row first.")
        return product

    def add(self, scan=None):
        scan = scan or {}

        def save(values):
            product = self.svc.inventory.add_product(values)
            self.app.toast(f"{product['name']} added.")
            self.refresh()
        note = ("New barcode — enter the product details. Batch and expiry were read from the barcode where "
                "available; change anything that is not right.") if scan else None
        FormDialog(self, "Add product", product_fields({}, scan) + [
            ("stock", "Opening stock (strips)", "text", None, "0"),
            ("batch", "Batch no. (if stock)", "text", None, scan.get("batch", "")),
            ("expiry", "Expiry date (if stock)", "date", "future", scan.get("expiry", "")),
        ], save, "Add product", note=note)

    def edit_product(self):
        if not self.svc.session.is_admin:
            self.app.toast("Only an administrator can edit products.")
            return
        product = self.selected_product()
        if not product:
            return

        def save(values):
            updated = self.svc.inventory.update_product(product["id"], values)
            self.app.toast(f"{updated['name']} updated.")
            self.refresh()
        FormDialog(self, f"Edit {product['name']}", product_fields(product, {}), save, "Save changes",
                   note="Changing tablets per strip converts the stock on hand (e.g. 5 strips → 50 tablets). "
                        "Administrators only.")

    def receive_selected(self):
        product = self.selected_product()
        if product:
            self.receive(product)

    def receive(self, product, scan=None):
        scan = scan or {}
        per_pack = lookups.pack_size(product)
        admin = self.svc.session.is_admin

        def save(values):
            self.svc.inventory.receive_stock(product["id"], values["batch"], values["expiry"], values["quantity"],
                                             values.get("loose") or 0, values.get("price"), values.get("mrp"))
            self.app.toast(f"Stock received for {product['name']}.")
            self.refresh()
        price_kind = "text" if admin else "readonly"
        fields = [("product", "Product", "readonly", None, product["name"]),
                  ("barcode", "Barcode", "readonly", None, product.get("barcode") or "—"),
                  ("batch", "Batch no. *", "text", None, scan.get("batch", "")),
                  ("expiry", "Expiry date *", "date", "future", scan.get("expiry", "")),
                  ("quantity", f"Quantity (strips of {per_pack}) *" if per_pack > 1 else "Quantity *", "text", None, "")]
        if per_pack > 1:
            fields.append(("loose", "Extra loose tablets", "text", None, "0"))
        fields += [("price", "Selling price per strip/pack", price_kind, None, f"{product['price']:g}"),
                   ("mrp", "MRP per strip/pack", price_kind, None, f"{product['mrp']:g}")]
        note = None
        if scan.get("batch") or scan.get("expiry"):
            note = "Batch and expiry were read from the barcode — check them against the pack and change if needed."
        elif scan:
            note = "This barcode has no batch/expiry; enter them from the pack."
        if admin:
            note = (note + " " if note else "") + "Update price/MRP if this stock is priced differently."
        FormDialog(self, "Receive stock", fields, save, "Receive", note=note)

    def export(self):
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="phoebix-inventory.csv",
                                            filetypes=[("CSV", "*.csv")])
        if path:
            self.svc.reports.export_inventory(path)
            self.app.toast(f"Saved {path}")


CATEGORIES = ["Tablets", "Capsules", "Syrups", "Injections", "Ointments", "Devices", "Personal care", "Wellness",
              "Others"]


def product_fields(product, scan):
    """Editable product fields, pre-filled from an existing product and/or a scan."""
    p = product
    per_pack = lookups.pack_size(p) if p else 1
    category = p.get("category") or "Tablets"
    return [
        ("name", "Product name *", "text", None, p.get("name", "")),
        ("brand", "Brand · pack", "text", None, p.get("brand", "")),
        ("barcode", "Barcode", "text", None, scan.get("code") or p.get("barcode", "")),
        ("category", "Category", "combo", CATEGORIES if category in CATEGORIES else CATEGORIES + [category], category),
        ("hsn", "HSN code", "text", None, p.get("hsn", "")),
        ("unitsPerPack", "Tablets per strip (1 if not sold loose)", "text", None, str(per_pack)),
        ("allowLoose", "Allow loose tablet sale", "combo", ["Yes", "No"],
         "Yes" if (p.get("allowLoose") if p else True) else "No"),
        ("price", "Selling price per strip/pack *", "text", None, f"{p['price']:g}" if p else ""),
        ("mrp", "MRP per strip/pack *", "text", None, f"{p['mrp']:g}" if p else ""),
        ("gst", "GST % *", "combo", [str(g) for g in lookups.GST_RATES], str(p.get("gst", 12))),
        ("reorder", "Reorder level (strips)", "text", None, str(p.get("reorder", 10))),
    ]


class UnknownBarcodeDialog(tk.Toplevel):
    """A barcode that matches no product: add a new product, or attach it to an existing one."""

    def __init__(self, page, scan):
        super().__init__(page)
        self.withdraw()
        self.page, self.scan = page, scan
        self.title("New barcode")
        self.transient(page.winfo_toplevel())
        self.configure(background=theme.CARD, padx=22, pady=18)
        self.resizable(False, False)
        ttk.Label(self, text="Barcode not found", style="CardH2.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        details = f"Code {scan['code']}"
        if scan.get("batch"):
            details += f" · batch {scan['batch']}"
        if scan.get("expiry"):
            details += f" · expiry {scan['expiry']}"
        ttk.Label(self, text=details, style="CardMuted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w",
                                                                      pady=(2, 12))
        ttk.Button(self, text="Add as a new product…", style="Primary.TButton", command=self.new_product).grid(
            row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(self, text="…or this pack is a product already in the list:", style="Card.TLabel").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(14, 4))
        # Products without a barcode first; they are the likely match.
        products = sorted(page.products, key=lambda p: (bool(p["barcode"]), p["name"].lower()))
        self.choices = {f"{p['name']} · {p['brand']}" + (" (has a barcode)" if p["barcode"] else ""): p
                        for p in products}
        self.choice = tk.StringVar()
        ttk.Combobox(self, textvariable=self.choice, values=list(self.choices), state="readonly", width=46).grid(
            row=4, column=0, sticky="ew")
        ttk.Button(self, text="Link barcode", command=self.link).grid(row=4, column=1, padx=(8, 0))
        self.error = ttk.Label(self, text="", style="Bad.TLabel")
        self.error.grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Button(self, text="Cancel", command=self.destroy).grid(row=6, column=1, sticky="e", pady=(10, 0))
        self.bind("<Escape>", lambda _e: self.destroy())
        center_on_main(self)
        self.lift()
        self.focus_set()
        self._grab()

    def _grab(self, tries=20):
        try:
            self.grab_set()
        except tk.TclError:
            if tries and self.winfo_exists():
                self.after(50, lambda: self._grab(tries - 1))

    def new_product(self):
        self.destroy()
        self.page.add(self.scan)

    def link(self):
        product = self.choices.get(self.choice.get())
        if not product:
            self.error.configure(text="Choose a product first.")
            return
        self.destroy()
        self.page.link_and_receive(product, self.scan)
