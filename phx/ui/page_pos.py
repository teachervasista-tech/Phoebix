"""New Sale: product picker, cart, discounts, loyalty redemption, payment and checkout."""
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from ..services import lookups
from ..services.core import ServiceError
from . import theme
from .theme import DataTable, card, inr
from .widgets import FormDialog, Page, center_on_main, guarded

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
        ttk.Label(top, text="▮▯▮▮▯▮  Search or scan", style="Card.TLabel",
                  font=(theme.FONT, 10, "bold")).pack(side="left", padx=(0, 8))
        self.search_entry = ttk.Entry(top, textvariable=self.search)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda _e: self.on_search_enter())
        self.category_box = ttk.Combobox(top, textvariable=self.category, state="readonly", width=16, values=["All"])
        self.category_box.pack(side="left", padx=(8, 0))
        self.search.trace_add("write", lambda *_: self.fill_products())
        self.category_box.bind("<<ComboboxSelected>>", lambda _e: self.fill_products())
        ttk.Label(left, text="Scan a pack's barcode, or search and double-click a product. For tablets you choose "
                             "strips and/or loose tablets.", style="CardMuted.TLabel", wraplength=520).pack(
            anchor="w", pady=(6, 6))
        self.product_table = DataTable(left, [("name", "Product", 170, "w"), ("category", "Category", 80, "w"),
                                              ("price", "Strip/pack", 72, "e"), ("loose", "Per tab", 58, "e"),
                                              ("gst", "GST", 40, "e"), ("stock", "Stock", 110, "e")], height=16,
                                       on_double=lambda pid: self.pick_product(pid))
        self.product_table.tree.bind("<Return>", lambda _e: self.pick_product(self.product_table.selected()))
        self.product_table.pack(fill="both", expand=True)
        ttk.Button(left, text="Add to bill…", style="Primary.TButton",
                   command=lambda: self.pick_product(self.product_table.selected())).pack(anchor="e", pady=(8, 0))

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
        self.cart_list = CartList(right, on_change=self.change_line_qty, on_remove=self.remove_line)
        self.cart_list.pack(fill="both", expand=True, pady=(10, 4))
        cart_bar = ttk.Frame(right, style="Card.TFrame")
        cart_bar.pack(fill="x")
        self.cart_count = ttk.Label(cart_bar, text="", style="CardMuted.TLabel")
        self.cart_count.pack(side="left")
        ttk.Button(cart_bar, text="Clear bill", command=self.clear_cart).pack(side="right")

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
        self.after_idle(self.focus_search)

    @staticmethod
    def offer_label(offer):
        value = f"{offer['discount']:g}%" if offer["type"] == "percent" else f"₹{offer['discount']:g}"
        return f"{offer['name']} ({value} off)"

    def fill_products(self):
        text, category = self.search.get().strip().lower(), self.category.get()
        rows = []
        self.visible_ids = []
        for p in self.products:
            if category not in ("All", "") and p["category"] != category:
                continue
            if text and text not in f"{p['name']} {p['brand']} {p['hsn']} {p['barcode']}".lower():
                continue
            self.visible_ids.append(p["id"])
            sellable = any(b["stock"] > 0 and not lookups.is_expired(b["expiry"]) for b in p["batches"])
            loose = inr(lookups.unit_price(p, "loose")) if p.get("allowLoose") else "—"
            rows.append((p["id"], (p["name"], p["category"], inr(p["price"]), loose, f"{p['gst']}%",
                                   lookups.format_stock(p["stock"], lookups.pack_size(p))),
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
        return {"lines": [{"productId": l["productId"], "batchId": l["batchId"], "qty": l["qty"], "unit": l["unit"]}
                          for l in self.cart],
                "customerId": customer["id"] if customer else None, "offerId": offer["id"] if offer else None,
                "manual": None if offer else (self.manual_kind.get(), manual_value), "redeem": max(redeem, 0)}

    # ---- cart ----------------------------------------------------------
    @staticmethod
    def line_key(line):
        return f"{line['batchId']}|{line['unit']}"

    def reserved_units(self, exclude=None):
        """Base units (tablets) already taken from each batch by the cart."""
        reserved = {}
        for line in self.cart:
            if line is not exclude:
                reserved[line["batchId"]] = reserved.get(line["batchId"], 0) + line["qty"] * line["perUnit"]
        return reserved

    def product(self, product_id):
        return next((p for p in self.products if p["id"] == product_id), None)

    def on_search_enter(self):
        """Enter in the search box: a scanned barcode adds that product; otherwise a single match is added."""
        text = self.search.get().strip()
        if not text:
            return
        try:
            scan = self.svc.inventory.lookup_scan(text)
        except ServiceError:
            scan = {"product": None}
        if scan["product"]:
            self.search.set("")
            self.pick_product(scan["product"]["id"], batch_no=scan.get("batch") or None)
            return
        if len(self.visible_ids) == 1:
            only = self.visible_ids[0]  # clearing the search below re-lists everything
            self.search.set("")
            self.pick_product(only)
            return
        looks_like_code = text.replace(" ", "").isdigit() or "\x1d" in text or text.startswith("(01)")
        self.app.toast(f"No product has barcode {text}. Add it in Inventory → Scan barcode." if looks_like_code
                       else "Several products match — pick one from the list.")
        if looks_like_code:
            self.search.set("")

    def focus_search(self):
        if self.winfo_ismapped() and self.grab_current() is None:
            self.search_entry.focus_set()

    def pick_product(self, product_id, batch_no=None):
        """Double-click / Enter / scan: ask strips + tablets for loose-sale items, else add one pack.

        batch_no: batch printed in a scanned 2D code; billed from that batch when it has stock."""
        product = self.product(product_id)
        if not product:
            self.app.toast("Select a product first.")
            return
        if product.get("allowLoose") and lookups.pack_size(product) > 1:
            QuantityDialog(self, product, batch_no)
        else:
            if self.add_product(product_id, "pack", batch_no=batch_no):
                self.app.toast(f"Added {product['name']}.")
            self.after_idle(self.focus_search)

    def plan_from_batch(self, product, unit, count, batch_no):
        """Take everything from the scanned batch if it is unexpired and has enough free stock."""
        batch = next((b for b in product["batches"] if b["batch"] == batch_no), None)
        if not batch or lookups.is_expired(batch["expiry"]):
            return None
        free = batch["stock"] - self.reserved_units().get(batch["id"], 0)
        need = count * (lookups.pack_size(product) if unit == "pack" else 1)
        return [(batch, count)] if free >= need else None

    def add_product(self, product_id, unit="pack", count=1, quiet=False, batch_no=None):
        """Add `count` packs or loose tablets, spread over batches (earliest expiry first). Returns True if added."""
        product = self.product(product_id)
        if not product:
            if not quiet:
                self.app.toast("Select a product first.")
            return False
        if unit == "loose" and not product.get("allowLoose"):
            if not quiet:
                self.app.toast(f"{product['name']} is sold only as a full pack.")
            return False
        plan = (batch_no and self.plan_from_batch(product, unit, count, batch_no)) or \
            self.svc.inventory.allocate(product, self.reserved_units(), unit, count)
        if not plan:
            if not quiet:
                self.app.toast(f"Not enough unexpired stock of {product['name']}.")
            return False
        per_pack = lookups.pack_size(product)
        for batch, qty in plan:
            line = next((l for l in self.cart if l["batchId"] == batch["id"] and l["unit"] == unit), None)
            if line:
                line["qty"] += qty
            else:
                self.cart.append({"productId": product["id"], "batchId": batch["id"], "name": product["name"],
                                  "batch": batch["batch"], "price": lookups.unit_price(product, unit), "qty": qty,
                                  "stock": batch["stock"], "unit": unit, "perUnit": per_pack if unit == "pack" else 1,
                                  "label": lookups.unit_label(unit, per_pack)})
        self.redraw_cart()
        return True

    def change_line_qty(self, line, delta):
        """Per-row − / + buttons."""
        if line not in self.cart:
            return
        if delta > 0:
            free = line["stock"] - self.reserved_units(exclude=line).get(line["batchId"], 0)
            if (line["qty"] + delta) * line["perUnit"] > free:
                # This batch is used up; take the extra from the next batch if there is one.
                if not self.add_product(line["productId"], line["unit"], delta, quiet=True):
                    self.app.toast(f"No more stock of {line['name']}.")
                return
        line["qty"] += delta
        if line["qty"] <= 0:
            self.cart.remove(line)
        self.redraw_cart()

    def remove_line(self, line):
        """Per-row ✕ button."""
        if line in self.cart:
            self.cart.remove(line)
            self.redraw_cart()

    def clear_cart(self):
        self.cart.clear()
        self.redeem.set("0")
        self.redraw_cart()

    def redraw_cart(self):
        self.cart_list.show(self.cart)
        count = len(self.cart)
        self.cart_count.configure(text=f"{count} item{'s' if count != 1 else ''} in bill" if count else "Bill is empty")
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


class CartList(ttk.Frame):
    """Bill lines, each with its own − qty + and ✕ controls (a Treeview cannot hold buttons)."""

    COLUMNS = (("Item", 1, "w"), ("Qty", 0, "center"), ("Rate", 0, "e"), ("Amount", 0, "e"), ("", 0, "e"))

    def __init__(self, parent, on_change, on_remove):
        super().__init__(parent, style="Card.TFrame")
        self.on_change, self.on_remove = on_change, on_remove
        head = tk.Frame(self, background="#f1f4f6")
        head.pack(fill="x")
        self._columns(head)
        for col, (text, _w, anchor) in enumerate(self.COLUMNS):
            tk.Label(head, text=text, background="#f1f4f6", foreground=theme.MUTED, anchor=anchor,
                     font=(theme.FONT, 9, "bold"), padx=6, pady=5).grid(row=0, column=col, sticky="ew")
        body = tk.Frame(self, background=theme.CARD)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, background=theme.CARD, highlightthickness=0, height=200)
        scroll = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.rows = tk.Frame(self.canvas, background=theme.CARD)
        self._window = self.canvas.create_window(0, 0, window=self.rows, anchor="nw")
        self.rows.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        for widget in (self.canvas, self.rows):
            widget.bind("<MouseWheel>", self._wheel)
        self.row_widgets = []

    def _columns(self, frame):
        frame.columnconfigure(0, weight=1)
        for col, minsize in ((1, 104), (2, 66), (3, 76), (4, 30)):
            frame.columnconfigure(col, minsize=minsize)

    def _wheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")

    def show(self, lines):
        for child in self.rows.winfo_children():
            child.destroy()
        self.row_widgets = []
        self._columns(self.rows)
        if not lines:
            tk.Label(self.rows, text="No items yet — double-click a product on the left.", background=theme.CARD,
                     foreground=theme.MUTED, pady=18).grid(row=0, column=0, columnspan=5)
        for index, line in enumerate(lines):
            bg = theme.CARD if index % 2 == 0 else "#fafbfc"
            r = index * 2
            name = tk.Frame(self.rows, background=bg)
            name.grid(row=r, column=0, sticky="nsew")
            tk.Label(name, text=line["name"], background=bg, foreground=theme.INK, anchor="w",
                     font=(theme.FONT, 10)).pack(anchor="w", padx=(6, 0), pady=(4, 0))
            tk.Label(name, text=f"Batch {line['batch']}",
                     background=bg, foreground=theme.MUTED, anchor="w", font=(theme.FONT, 8)).pack(
                anchor="w", padx=(6, 0), pady=(0, 4))
            qty = tk.Frame(self.rows, background=bg)
            qty.grid(row=r, column=1, sticky="nsew")
            inner = tk.Frame(qty, background=bg)
            inner.place(relx=0.5, rely=0.5, anchor="center")
            minus = self._button(inner, "−", lambda l=line: self.on_change(l, -1), bg)
            minus.pack(side="left")
            label = line["label"] + ("s" if line["label"] and line["qty"] != 1 else "")
            count = tk.Label(inner, text=f"{line['qty']} {label}".strip(), background=bg, width=8,
                             font=(theme.FONT, 10, "bold"), foreground=theme.INK)
            count.pack(side="left")
            plus = self._button(inner, "+", lambda l=line: self.on_change(l, 1), bg)
            plus.pack(side="left")
            for col, text in ((2, inr(line["price"])), (3, inr(line["qty"] * line["price"]))):
                tk.Label(self.rows, text=text, background=bg, foreground=theme.INK, anchor="e", padx=6,
                         font=(theme.FONT, 10, "bold" if col == 3 else "normal")).grid(row=r, column=col, sticky="nsew")
            remove = self._button(self.rows, "✕", lambda l=line: self.on_remove(l), bg, danger=True)
            remove.grid(row=r, column=4, sticky="e", padx=(0, 4))
            tk.Frame(self.rows, background=theme.LINE, height=1).grid(row=r + 1, column=0, columnspan=5, sticky="ew")
            self.row_widgets.append({"line": line, "minus": minus, "plus": plus, "remove": remove, "count": count})
        for widget in self.rows.winfo_children():
            widget.bind("<MouseWheel>", self._wheel)
        self.canvas.yview_moveto(1.0 if lines else 0.0)

    @staticmethod
    def _button(parent, text, command, bg, danger=False):
        colour = theme.CORAL if danger else theme.GREEN
        return tk.Button(parent, text=text, command=command, width=2, relief="flat", cursor="hand2",
                         background=bg, foreground=colour, activebackground=theme.GREEN_LIGHT,
                         activeforeground=colour, font=(theme.FONT, 11, "bold"), borderwidth=0)


class QuantityDialog(tk.Toplevel):
    """Ask how many strips and/or loose tablets the customer wants."""

    def __init__(self, page, product, batch_no=None):
        super().__init__(page)
        self.withdraw()
        self.page, self.product, self.batch_no = page, product, batch_no
        # Return the cursor to the search/scan box when this closes, ready for the next scan.
        self.bind("<Destroy>", lambda e: e.widget is self and page.after_idle(page.focus_search), add="+")
        self.title(f"Add {product['name']}")
        self.transient(page.winfo_toplevel())
        self.configure(background=theme.CARD, padx=22, pady=18)
        self.resizable(False, False)
        per_pack = lookups.pack_size(product)
        self.per_pack = per_pack
        self.strip_price, self.tab_price = lookups.unit_price(product, "pack"), lookups.unit_price(product, "loose")
        units, packs = page.svc.inventory.free_units(product, page.reserved_units())
        self.free_units_, self.free_packs = units, packs
        ttk.Label(self, text=product["name"], style="CardH2.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(self, text=f"{per_pack} tablets per strip · available {lookups.format_stock(units, per_pack)}",
                  style="CardMuted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 10))
        self.strips, self.tabs = tk.StringVar(value="1" if packs else "0"), tk.StringVar(value="0" if packs else "1")
        rows = (("Strips", self.strips, max(packs, 0), f"× {inr(self.strip_price)} per strip"),
                ("Loose tablets", self.tabs, max(units, 0), f"× {inr(self.tab_price)} per tablet"))
        self.spins = []
        for r, (label, var, top, hint) in enumerate(rows, start=2):
            ttk.Label(self, text=label, style="Card.TLabel").grid(row=r, column=0, sticky="w", pady=4, padx=(0, 12))
            spin = ttk.Spinbox(self, textvariable=var, from_=0, to=top, width=8, increment=1)
            spin.grid(row=r, column=1, sticky="w", pady=4)
            ttk.Label(self, text=hint, style="CardMuted.TLabel").grid(row=r, column=2, sticky="w", padx=(10, 0))
            var.trace_add("write", lambda *_: self.update_total())
            self.spins.append(spin)
        quick = ttk.Frame(self, style="Card.TFrame")
        quick.grid(row=4, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(quick, text="Quick:", style="CardMuted.TLabel").pack(side="left", padx=(0, 6))
        presets = [("1 strip", 1, 0), ("2 strips", 2, 0), ("1 tablet", 0, 1)]
        if per_pack // 2 > 1:
            presets.append((f"{per_pack // 2} tablets", 0, per_pack // 2))
        for text, strips, tabs in presets:
            if (strips <= packs) and (tabs <= units) and (strips or tabs):
                ttk.Button(quick, text=text, command=lambda s=strips, t=tabs: self.preset(s, t)).pack(
                    side="left", padx=(0, 4))
        self.total = ttk.Label(self, text="", style="CardH2.TLabel")
        self.total.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12, 0))
        self.error = ttk.Label(self, text="", style="Bad.TLabel", wraplength=380)
        self.error.grid(row=6, column=0, columnspan=3, sticky="w")
        buttons = ttk.Frame(self, style="Card.TFrame")
        buttons.grid(row=7, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        self.add_button = ttk.Button(buttons, text="Add to bill", style="Primary.TButton", command=self.submit)
        self.add_button.pack(side="right")
        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_total()
        center_on_main(self)
        self.lift()
        first = self.spins[0] if packs else self.spins[1]
        first.focus_set()
        first.selection_range(0, "end")
        self._grab()

    def _grab(self, tries=20):
        try:
            self.grab_set()
        except tk.TclError:
            if tries and self.winfo_exists():
                self.after(50, lambda: self._grab(tries - 1))

    def preset(self, strips, tabs):
        self.strips.set(str(strips))
        self.tabs.set(str(tabs))
        self.submit()

    def counts(self):
        try:
            strips, tabs = int(self.strips.get() or 0), int(self.tabs.get() or 0)
        except ValueError:
            return None
        return (strips, tabs) if strips >= 0 and tabs >= 0 else None

    def update_total(self):
        counts = self.counts()
        if counts is None:
            self.total.configure(text="Enter whole numbers")
            return
        strips, tabs = counts
        self.total.configure(text=f"Total {inr(strips * self.strip_price + tabs * self.tab_price)}")

    def submit(self):
        counts = self.counts()
        if counts is None:
            self.error.configure(text="Enter whole numbers (0 or more).")
            return
        strips, tabs = counts
        if not strips and not tabs:
            self.error.configure(text="Enter at least one strip or tablet.")
            return
        if strips * self.per_pack + tabs > self.free_units_ or strips > self.free_packs:
            self.error.configure(text=f"Only {lookups.format_stock(self.free_units_, self.per_pack)} available.")
            return
        # Strips first (they must come whole from one batch), then loose tablets from what is left.
        snapshot = [dict(line) for line in self.page.cart]
        pid, batch_no = self.product["id"], self.batch_no
        ok = (not strips or self.page.add_product(pid, "pack", strips, quiet=True, batch_no=batch_no)) and (
            not tabs or self.page.add_product(pid, "loose", tabs, quiet=True, batch_no=batch_no))
        if not ok:
            self.page.cart[:] = snapshot
            self.page.redraw_cart()
            self.error.configure(text="Not enough stock in whole strips for that combination; "
                                      "try fewer strips or more loose tablets.")
            return
        self.destroy()


def open_customer_form(parent, on_save):
    return FormDialog(parent, "Add customer", [
        ("name", "Name *", "text", None, ""), ("phone", "Phone *", "text", None, ""),
        ("email", "Email", "text", None, ""), ("address", "Address", "text", None, ""),
        ("state", "State", "text", None, ""), ("gstin", "GSTIN", "text", None, ""),
        ("drugLicense", "Drug licence no.", "text", None, "")], on_save, "Save customer")
