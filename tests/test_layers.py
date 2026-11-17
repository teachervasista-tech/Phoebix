import ast
import json
import os
import tempfile
import unittest
from pathlib import Path

from phx.services.container import Services
from phx.services.core import AuthError, ServiceError

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_state.json"


class FakeGateway:
    def __init__(self, state="COMPLETED", amount=None, mode="UPI_QR"):
        self.state, self.amount, self.mode, self.created = state, amount, mode, []

    def is_configured(self):
        return True

    def create_order(self, order_id, amount, reference):
        self.created.append((order_id, amount))
        return "https://pay.example/checkout", "OMO1"

    def order_status(self, order_id):
        amount = self.amount if self.amount is not None else self.created[-1][1]
        return {"state": self.state, "amount": amount, "transactionId": "TX1", "mode": self.mode}


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gateway = FakeGateway()
        self.svc = Services(Path(self.tmp.name) / "t.sqlite3", SAMPLE, self.gateway)
        self.addCleanup(self.tmp.cleanup)

    def admin(self):
        self.svc.auth.login("admin", "admin123")

    def staff(self):
        self.svc.auth.login("cashier", "cashier123")

    def request(self, **extra):
        product = self.svc.inventory.products()[0]
        batch = next(b for b in product["batches"] if b["stock"] > 5)
        return {"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 2}], **extra}, product, batch


class AuthTests(ServiceTestCase):
    def test_login_and_lockout(self):
        with self.assertRaises(AuthError):
            self.svc.auth.login("admin", "wrong")
        user = self.svc.auth.login("admin", "admin123")
        self.assertTrue(user["mustChangePassword"])
        self.assertNotIn("passwordHash", user)
        self.svc.auth.logout()
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.svc.auth.login("cashier", "nope")
        with self.assertRaises(AuthError) as ctx:
            self.svc.auth.login("cashier", "cashier123")
        self.assertIn("Too many", str(ctx.exception))

    def test_change_password_clears_forced_flag(self):
        self.admin()
        user = self.svc.auth.change_password("admin123", "a-much-better-pass")
        self.assertFalse(user["mustChangePassword"])
        self.svc.auth.logout()
        self.svc.auth.login("admin", "a-much-better-pass")

    def test_staff_cannot_manage_users_or_bank(self):
        self.staff()
        with self.assertRaises(AuthError):
            self.svc.users.list()
        with self.assertRaises(AuthError):
            self.svc.settings.save_bank({"accountHolder": "X"})
        with self.assertRaises(AuthError):
            self.svc.settings.save_store({"name": "X", "invoicePrefix": "INV"})
        with self.assertRaises(AuthError):
            self.svc.backup.save_settings({"keep": 5})

    def test_admin_cannot_demote_self(self):
        self.admin()
        me = self.svc.session.user
        with self.assertRaises(ServiceError):
            self.svc.users.update(me["id"], me["name"], "staff", True)

    def test_unauthenticated_calls_rejected(self):
        with self.assertRaises(AuthError):
            self.svc.customers.add({"name": "A", "phone": "9876543210"})


class BillingTests(ServiceTestCase):
    def test_sale_reduces_stock_and_stamps_cashier(self):
        self.staff()
        request, product, batch = self.request()
        sale = self.svc.billing.checkout(request, "Cash")
        self.assertEqual(sale["soldBy"]["username"], "cashier")
        self.assertEqual(sale["id"], "INV-1049")
        after = next(p for p in self.svc.inventory.products() if p["id"] == product["id"])
        # Stock is held in base units (tablets); two strips consume 2 * units-per-strip.
        self.assertEqual(next(b for b in after["batches"] if b["id"] == batch["id"])["stock"],
                         batch["stock"] - 2 * product["unitsPerPack"])

    def test_loyalty_earn_redeem_and_totals(self):
        self.admin()
        customer = self.svc.customers.list()[0]
        request, _, _ = self.request(customerId=customer["id"], redeem=5)
        totals = self.svc.billing.quote(request)
        self.assertEqual(totals["redeem"], 5)
        sale = self.svc.billing.checkout(request, "Cash")
        after = next(c for c in self.svc.customers.list() if c["id"] == customer["id"])
        self.assertEqual(after["points"], customer["points"] - 5 + sale["earned"])
        self.assertEqual(after["visits"], customer["visits"] + 1)

    def test_insufficient_stock_rejected_without_side_effects(self):
        self.admin()
        request, product, batch = self.request()
        request["lines"][0]["qty"] = batch["stock"] + 1
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "Cash")
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_credit_needs_customer_and_card_needs_gateway(self):
        self.admin()
        request, _, _ = self.request()
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "Credit")
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout(request, "UPI")

    def test_invoice_has_gst_split_and_bank(self):
        self.admin()
        self.svc.settings.save_bank({"accountHolder": "Phoebix", "bankName": "HDFC", "accountNumber": "123456789012",
                                     "ifsc": "HDFC0001234", "accountType": "Current"})
        request, _, _ = self.request()
        sale = self.svc.billing.checkout(request, "Cash")
        invoice = self.svc.billing.invoice(sale["id"])
        self.assertTrue(invoice["intra"])
        self.assertTrue(invoice["hasBank"])
        self.assertAlmostEqual(sum(l["cgst"] + l["sgst"] for l in invoice["lines"]), sale["totals"]["tax"], places=1)


