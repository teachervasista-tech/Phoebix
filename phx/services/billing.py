"""Point-of-sale: pricing, checkout and invoices."""
from ..domain import rules
from .core import ServiceError


def resolve_lines(repos, requested, on=None):
    """Build priced, validated sale lines from {productId, batchId, qty} requests."""
    if not requested:
        raise ServiceError("Add at least one item to the bill.")
    lines, used = [], {}
    for entry in requested:
        qty = entry.get("qty")
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            raise ServiceError("Each line needs a whole quantity of at least 1.")
        product = repos.products.get(entry.get("productId"))
        batch = next((b for b in product["batches"] if b["id"] == entry.get("batchId")), None) if product else None
        if not batch:
            raise ServiceError("A selected product batch no longer exists.")
        if rules.is_expired(batch["expiry"], on):
            raise ServiceError(f"{product['name']} batch {batch['batch']} is expired.")
        used[batch["id"]] = used.get(batch["id"], 0) + qty
        if used[batch["id"]] > batch["stock"]:
            raise ServiceError(f"Only {batch['stock']} unit(s) of {product['name']} batch {batch['batch']} are in stock.")
        lines.append({"id": product["id"], "batchId": batch["id"], "name": product["name"], "batch": batch["batch"],
                      "expiry": batch["expiry"], "hsn": product["hsn"], "price": product["price"],
                      "gst": product["gst"], "qty": qty})
    return lines


def build_draft(repos, request, on=None):
    store_rules = repos.settings.get("rules", rules.DEFAULT_RULES)
    customer = repos.customers.get(request.get("customerId")) if request.get("customerId") else None
    if request.get("customerId") and not customer:
        raise ServiceError("Selected customer was not found.")
    lines = resolve_lines(repos, request.get("lines"), on)
    offer = rules.active_offer(repos.offers.all(), request.get("offerId"), on) if request.get("offerId") else None
    if request.get("offerId") and not offer:
        raise ServiceError("The selected offer is not active.")
    manual = request.get("manual")
    if manual and (manual[0] not in ("percent", "fixed") or manual[1] < 0 or (manual[0] == "percent" and manual[1] > 100)):
        raise ServiceError("Enter a valid discount.")
    redeem_wanted = int(request.get("redeem") or 0)
    if customer and redeem_wanted > customer["points"]:
        raise ServiceError("The customer does not have that many points.")
    totals = rules.cart_totals(lines, store_rules, customer, offer, manual, redeem_wanted)
    if totals["total"] <= 0:
        raise ServiceError("The bill total must be greater than zero.")
    return {"lines": lines, "totals": totals, "customer": customer, "rules": store_rules,
            "earned": rules.points_earned(totals, store_rules, customer), "redeemed": totals["redeem"]}


def record_sale(repos, draft, payment, status, sold_by, extra=None, on=None):
    """Persist a sale and apply its stock and loyalty effects. Runs inside a write unit of work."""
    for line in draft["lines"]:
        if not repos.products.decrement_batch(line["batchId"], line["qty"]):
            raise ServiceError(f"Stock for {line['name']} changed; please review the bill.")
    customer = repos.customers.get(draft["customer"]["id"]) if draft["customer"] else None
    if customer:
        if customer["points"] < draft["redeemed"]:
            raise ServiceError("The customer's points changed; please review the bill.")
        spent = customer["spent"] + draft["totals"]["total"]
        repos.customers.update_loyalty(customer["id"], customer["points"] - draft["redeemed"] + draft["earned"],
                                       spent, customer["visits"] + 1, rules.tier_for(spent))
    store = repos.settings.get("store", rules.DEFAULT_STORE)
    seq = repos.sales.max_seq() + 1
    sale = {"id": f"{store['invoicePrefix']}-{seq}", "seq": seq,
            "customerId": customer["id"] if customer else None,
            "customerName": customer["name"] if customer else "Walk-in customer",
            "date": on or rules.today(), "total": draft["totals"]["total"],
            "items": sum(l["qty"] for l in draft["lines"]), "payment": payment, "status": status,
            "earned": draft["earned"], "redeemed": draft["redeemed"], "soldBy": sold_by,
            "lines": draft["lines"], "totals": draft["totals"], **(extra or {})}
    repos.sales.add(sale)
    return repos.sales.get(sale["id"])


class BillingService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def quote(self, request):
        """Totals for the cart as it stands; tolerant of an empty cart."""
        with self.db.unit_of_work() as repos:
            store_rules = repos.settings.get("rules", rules.DEFAULT_RULES)
            customer = repos.customers.get(request.get("customerId")) if request.get("customerId") else None
            lines = []
            for entry in request.get("lines") or []:
                product = repos.products.get(entry["productId"])
                if product:
                    lines.append({"qty": entry["qty"], "price": product["price"], "gst": product["gst"]})
            offer = rules.active_offer(repos.offers.all(), request.get("offerId")) if request.get("offerId") else None
            return rules.cart_totals(lines, store_rules, customer, offer, request.get("manual"), request.get("redeem") or 0)

    def checkout(self, request, payment):
        user_stamp = self.session.sold_by()
        if payment not in ("Cash", "Credit"):
            raise ServiceError("Card and UPI payments are completed through PhonePe.")
        with self.db.unit_of_work(write=True) as repos:
            draft = build_draft(repos, request)
            if payment == "Credit" and not draft["customer"]:
                raise ServiceError("Select a customer for a credit sale.")
            return record_sale(repos, draft, payment, "Credit" if payment == "Credit" else "Paid", user_stamp)

    def sales(self):
        with self.db.unit_of_work() as repos:
            return repos.sales.all()

    def invoice(self, sale_id):
        with self.db.unit_of_work() as repos:
            sale = repos.sales.get(sale_id)
            if not sale:
                raise ServiceError("Invoice not found.")
            store = repos.settings.get("store", rules.DEFAULT_STORE)
            bank = repos.settings.get("bank", rules.DEFAULT_BANK)
            customer = repos.customers.get(sale["customerId"]) if sale["customerId"] else None
        if not sale["lines"] or not sale["totals"]:
            raise ServiceError("This is a sample transaction without line items, so it cannot be reprinted.")
        intra = rules.is_intra_state(store, customer)
        return {"sale": sale, "store": store, "bank": bank, "customer": customer, "intra": intra,
                "title": "TAX INVOICE" if store["gstin"] else "DEMO BILL · GSTIN NOT SET",
                "lines": rules.invoice_lines(sale["lines"], sale["totals"], intra),
                "hasBank": bool(bank["accountNumber"] or bank["upiId"])}
