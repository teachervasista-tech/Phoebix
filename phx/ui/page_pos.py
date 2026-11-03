"""New Sale: product picker, cart, discounts, loyalty redemption, payment and checkout."""
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from ..services import lookups
from ..services.core import ServiceError
from . import theme
from .theme import DataTable, card, inr
from .widgets import FormDialog, Page, guarded

WALK_IN = "Walk-in customer"
POLL_MS = 5000


class PosPage(Page):
    title = "New Sale"
    subtitle = "Scan or pick products, apply rewards and bill"

    def build(self):
        self.cart, self.products, self.customers, self.offers = [], [], [], []
        self.pending_order = None
        self._poll_job = None
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=5, uniform="p")
        body.columnconfigure(1, weight=4, uniform="p")
        body.rowconfigure(0, weight=1)

        left = card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        top = ttk.Frame(left, style="Card.TFrame")
        top.pack(fill="x")
        self.search = tk.StringVar()
        self.category = tk.StringVar(value="All")
        entry = ttk.Entry(top, textvariable=self.search)
        entry.pack(side="left", fill="x", expand=True)
        self.category_box = ttk.Combobox(top, textvariable=self.category, state="readonly", width=16, values=["All"])
        self.category_box.pack(side="left", padx=(8, 0))
        self.search.trace_add("write", lambda *_: self.fill_products())
        self.category_box.bind("<<ComboboxSelected>>", lambda _e: self.fill_products())
        ttk.Label(left, text="Double-click a product (or press Add) to put it in the bill.", style="CardMuted.TLabel").pack(
            anchor="w", pady=(6, 6))
        self.product_table = DataTable(left, [("name", "Product", 230, "w"), ("category", "Category", 90, "w"),
                                              ("price", "Price", 80, "e"), ("gst", "GST", 50, "e"),
                                              ("stock", "Stock", 60, "e")], height=16,
                                       on_double=lambda pid: self.add_product(pid))
        self.product_table.pack(fill="both", expand=True)
        ttk.Button(left, text="Add to bill", command=lambda: self.add_product(self.product_table.selected())).pack(
            anchor="e", pady=(8, 0))

        right = card(body)
        right.grid(row=0, column=1, sticky="nsew")
        row = ttk.Frame(right, style="Card.TFrame")
        row.pack(fill="x")
        ttk.Label(row, text="Customer", style="Card.TLabel").pack(side="left")
        self.customer = tk.StringVar(value=WALK_IN)
        self.customer_box = ttk.Combobox(row, textvariable=self.customer, state="readonly", width=28)
        self.customer_box.pack(side="left", padx=8, fill="x", expand=True)
        self.customer_box.bind("<<ComboboxSelected>>", lambda _e: self.customer_changed())
        ttk.Button(row, text="+ New", command=self.new_customer).pack(side="left")
        self.cart_table = DataTable(right, [("name", "Item", 150, "w"), ("batch", "Batch", 70, "w"),
                                            ("qty", "Qty", 40, "e"), ("price", "Price", 70, "e"),
                                            ("amount", "Amount", 80, "e")], height=7)
        self.cart_table.pack(fill="both", expand=True, pady=(10, 4))
        qty = ttk.Frame(right, style="Card.TFrame")
        qty.pack(fill="x")
        for text, delta in (("−", -1), ("+", 1)):
            ttk.Button(qty, text=text, width=3, command=lambda d=delta: self.change_qty(d)).pack(side="left", padx=(0, 4))
        ttk.Button(qty, text="Remove", command=self.remove_line).pack(side="left")
        ttk.Button(qty, text="Clear", command=self.clear_cart).pack(side="left", padx=4)

        form = ttk.Frame(right, style="Card.TFrame")
        form.pack(fill="x", pady=(10, 0))
        form.columnconfigure(1, weight=1)
        self.offer = tk.StringVar(value="No offer")
        self.manual_kind, self.manual_value = tk.StringVar(value="percent"), tk.StringVar(value="0")
        self.redeem = tk.StringVar(value="0")
        ttk.Label(form, text="Offer", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=2)
        self.offer_box = ttk.Combobox(form, textvariable=self.offer, state="readonly")
        self.offer_box.grid(row=0, column=1, columnspan=2, sticky="ew", pady=2, padx=(8, 0))
        ttk.Label(form, text="Discount", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        discount_row = ttk.Frame(form, style="Card.TFrame")
        discount_row.grid(row=1, column=1, columnspan=2, sticky="w", pady=2, padx=(8, 0))
        ttk.Entry(discount_row, textvariable=self.manual_value, width=8).pack(side="left")
        ttk.Combobox(discount_row, textvariable=self.manual_kind, values=["percent", "fixed"], state="readonly",
                     width=8).pack(side="left", padx=6)
        ttk.Label(form, text="Redeem points", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=2)
        redeem_row = ttk.Frame(form, style="Card.TFrame")
        redeem_row.grid(row=2, column=1, columnspan=2, sticky="w", pady=2, padx=(8, 0))
        ttk.Entry(redeem_row, textvariable=self.redeem, width=8).pack(side="left")
        self.redeem_hint = ttk.Label(redeem_row, text="", style="CardMuted.TLabel")
        self.redeem_hint.pack(side="left", padx=6)
        for variable in (self.offer, self.manual_kind, self.manual_value, self.redeem):
            variable.trace_add("write", lambda *_: self.update_totals())

        self.totals_label = ttk.Label(right, text="", style="Card.TLabel", justify="right", font=(theme.FONT, 10))
        self.totals_label.pack(anchor="e", pady=(10, 0))
        self.total_big = ttk.Label(right, text=inr(0), style="Stat.TLabel")
        self.total_big.pack(anchor="e")
        pay = ttk.Frame(right, style="Card.TFrame")
        pay.pack(fill="x", pady=(6, 0))
        self.payment = tk.StringVar(value="Cash")
        for method in lookups.PAYMENT_METHODS:
            ttk.Radiobutton(pay, text=method, value=method, variable=self.payment,
                            command=self.update_totals).pack(side="left", padx=(0, 10))
        self.checkout_button = ttk.Button(right, text="Checkout", style="Primary.TButton", command=self.checkout)
        self.checkout_button.pack(fill="x", pady=(8, 0))
        self.pending = ttk.Frame(right, style="Card.TFrame")
        self.pending_label = ttk.Label(self.pending, text="", style="Card.TLabel", wraplength=360, justify="left")
        self.pending_label.pack(anchor="w")
        pending_buttons = ttk.Frame(self.pending, style="Card.TFrame")
        pending_buttons.pack(anchor="w", pady=(4, 0))
        ttk.Button(pending_buttons, text="Check payment status", command=self.check_payment).pack(side="left")
        ttk.Button(pending_buttons, text="Reopen PhonePe", command=self.reopen_payment).pack(side="left", padx=6)
        ttk.Button(pending_buttons, text="Dismiss", command=self.dismiss_payment).pack(side="left")
        self.redirect_url = None

    # ---- data ----------------------------------------------------------
    def refresh(self):
        self.products = self.svc.inventory.products()
        self.customers = self.svc.customers.list()
        self.offers = self.svc.loyalty.usable_offers()
        categories = ["All"] + sorted({p["category"] for p in self.products})
        self.category_box.configure(values=categories)
        names = [WALK_IN] + [f"{c['name']} · {c['phone']}" for c in self.customers]
        keep = self.customer.get()
        self.customer_box.configure(values=names)
        self.customer.set(keep if keep in names else WALK_IN)
        offer_names = ["No offer"] + [self.offer_label(o) for o in self.offers]
        self.offer_box.configure(values=offer_names)
        if self.offer.get() not in offer_names:
            self.offer.set("No offer")
        self.fill_products()
        self.update_totals()

    @staticmethod
    def offer_label(offer):
        value = f"{offer['discount']:g}%" if offer["type"] == "percent" else f"₹{offer['discount']:g}"
        return f"{offer['name']} ({value} off)"

    def fill_products(self):
        text, category = self.search.get().strip().lower(), self.category.get()
        rows = []
        for p in self.products:
            if category not in ("All", "") and p["category"] != category:
                continue
            if text and text not in f"{p['name']} {p['brand']} {p['hsn']}".lower():
                continue
            sellable = any(b["stock"] > 0 and not lookups.is_expired(b["expiry"]) for b in p["batches"])
            rows.append((p["id"], (p["name"], p["category"], inr(p["price"]), f"{p['gst']}%", p["stock"]),
                         None if sellable else "muted"))
        self.product_table.set_rows(rows)

    def selected_customer(self):
        name = self.customer.get()
        if name == WALK_IN:
            return None
        values = list(self.customer_box.cget("values"))
        index = values.index(name) - 1 if name in values else -1
        return self.customers[index] if 0 <= index < len(self.customers) else None

    def selected_offer(self):
        label = self.offer.get()
        return next((o for o in self.offers if self.offer_label(o) == label), None)

    def request(self):
        customer, offer = self.selected_customer(), self.selected_offer()
        try:
            manual_value = float(self.manual_value.get() or 0)
        except ValueError:
            manual_value = 0
        try:
            redeem = int(self.redeem.get() or 0)
        except ValueError:
            redeem = 0
        return {"lines": [{"productId": l["productId"], "batchId": l["batchId"], "qty": l["qty"]} for l in self.cart],
                "customerId": customer["id"] if customer else None, "offerId": offer["id"] if offer else None,
                "manual": None if offer else (self.manual_kind.get(), manual_value), "redeem": max(redeem, 0)}

    # ---- cart ----------------------------------------------------------
    def add_product(self, product_id):
        product = next((p for p in self.products if p["id"] == product_id), None)
        if not product:
            return
        reserved = {}
        for line in self.cart:
            reserved[line["batchId"]] = reserved.get(line["batchId"], 0) + line["qty"]
        batch = self.svc.inventory.pick_batch(product, reserved)
        if not batch:
            self.app.toast("No unexpired batch stock is available.")
            return
        line = next((l for l in self.cart if l["batchId"] == batch["id"]), None)
        if line:
            line["qty"] += 1
        else:
            self.cart.append({"productId": product["id"], "batchId": batch["id"], "name": product["name"],
                              "batch": batch["batch"], "price": product["price"], "qty": 1, "stock": batch["stock"]})
        self.redraw_cart()

    def selected_line(self):
        key = self.cart_table.selected()
        return next((l for l in self.cart if l["batchId"] == key), None)

    def change_qty(self, delta):
        line = self.selected_line()
        if not line:
            return
        if delta > 0 and line["qty"] >= line["stock"]:
            self.app.toast("No more units are available in this batch.")
            return
        line["qty"] += delta
        if line["qty"] <= 0:
            self.cart.remove(line)
        self.redraw_cart(line["batchId"])

    def remove_line(self):
        line = self.selected_line()
        if line:
            self.cart.remove(line)
            self.redraw_cart()

    def clear_cart(self):
        self.cart.clear()
        self.redeem.set("0")
        self.redraw_cart()

    def redraw_cart(self, keep=None):
        self.cart_table.set_rows([(l["batchId"], (l["name"], l["batch"], l["qty"], inr(l["price"]),
                                                  inr(l["qty"] * l["price"])), None) for l in self.cart])
        if keep and self.cart_table.tree.exists(keep):
            self.cart_table.tree.selection_set(keep)
        self.update_totals()

    def customer_changed(self):
        self.redeem.set("0")
        self.update_totals()

    def update_totals(self):
        if not hasattr(self, "totals_label"):
            return
        totals = self.svc.billing.quote(self.request())
        customer = self.selected_customer()
        self.redeem_hint.configure(text=f"max {totals['maxRedeem']} of {customer['points']}" if customer else "select a customer")
        self.totals_label.configure(text=(
            f"Subtotal  {inr(totals['subtotal'])}\nDiscount  −{inr(totals['discount'])}\n"
            f"GST  {inr(totals['tax'])}\nPoints  −{inr(totals['redeem'])}"))
        self.total_big.configure(text=inr(totals["total"]))
        online = self.payment.get() in lookups.ONLINE_METHODS
        self.checkout_button.configure(text="Pay with PhonePe" if online else "Checkout",
                                       state="disabled" if self.pending_order else "normal")

    # ---- customers -----------------------------------------------------
    def new_customer(self):
        def save(values):
            created = self.svc.customers.add(values)
            self.refresh()
            self.customer.set(f"{created['name']} · {created['phone']}")
            self.update_totals()
            self.app.toast(f"{created['name']} added to customers.")
        open_customer_form(self, save)

    # ---- checkout ------------------------------------------------------
    def checkout(self):
        method = self.payment.get()
        request = self.request()
        if method in lookups.ONLINE_METHODS:
            ok, started = guarded(self, lambda: self.svc.payments.start(request, method))
            if not ok:
                return
            self.pending_order, self.redirect_url = started["merchantOrderId"], started["redirectUrl"]
            webbrowser.open(self.redirect_url)
            self.show_pending("Complete the payment in your browser. Phoebix will confirm it automatically.")
            self.schedule_poll()
            return
        ok, sale = guarded(self, lambda: self.svc.billing.checkout(request, method))
        if ok:
            self.sale_done(sale)

    def sale_done(self, sale):
        self.cart.clear()
        self.redeem.set("0")
        self.manual_value.set("0")
        self.offer.set("No offer")
        self.dismiss_payment()
        self.refresh()
        self.redraw_cart()
        self.app.toast(f"{sale['id']} saved · {inr(sale['total'])} · billed by {sale['soldBy']['username']}")
        self.app.open_invoice(sale["id"])

    # ---- PhonePe -------------------------------------------------------
    def show_pending(self, text):
        self.pending_label.configure(text=text)
        self.pending.pack(fill="x", pady=(8, 0))
        self.update_totals()

    def dismiss_payment(self):
        if self._poll_job:
            self.after_cancel(self._poll_job)
            self._poll_job = None
        self.pending_order = None
        self.pending.pack_forget()
        self.update_totals()

    def reopen_payment(self):
        if self.redirect_url:
            webbrowser.open(self.redirect_url)

    def schedule_poll(self):
        self._poll_job = self.after(POLL_MS, lambda: self.check_payment(quiet=True))

    def check_payment(self, quiet=False):
        if not self.pending_order:
            return
        try:
            result = self.svc.payments.check(self.pending_order)
        except ServiceError as error:
            if quiet:
                self.pending_label.configure(text=f"{error}\nWill keep retrying…")
                self.schedule_poll()
            else:
                messagebox.showerror("Phoebix", str(error), parent=self.winfo_toplevel())
            return
        status = result["status"]
        if status == "COMPLETED":
            self.sale_done(result["sale"])
        elif status in ("FAILED", "EXPIRED"):
            self.dismiss_payment()
            messagebox.showwarning("Phoebix", f"The PhonePe payment {status.lower()}. No sale was recorded.",
                                   parent=self.winfo_toplevel())
        elif status == "RECONCILIATION_REQUIRED":
            self.dismiss_payment()
            messagebox.showerror("Phoebix", result.get("message", "Reconcile this payment."), parent=self.winfo_toplevel())
        else:
            self.pending_label.configure(text="Waiting for the payment to be completed…")
            self.schedule_poll()


def open_customer_form(parent, on_save):
    return FormDialog(parent, "Add customer", [
        ("name", "Name *", "text", None, ""), ("phone", "Phone *", "text", None, ""),
        ("email", "Email", "text", None, ""), ("address", "Address", "text", None, ""),
        ("state", "State", "text", None, ""), ("gstin", "GSTIN", "text", None, ""),
        ("drugLicense", "Drug licence no.", "text", None, "")], on_save, "Save customer")