class PaymentTests(ServiceTestCase):
    def test_completed_payment_records_sale_once(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.assertTrue(started["redirectUrl"].startswith("https://"))
        first = self.svc.payments.check(started["merchantOrderId"])
        second = self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first["sale"]["id"], second["sale"]["id"])
        self.assertEqual(first["sale"]["soldBy"]["username"], "cashier")
        self.assertEqual(len(self.svc.billing.sales()), 7)

    def test_pending_does_not_record(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "Card")
        self.gateway.state = "PENDING"
        self.assertEqual(self.svc.payments.check(started["merchantOrderId"])["status"], "PENDING")
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_amount_mismatch_never_records(self):
        self.staff()
        request, _, _ = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.gateway.amount = 100
        with self.assertRaises(ServiceError):
            self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(len(self.svc.billing.sales()), 6)

    def test_stock_change_during_payment_needs_reconciliation(self):
        self.staff()
        request, product, batch = self.request()
        started = self.svc.payments.start(request, "UPI")
        self.svc.billing.checkout({"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": batch["stock"],
                                              "unit": "loose"}]}, "Cash")
        result = self.svc.payments.check(started["merchantOrderId"])
        self.assertEqual(result["status"], "RECONCILIATION_REQUIRED")


class CatalogTests(ServiceTestCase):
    def test_add_customer_validates_and_persists(self):
        self.staff()
        customer = self.svc.customers.add({"name": "Ravi Kumar", "phone": "98765 43210", "state": "Telangana"})
        self.assertEqual(customer["initials"], "RK")
        with self.assertRaises(ServiceError):
            self.svc.customers.add({"name": "Dup", "phone": "9876543210"})
        with self.assertRaises(ServiceError):
            self.svc.customers.add({"name": "Bad", "phone": "123"})
        self.assertIn("Ravi Kumar", [c["name"] for c in self.svc.customers.list()])

    def test_inventory_add_and_receive(self):
        self.staff()
        product = self.svc.inventory.add_product({"name": "Test Syrup", "price": 50, "mrp": 60, "gst": 12,
                                                  "stock": 10, "batch": "B1", "expiry": "2099-01-01"})
        updated = self.svc.inventory.receive_stock(product["id"], "B2", "2098-01-01", 5)
        self.assertEqual(updated["stock"], 15)
        self.assertEqual(updated["batches"][0]["batch"], "B2")
        with self.assertRaises(ServiceError):
            self.svc.inventory.receive_stock(product["id"], "B1", "2099-06-01", 1)
        with self.assertRaises(ServiceError):
            self.svc.inventory.add_product({"name": "Bad", "price": 70, "mrp": 60, "gst": 5})

    def test_bank_details_validation(self):
        self.admin()
        with self.assertRaises(ServiceError):
            self.svc.settings.save_bank({"accountHolder": "A", "bankName": "B", "accountNumber": "12", "ifsc": "HDFC0001234"})
        bank = self.svc.settings.save_bank({"accountHolder": "A", "bankName": "B", "accountNumber": "123456789",
                                            "ifsc": "hdfc0001234", "upiId": "shop@okhdfc"})
        self.assertEqual(bank["ifsc"], "HDFC0001234")

    def test_offer_applies_discount(self):
        self.admin()
        self.svc.loyalty.add_offer("Ten off", 10, "percent", "2099-01-01")
        offer = self.svc.loyalty.usable_offers()[0]
        request, _, _ = self.request(offerId=offer["id"])
        totals = self.svc.billing.quote(request)
        self.assertAlmostEqual(totals["discount"], totals["subtotal"] * 0.1, places=2)

    def test_reports_and_exports(self):
        self.admin()
        path = Path(self.tmp.name) / "sales.csv"
        self.svc.reports.export_sales(path)
        self.assertIn("INV-1048", path.read_text(encoding="utf-8-sig"))
        self.assertEqual(self.svc.reports.reports()["invoices"], 6)
        self.assertIn("week", self.svc.reports.dashboard())


