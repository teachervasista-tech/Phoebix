"""Online (UPI / card) payments: start a PhonePe order, then confirm it before recording the sale."""
import uuid
from datetime import datetime, timezone

from ..domain import rules
from .billing import build_draft, record_sale
from .core import PaymentGatewayError, ServiceError


def _now():
    return datetime.now(timezone.utc).isoformat()


class PaymentService:
    def __init__(self, db, session, gateway):
        self.db, self.session, self.gateway = db, session, gateway

    def is_configured(self):
        return self.gateway.is_configured()

    def start(self, request, method):
        sold_by = self.session.sold_by()
        if method not in rules.ONLINE_METHODS:
            raise ServiceError("Choose UPI or Card for online payment.")
        if not self.gateway.is_configured():
            raise PaymentGatewayError("PhonePe is not configured. Set PHONEPE_CLIENT_ID, PHONEPE_CLIENT_SECRET and "
                                      "PHONEPE_CLIENT_VERSION in the .env file, then restart Phoebix.")
        with self.db.unit_of_work() as repos:
            draft = build_draft(repos, request)
        order_id = "PHX" + uuid.uuid4().hex[:24].upper()
        amount = round(draft["totals"]["total"] * 100)
        if amount < 100:
            raise ServiceError("Online payments must be at least ₹1.")
        url, provider_id = self.gateway.create_order(order_id, amount, order_id)
        intent = {"request": request, "method": method, "soldBy": sold_by, "total": draft["totals"]["total"]}
        with self.db.unit_of_work(write=True) as repos:
            repos.payments.add(order_id, amount, intent, provider_id, _now())
        return {"merchantOrderId": order_id, "redirectUrl": url, "status": "PENDING"}

    def check(self, order_id):
        """Ask PhonePe for the order state; record the sale exactly once when it is COMPLETED."""
        with self.db.unit_of_work() as repos:
            payment = repos.payments.get(order_id)
        if not payment:
            raise ServiceError("Payment order not found.")
        if payment["status"] == "COMPLETED":
            with self.db.unit_of_work() as repos:
                return {"status": "COMPLETED", "sale": repos.sales.get(payment["saleId"])}
        if payment["status"] == "RECONCILIATION_REQUIRED":
            return {"status": payment["status"], "message": "This payment needs manual reconciliation."}
        result = self.gateway.order_status(order_id)
        if result["state"] != "COMPLETED":
            with self.db.unit_of_work(write=True) as repos:
                repos.payments.set_status(order_id, result["state"], _now())
            return {"status": result["state"]}
        if result["amount"] != payment["amount"]:
            raise PaymentGatewayError("PhonePe reports a completed payment whose amount does not match the invoice. "
                                      "Do not issue goods; reconcile it in the PhonePe dashboard.")
        intent = payment["intent"]
        method = "UPI" if str(result["mode"] or "").startswith("UPI") else "Card" if "CARD" in str(result["mode"] or "") else intent["method"]
        try:
            with self.db.unit_of_work(write=True) as repos:
                draft = build_draft(repos, intent["request"])
                if round(draft["totals"]["total"] * 100) != payment["amount"]:
                    raise ServiceError("The bill total changed during payment.")
                sale = record_sale(repos, draft, method, "Paid", intent["soldBy"],
                                   {"gateway": "PhonePe", "phonepeOrderId": order_id,
                                    "phonepeTransactionId": result["transactionId"]})
                repos.payments.set_status(order_id, "COMPLETED", _now(), sale["id"])
        except ServiceError as error:
            with self.db.unit_of_work(write=True) as repos:
                repos.payments.set_status(order_id, "RECONCILIATION_REQUIRED", _now())
            return {"status": "RECONCILIATION_REQUIRED",
                    "message": f"Payment completed, but the sale could not be recorded: {error} Reconcile this order before dispensing."}
        return {"status": "COMPLETED", "sale": sale}
