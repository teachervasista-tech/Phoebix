"""Inventory, customers, store settings and the loyalty programme."""
import uuid
from datetime import date

from ..data.database import DataError
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
        self.session.require_admin()
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

    @staticmethod
    def _check_barcode_free(repos, barcode, product_id=None):
        if barcode:
            owner = repos.products.by_barcode(barcode)
            if owner and owner["id"] != product_id:
                raise ServiceError(f"Barcode {barcode} already belongs to {owner['name']}.")

    def add_product(self, data):
        self.session.require_user()
        clean = _wrap(lambda: rules.validate_product(data))
        with self.db.unit_of_work(write=True) as repos:
            self._check_barcode_free(repos, clean["barcode"])
            product_id = repos.products.new_id()
            repos.products.add({**clean, "id": product_id})
            if clean["stock"]:
                repos.products.add_batch(f"{product_id}-batch-1", product_id, clean["batch"], clean["expiry"], clean["stock"])
            return repos.products.get(product_id)

    def update_product(self, product_id, data):
        """Edit a product's details, prices, barcode and pack size (admin)."""
        self.session.require_admin()
        clean = _wrap(lambda: rules.validate_product({**data, "stock": 0}))
        with self.db.unit_of_work(write=True) as repos:
            if not repos.products.get(product_id):
                raise ServiceError("Product not found.")
            self._check_barcode_free(repos, clean["barcode"], product_id)
            repos.products.update_details(product_id, clean)
            try:
                repos.products.set_pack(product_id, clean["unitsPerPack"], clean["allowLoose"])
            except DataError as error:
                raise ServiceError(str(error)) from error
            return repos.products.get(product_id)

    def receive_stock(self, product_id, batch, expiry, quantity, loose=0, price=None, mrp=None):
        """quantity is in packs (strips); loose is extra single units (tablets).

        price/mrp (per pack), when given and different, update the product's prices (admin only)."""
        user = self.session.require_user()
        with self.db.unit_of_work(write=True) as repos:
            product = repos.products.get(product_id)
            if not product:
                raise ServiceError("Product not found.")
            batch, quantity = _wrap(lambda: rules.validate_receive(
                batch, expiry, quantity, product["batches"], rules.pack_size(product), loose))
            if price not in (None, "") or mrp not in (None, ""):
                new_price, new_mrp = _wrap(lambda: rules.validate_prices(
                    price if price not in (None, "") else product["price"],
                    mrp if mrp not in (None, "") else product["mrp"]))
                if (new_price, new_mrp) != (product["price"], product["mrp"]):
                    if user["role"] != "admin":
                        raise ServiceError("Only an administrator can change prices. Leave price and MRP as they are.")
                    repos.products.set_prices(product_id, new_price, new_mrp)
            match = next((b for b in product["batches"] if b["batch"] == batch and b["expiry"] == expiry), None)
            if match:
                repos.products.set_batch_stock(match["id"], match["stock"] + quantity)
            else:
                repos.products.add_batch(repos.products.next_batch_id(product_id), product_id, batch, expiry, quantity)
            return repos.products.get(product_id)

    def lookup_scan(self, raw):
        """Decode a scan and find its product: {"code", "batch", "expiry", "product" (or None)}."""
        self.session.require_user()
        scan = _wrap(lambda: rules.parse_scan(raw))
        if not scan["code"]:
            raise ServiceError("Nothing was scanned.")
        with self.db.unit_of_work() as repos:
            scan["product"] = repos.products.by_barcode(scan["code"])
        return scan

    def link_barcode(self, product_id, barcode):
        """Attach a scanned barcode to an existing product that has none (or replace it)."""
        self.session.require_user()
        code = _wrap(lambda: rules.normalize_barcode(barcode))
        if not code:
            raise ServiceError("Scan or type a barcode.")
        with self.db.unit_of_work(write=True) as repos:
            product = repos.products.get(product_id)
            if not product:
                raise ServiceError("Product not found.")
            if product["barcode"] and product["barcode"] != code and not self.session.is_admin:
                raise ServiceError(f"{product['name']} already has barcode {product['barcode']}; "
                                   "only an administrator can replace it.")
            self._check_barcode_free(repos, code, product_id)
            repos.products.set_barcode(product_id, code)
            return repos.products.get(product_id)

    def set_pack(self, product_id, units_per_pack, allow_loose):
        """Set how many units (tablets) a pack (strip) holds and whether loose sale is allowed."""
        self.session.require_admin()
        units_per_pack = _wrap(lambda: rules.parse_units_per_pack(units_per_pack))
        allow_loose = rules.truthy(allow_loose) and units_per_pack > 1
        with self.db.unit_of_work(write=True) as repos:
            try:
                repos.products.set_pack(product_id, units_per_pack, allow_loose)
            except DataError as error:
                raise ServiceError(str(error)) from error
            return repos.products.get(product_id)

    @staticmethod
    def pick_batch(product, reserved, unit="pack"):
        """Earliest-expiry unexpired batch that can supply one more `unit` beyond what the cart holds."""
        return rules.available_batch(product, reserved, need=rules.base_qty(product, unit, 1))

    @staticmethod
    def allocate(product, reserved, unit, count):
        """[(batch, qty)] covering `count` packs or loose units, earliest expiry first; None if short."""
        return rules.allocate(product, reserved, unit, count)

    @staticmethod
    def free_units(product, reserved):
        """(sellable base units, whole packs obtainable) after what the cart already holds."""
        return rules.free_units(product, reserved)

    @staticmethod
    def alerts(products):
        return [p for p in products if rules.is_low_stock(p) or any(
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
