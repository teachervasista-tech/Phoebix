"""Inventory, customers, store settings and the loyalty programme."""
import uuid
from datetime import date

from ..domain import rules
from .core import ServiceError


def _wrap(call):
    try:
        return call()
    except ValueError as error:
        raise ServiceError(str(error)) from error


class SettingsService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def store(self):
        with self.db.unit_of_work() as repos:
            return repos.settings.get("store", rules.DEFAULT_STORE)

    def bank(self):
        with self.db.unit_of_work() as repos:
            return repos.settings.get("bank", rules.DEFAULT_BANK)

    def rules(self):
        with self.db.unit_of_work() as repos:
            return repos.settings.get("rules", rules.DEFAULT_RULES)

    def save_store(self, data):
        self.session.require_user()
        store = _wrap(lambda: rules.validate_store(data))
        with self.db.unit_of_work(write=True) as repos:
            repos.settings.put("store", store)
        return store

    def save_bank(self, data):
        self.session.require_admin()
        bank = _wrap(lambda: rules.validate_bank(data))
        with self.db.unit_of_work(write=True) as repos:
            repos.settings.put("bank", bank)
        return bank


class InventoryService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def products(self):
        with self.db.unit_of_work() as repos:
            return repos.products.all()

    def add_product(self, data):
        self.session.require_user()
        clean = _wrap(lambda: rules.validate_product(data))
        with self.db.unit_of_work(write=True) as repos:
            product_id = repos.products.new_id()
            repos.products.add({**clean, "id": product_id})
            if clean["stock"]:
                repos.products.add_batch(f"{product_id}-batch-1", product_id, clean["batch"], clean["expiry"], clean["stock"])
            return repos.products.get(product_id)

    def receive_stock(self, product_id, batch, expiry, quantity):
        self.session.require_user()
        with self.db.unit_of_work(write=True) as repos:
            product = repos.products.get(product_id)
            if not product:
                raise ServiceError("Product not found.")
            batch, quantity = _wrap(lambda: rules.validate_receive(batch, expiry, quantity, product["batches"]))
            match = next((b for b in product["batches"] if b["batch"] == batch and b["expiry"] == expiry), None)
            if match:
                repos.products.set_batch_stock(match["id"], match["stock"] + quantity)
            else:
                repos.products.add_batch(repos.products.next_batch_id(product_id), product_id, batch, expiry, quantity)
            return repos.products.get(product_id)

    @staticmethod
    def pick_batch(product, reserved):
        """Earliest-expiry unexpired batch with stock left after what the cart already holds."""
        return rules.available_batch(product, reserved)

    @staticmethod
    def alerts(products):
        return [p for p in products if p["stock"] <= p["reorder"] or any(
            b["stock"] > 0 and rules.is_near_expiry(b["expiry"]) for b in p["batches"])]


class CustomerService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def list(self):
        with self.db.unit_of_work() as repos:
            return repos.customers.all()

    def add(self, data):
        self.session.require_user()
        with self.db.unit_of_work(write=True) as repos:
            clean = _wrap(lambda: rules.validate_customer(data, repos.customers.phones()))
            customer = {**clean, "id": repos.customers.new_id(), "points": 0, "tier": "Member",
                        "spent": 0, "visits": 0, "joined": rules.today()}
            repos.customers.add(customer)
            return repos.customers.get(customer["id"])

    def adjust_points(self, customer_id, delta):
        self.session.require_admin()
        with self.db.unit_of_work(write=True) as repos:
            customer = repos.customers.get(customer_id)
            if not customer:
                raise ServiceError("Customer not found.")
            if customer["points"] + delta < 0:
                raise ServiceError("Points cannot go below zero.")
            repos.customers.update_loyalty(customer_id, customer["points"] + delta, customer["spent"],
                                           customer["visits"], customer["tier"])
            return repos.customers.get(customer_id)


class LoyaltyService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def rules(self):
        with self.db.unit_of_work() as repos:
            return repos.settings.get("rules", rules.DEFAULT_RULES)

    def save_rules(self, data):
        self.session.require_admin()
        clean = _wrap(lambda: rules.validate_rules(data))
        with self.db.unit_of_work(write=True) as repos:
            current = repos.settings.get("rules", rules.DEFAULT_RULES)
            repos.settings.put("rules", {**current, **clean})
            return repos.settings.get("rules", rules.DEFAULT_RULES)

    def toggle_rule(self, key):
        self.session.require_admin()
        if key not in ("birthday", "wellness", "refill"):
            raise ServiceError("Unknown reward rule.")
        with self.db.unit_of_work(write=True) as repos:
            current = repos.settings.get("rules", rules.DEFAULT_RULES)
            current[key] = not current[key]
            repos.settings.put("rules", current)
            return current

    def offers(self):
        with self.db.unit_of_work() as repos:
            return repos.offers.all()

    def usable_offers(self):
        return [o for o in self.offers() if o["enabled"] and o["end"] >= rules.today()]

    def add_offer(self, name, discount, kind, end):
        self.session.require_admin()
        name, discount, kind, end = _wrap(lambda: rules.validate_offer(name, discount, kind, end))
        with self.db.unit_of_work(write=True) as repos:
            repos.offers.add(f"o{uuid.uuid4().hex[:8]}", name, discount, kind, end)

    def toggle_offer(self, offer_id):
        self.session.require_admin()
        with self.db.unit_of_work(write=True) as repos:
            offer = repos.offers.get(offer_id)
            if not offer:
                raise ServiceError("Offer not found.")
            repos.offers.set_enabled(offer_id, not offer["enabled"])

    def delete_offer(self, offer_id):
        self.session.require_admin()
        with self.db.unit_of_work(write=True) as repos:
            repos.offers.delete(offer_id)

    def stats(self):
        with self.db.unit_of_work() as repos:
            sales, customers = repos.sales.all(), repos.customers.all()
        month = date.today().isoformat()[:7]
        this_month = [s for s in sales if s["date"].startswith(month)]
        members = sum(1 for c in customers if c["visits"] > 0)
        return {"earned": sum(s["earned"] for s in this_month),
                "redeemed": sum(s["redeemed"] for s in this_month),
                "memberVisitPercent": round(100 * len({s["customerId"] for s in sales if s["customerId"]})
                                            / len(customers)) if customers else 0,
                "members": members, "customers": len(customers)}