class LooseSaleTests(ServiceTestCase):
    def tablet_product(self, strips=2, per_strip=10, allow_loose=True):
        return self.svc.inventory.add_product({"name": "Test Tabs", "price": 30, "mrp": 35, "gst": 12,
                                               "unitsPerPack": per_strip, "allowLoose": allow_loose,
                                               "stock": strips, "batch": "T1", "expiry": "2099-01-01"})

    def test_rules_helpers(self):
        from phx.domain import rules
        product = {"price": 30.0, "unitsPerPack": 10}
        self.assertEqual(rules.unit_price(product, "loose"), 3.0)
        self.assertEqual(rules.unit_price(product, "pack"), 30.0)
        self.assertEqual(rules.base_qty(product, "pack", 2), 20)
        self.assertEqual(rules.base_qty(product, "loose", 3), 3)
        self.assertEqual(rules.format_stock(43, 10), "4 strips + 3 tabs")
        self.assertEqual(rules.format_stock(10, 10), "1 strip")
        self.assertEqual(rules.format_stock(1, 10), "1 tab")
        self.assertEqual(rules.format_stock(0, 10), "0 strips")
        self.assertEqual(rules.format_stock(7, 1), "7")

    def test_allocate_spreads_over_batches_earliest_first(self):
        from phx.domain import rules
        product = {"unitsPerPack": 10, "batches": [
            {"id": "b2", "batch": "B2", "expiry": "2099-06-01", "stock": 30},
            {"id": "b1", "batch": "B1", "expiry": "2099-01-01", "stock": 15},
            {"id": "b0", "batch": "B0", "expiry": "2000-01-01", "stock": 100}]}  # expired
        plan = rules.allocate(product, {}, "pack", 3)
        self.assertEqual([(b["id"], n) for b, n in plan], [("b1", 1), ("b2", 2)])
        plan = rules.allocate(product, {"b1": 10}, "loose", 8)
        self.assertEqual([(b["id"], n) for b, n in plan], [("b1", 5), ("b2", 3)])
        self.assertIsNone(rules.allocate(product, {}, "pack", 5))
        self.assertEqual(rules.free_units(product, {"b2": 10}), (35, 3))

    def test_sell_strip_and_loose_tablets(self):
        self.staff()
        product = self.tablet_product()
        self.assertEqual(product["stock"], 20)
        batch = product["batches"][0]
        request = {"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 1, "unit": "pack"},
                             {"productId": product["id"], "batchId": batch["id"], "qty": 3, "unit": "loose"}]}
        quote = self.svc.billing.quote(request)
        self.assertAlmostEqual(quote["subtotal"], 30 + 3 * 3.0)
        self.assertAlmostEqual(quote["total"], (30 + 9) * 1.12, places=2)
        sale = self.svc.billing.checkout(request, "Cash")
        self.assertAlmostEqual(sale["total"], quote["total"])
        after = next(p for p in self.svc.inventory.products() if p["id"] == product["id"])
        self.assertEqual(after["stock"], 7)
        invoice = self.svc.billing.invoice(sale["id"])
        self.assertEqual([l["unitLabel"] for l in invoice["lines"]], ["strip", "tab"])
        self.assertEqual(invoice["lines"][1]["price"], 3.0)

    def test_loose_rejected_when_not_allowed(self):
        self.staff()
        product = self.tablet_product(allow_loose=False)
        batch = product["batches"][0]
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout({"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 1,
                                                  "unit": "loose"}]}, "Cash")

    def test_cannot_oversell_tablets_across_lines(self):
        self.staff()
        product = self.tablet_product(strips=1)
        batch = product["batches"][0]
        with self.assertRaises(ServiceError):
            self.svc.billing.checkout({"lines": [
                {"productId": product["id"], "batchId": batch["id"], "qty": 1, "unit": "pack"},
                {"productId": product["id"], "batchId": batch["id"], "qty": 1, "unit": "loose"}]}, "Cash")

    def test_request_without_unit_is_a_pack(self):
        """Pending PhonePe intents saved before this change replay as whole packs."""
        self.staff()
        product = self.tablet_product()
        batch = product["batches"][0]
        sale = self.svc.billing.checkout({"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 1}]},
                                         "Cash")
        self.assertEqual(sale["lines"][0]["unit"], "pack")
        self.assertEqual(sale["lines"][0]["price"], 30)

    def test_receive_strips_plus_loose_and_low_stock(self):
        self.staff()
        product = self.tablet_product(strips=0)
        updated = self.svc.inventory.receive_stock(product["id"], "R1", "2099-01-01", 2, 5)
        self.assertEqual(updated["stock"], 25)
        from phx.domain import rules
        self.assertFalse(rules.is_low_stock({**updated, "reorder": 2}))
        self.assertTrue(rules.is_low_stock({**updated, "reorder": 3}))

    def test_set_pack_rescales_whole_packs_only(self):
        self.admin()
        product = self.svc.inventory.add_product({"name": "Old Tabs", "price": 20, "mrp": 25, "gst": 5,
                                                  "stock": 4, "batch": "O1", "expiry": "2099-01-01"})
        self.assertEqual(product["stock"], 4)
        updated = self.svc.inventory.set_pack(product["id"], "15", "Yes")
        self.assertEqual(updated["stock"], 60)
        self.assertTrue(updated["allowLoose"])
        batch = updated["batches"][0]
        self.svc.billing.checkout({"lines": [{"productId": product["id"], "batchId": batch["id"], "qty": 1,
                                              "unit": "loose"}]}, "Cash")
        with self.assertRaises(ServiceError):
            self.svc.inventory.set_pack(product["id"], 10, True)

    def test_sample_tablets_get_pack_size(self):
        products = {p["name"]: p for p in self.svc.inventory.products()}
        self.assertEqual(products["Paracetamol 650 mg"]["unitsPerPack"], 15)
        self.assertTrue(products["Paracetamol 650 mg"]["allowLoose"])
        self.assertEqual(products["Cough Relief Syrup"]["unitsPerPack"], 1)
        self.assertFalse(products["Cough Relief Syrup"]["allowLoose"])


class BarcodeTests(ServiceTestCase):
    def test_parse_scan_formats(self):
        from phx.domain import rules
        self.assertEqual(rules.parse_scan("8901234567894")["code"], "08901234567894")  # EAN-13
        self.assertEqual(rules.parse_scan("036000291452")["code"], "00036000291452")  # UPC-A
        self.assertEqual(rules.parse_scan("ABC-123x")["code"], "ABC-123X")  # internal Code-128
        gs1 = rules.parse_scan("]d20108901234567894172512001012AB\x1d21SER99")
        self.assertEqual((gs1["code"], gs1["expiry"], gs1["batch"]), ("08901234567894", "2025-12-31", "12AB"))
        printed = rules.parse_scan("(01)08901234567894(17)270615(10)B-77")
        self.assertEqual((printed["code"], printed["expiry"], printed["batch"]), ("08901234567894", "2027-06-15", "B-77"))
        no_gs = rules.parse_scan("010890123456789417270615")
        self.assertEqual((no_gs["code"], no_gs["expiry"], no_gs["batch"]), ("08901234567894", "2027-06-15", ""))
        self.assertEqual(rules.parse_scan("  ")["code"], "")

    def test_barcode_lookup_unique_and_link(self):
        self.staff()
        product = self.svc.inventory.add_product({"name": "Coded", "price": 10, "mrp": 12, "gst": 5,
                                                  "barcode": "8901234567894"})
        found = self.svc.inventory.lookup_scan("(01)08901234567894(10)X1")
        self.assertEqual(found["product"]["id"], product["id"])
        self.assertEqual(found["batch"], "X1")
        self.assertIsNone(self.svc.inventory.lookup_scan("4006381333931")["product"])
        with self.assertRaises(ServiceError):
            self.svc.inventory.add_product({"name": "Dup", "price": 10, "mrp": 12, "gst": 5,
                                            "barcode": "08901234567894"})
        other = self.svc.inventory.products()[0]
        linked = self.svc.inventory.link_barcode(other["id"], "4006381333931")
        self.assertEqual(linked["barcode"], "04006381333931")
        with self.assertRaises(ServiceError):
            self.svc.inventory.link_barcode(other["id"], "8901234567894")  # belongs to "Coded"
        with self.assertRaises(ServiceError):
            self.svc.inventory.link_barcode(other["id"], "5012345678900")  # staff cannot replace a barcode

    def test_receive_with_price_change(self):
        self.staff()
        product = self.svc.inventory.products()[0]
        with self.assertRaises(ServiceError):
            self.svc.inventory.receive_stock(product["id"], "N1", "2099-01-01", 1, 0, product["price"] + 1, product["mrp"] + 1)
        same = self.svc.inventory.receive_stock(product["id"], "N1", "2099-01-01", 1, 0,
                                                f"{product['price']:g}", f"{product['mrp']:g}")
        self.assertEqual(same["price"], product["price"])
        self.svc.auth.logout()
        self.admin()
        updated = self.svc.inventory.receive_stock(product["id"], "N2", "2099-01-01", 1, 0, 50, 55)
        self.assertEqual((updated["price"], updated["mrp"]), (50, 55))

    def test_update_product_admin_only(self):
        self.staff()
        product = self.svc.inventory.products()[0]
        with self.assertRaises(AuthError):
            self.svc.inventory.update_product(product["id"], {**product, "name": "X"})
        self.svc.auth.logout()
        self.admin()
        updated = self.svc.inventory.update_product(product["id"], {**product, "name": "Renamed", "barcode": ""})
        self.assertEqual(updated["name"], "Renamed")
        self.assertEqual(updated["stock"], product["stock"])


class OutdatedDatabaseTests(unittest.TestCase):
    def test_database_without_pack_columns_is_reported(self):
        import sqlite3
        from contextlib import closing
        from phx.data.database import Database, DataError
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old.sqlite3"
            with closing(sqlite3.connect(path)) as conn:
                conn.execute("CREATE TABLE products (id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '',"
                             " category TEXT, hsn TEXT, reorder INTEGER, price REAL NOT NULL, mrp REAL NOT NULL,"
                             " gst INTEGER, emoji TEXT, tone TEXT)")
                conn.commit()
            with self.assertRaises(DataError) as ctx:
                Database(path)
            self.assertIn("units_per_pack", str(ctx.exception))


class BackupTests(ServiceTestCase):
    def folders(self):
        return Path(self.tmp.name) / "local", Path(self.tmp.name) / "cloud" / "Phoebix Backups"

    def test_backup_to_local_and_cloud_and_prune(self):
        import zipfile
        self.admin()
        local, cloud = self.folders()
        cloud.parent.mkdir()
        self.svc.backup.save_settings({"localDir": str(local), "cloudDir": str(cloud), "keep": 3})
        results = [self.svc.backup.backup_now() for _ in range(5)]
        self.assertTrue(all(r["cloudFile"] for r in results))
        self.assertEqual(len(list(local.glob("Phoebix-*.zip"))), 3)
        self.assertEqual(len(list(cloud.glob("Phoebix-*.zip"))), 3)
        with zipfile.ZipFile(results[-1]["file"]) as zf:
            self.assertEqual(zf.namelist(), ["phoebix.sqlite3"])
        self.assertIsNone(self.svc.backup.warning())
        self.assertIsNone(self.svc.reports.dashboard()["backupWarning"])

    def test_missing_cloud_folder_still_backs_up_locally(self):
        self.admin()
        local, _ = self.folders()
        self.svc.backup.save_settings({"localDir": str(local), "cloudDir": "Z:\\nowhere\\Phoebix Backups", "keep": 5})
        result = self.svc.backup.backup_now()
        self.assertTrue(Path(result["file"]).is_file())
        self.assertIsNone(result["cloudFile"])
        self.assertTrue(result["cloudError"])
        self.assertIn("Cloud", self.svc.backup.warning())

    def test_restore_round_trip(self):
        self.admin()
        local, _ = self.folders()
        self.svc.backup.save_settings({"localDir": str(local), "keep": 10})
        before = len(self.svc.billing.sales())
        snapshot = self.svc.backup.backup_now()["file"]
        request, _, _ = self.request()
        self.svc.billing.checkout(request, "Cash")
        self.assertEqual(len(self.svc.billing.sales()), before + 1)
        result = self.svc.backup.restore(snapshot)
        self.assertTrue(Path(result["safetyBackup"]).is_file())
        self.assertEqual(len(self.svc.billing.sales()), before)
        self.assertTrue(self.svc.db.integrity_ok())

    def test_restore_rejects_non_backup_and_staff(self):
        self.admin()
        bogus = Path(self.tmp.name) / "bogus.zip"
        bogus.write_bytes(b"not a zip")
        with self.assertRaises(ServiceError):
            self.svc.backup.restore(bogus)
        self.svc.auth.logout()
        self.staff()
        with self.assertRaises(AuthError):
            self.svc.backup.restore(bogus)
        with self.assertRaises(AuthError):
            self.svc.backup.backup_now()

    def test_auto_backup_runs_once_per_day(self):
        self.assertIsNotNone(self.svc.backup.auto_backup("startup"))
        self.assertIsNone(self.svc.backup.auto_backup("startup"))
        self.assertIsNotNone(self.svc.backup.auto_backup("close", force=True))


class LayeringTests(unittest.TestCase):
    """Enforce: ui -> services -> domain/data, domain and data stay independent."""

    FORBIDDEN = {
        "domain": ("phx.data", "phx.services", "phx.ui", "sqlite3", "tkinter"),
        "data": ("phx.services", "phx.ui", "phx.domain", "tkinter"),
        "services": ("phx.ui", "tkinter", "sqlite3"),
        "ui": ("phx.data", "phx.domain", "sqlite3"),
    }

    def imports(self, path, package):
        names = []
        parts = ["phx", package]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = parts[: max(0, len(parts) - node.level + 1)]
                    names.append(".".join(base + ([node.module] if node.module else [])))
                elif node.module:
                    names.append(node.module)
        return names

    def test_layer_dependencies(self):
        for package, banned in self.FORBIDDEN.items():
            for path in (ROOT / "phx" / package).glob("*.py"):
                for name in self.imports(path, package):
                    for bad in banned:
                        self.assertFalse(name == bad or name.startswith(bad + "."),
                                         f"{path.name} ({package}) must not import {name}")

if __name__ == "__main__":
    unittest.main()
