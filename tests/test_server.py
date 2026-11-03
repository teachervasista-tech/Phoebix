import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server


def sample_state():
    return {
        "store": {"name": "Phoebix Test Pharmacy"},
        "rules": {"earnPer": 100},
        "products": [{"id": "p1", "name": "Paracetamol", "batches": [{"batch": "A1", "stock": 5}]}],
        "customers": [{"id": "c1", "name": "Priya"}],
        "transactions": [{"id": "INV-1", "total": 42.5}],
        "offers": [{"id": "o1", "name": "Wellness"}],
    }


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Path(self.temp_dir.name) / "phoebix.sqlite3"
        server.initialize_database(self.database, seed=False)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_round_trip_persists_all_collections(self):
        state = sample_state()
        saved = server.save_state(state, expected_revision=0, database=self.database)
        loaded = server.read_state(self.database)

        self.assertEqual(saved["revision"], 1)
        self.assertEqual(loaded["state"], state)
        self.assertEqual(loaded["revision"], 1)
        self.assertTrue(loaded["updatedAt"])

    def test_rejects_stale_revision_without_overwriting_data(self):
        original = sample_state()
        server.save_state(original, expected_revision=0, database=self.database)
        changed = sample_state()
        changed["store"]["name"] = "Stale edit"

        with self.assertRaises(server.StateConflict) as conflict:
            server.save_state(changed, expected_revision=0, database=self.database)

        self.assertEqual(conflict.exception.revision, 1)
        self.assertEqual(server.read_state(self.database)["state"], original)

    def test_rejects_duplicate_record_ids(self):
        invalid = sample_state()
        invalid["customers"].append({"id": "c1", "name": "Duplicate"})

        with self.assertRaisesRegex(ValueError, "ids must be unique"):
            server.save_state(invalid, expected_revision=0, database=self.database)

    def test_add_customer_persists_and_rejects_duplicates(self):
        server.save_state(sample_state(), expected_revision=0, database=self.database)
        result = server.add_customer({"name": "Ravi Kumar", "phone": "+91 98765 43210", "expectedRevision": 1}, self.database)

        loaded = server.read_state(self.database)
        self.assertEqual(result["revision"], 2)
        self.assertEqual(loaded["revision"], 2)
        self.assertEqual(loaded["state"]["customers"][0]["id"], result["customer"]["id"])
        self.assertEqual(loaded["state"]["customers"][0]["initials"], "RK")
        self.assertEqual(len(loaded["state"]["customers"]), 2)
        with self.assertRaisesRegex(ValueError, "already exists"):
            server.add_customer({"name": "Other", "phone": "9876543210"}, self.database)
        with self.assertRaises(server.StateConflict):
            server.add_customer({"name": "Other", "phone": "9123456780", "expectedRevision": 1}, self.database)

    def test_login_sessions_and_lockout(self):
        server.initialize_database(self.database)
        server.failed_logins.clear()
        with self.assertRaises(server.AuthError):
            server.login("admin", "wrong-password", self.database)
        token, user = server.login("ADMIN", "admin123", self.database)
        self.assertEqual(user["username"], "admin")
        self.assertTrue(user["mustChangePassword"])
        self.assertEqual(server.get_session_user(token, self.database)["id"], user["id"])
        self.assertNotIn("password", " ".join(user))

        changed = server.change_password(user["id"], "admin123", "NewSecret99", token, self.database)
        self.assertFalse(changed["mustChangePassword"])
        server.logout(token, self.database)
        self.assertIsNone(server.get_session_user(token, self.database))
        with self.assertRaises(server.AuthError):
            server.login("admin", "admin123", self.database)

        server.failed_logins.clear()
        for _ in range(server.MAX_FAILED_LOGINS):
            with self.assertRaises(server.AuthError):
                server.login("cashier", "nope-nope", self.database)
        with self.assertRaises(server.AuthError) as locked:
            server.login("cashier", "cashier123", self.database)
        self.assertEqual(locked.exception.status, 429)
        server.failed_logins.clear()

    def test_sales_are_stamped_with_the_signed_in_user_and_cannot_be_reassigned(self):
        server.initialize_database(self.database)
        users = {entry["username"]: entry for entry in server.list_users(self.database)}
        admin, cashier = users["admin"], users["cashier"]
        state = sample_state()
        state["transactions"][0]["soldBy"] = {"userId": "forged", "username": "forged", "name": "Forged"}
        saved = server.save_state(state, expected_revision=server.read_state(self.database)["revision"], database=self.database, user=cashier)
        self.assertEqual(server.read_state(self.database)["state"]["transactions"][0]["soldBy"]["username"], "cashier")

        again = server.read_state(self.database)["state"]
        again["transactions"][0]["soldBy"] = {"userId": admin["id"], "username": "admin", "name": "Arjun Sharma"}
        again["transactions"].insert(0, {"id": "INV-2", "total": 10, "soldBy": {"userId": "forged", "username": "forged", "name": "Forged"}})
        server.save_state(again, expected_revision=saved["revision"], database=self.database, user=admin)
        final = {entry["id"]: entry["soldBy"]["username"] for entry in server.read_state(self.database)["state"]["transactions"]}
        self.assertEqual(final, {"INV-1": "cashier", "INV-2": "admin"})

    def test_user_management_guards(self):
        server.initialize_database(self.database)
        admin = next(entry for entry in server.list_users(self.database) if entry["username"] == "admin")
        created = server.create_user({"username": "Meera_K", "name": "Meera K", "role": "staff", "password": "Temp1234"}, self.database)
        self.assertEqual(created["username"], "meera_k")
        with self.assertRaisesRegex(ValueError, "already taken"):
            server.create_user({"username": "meera_k", "name": "Dup", "role": "staff", "password": "Temp1234"}, self.database)
        with self.assertRaises(ValueError):
            server.create_user({"username": "x y", "name": "Bad", "role": "staff", "password": "Temp1234"}, self.database)
        with self.assertRaisesRegex(ValueError, "own administrator"):
            server.update_user(admin["id"], {"active": False}, admin, self.database)

        token, _ = server.login("meera_k", "Temp1234", self.database)
        server.update_user(created["id"], {"active": False}, admin, self.database)
        self.assertIsNone(server.get_session_user(token, self.database))
        with self.assertRaises(server.AuthError):
            server.login("meera_k", "Temp1234", self.database)

    def test_bank_details_are_validated_and_admin_only(self):
        server.initialize_database(self.database)
        users = {entry["username"]: entry for entry in server.list_users(self.database)}
        admin, cashier = users["admin"], users["cashier"]
        bank = {"accountHolder": "Greenleaf Pharmacy", "bankName": "HDFC Bank", "branch": "Banjara Hills",
                "accountNumber": "5010 0123 4567 89", "ifsc": "hdfc0001234", "accountType": "Current", "upiId": "greenleaf@okhdfcbank"}

        def save(user, bank_details):
            current = server.read_state(self.database)
            state = current["state"]
            state["store"]["bank"] = bank_details
            return server.save_state(state, current["revision"], self.database, user=user)

        with self.assertRaises(server.AuthError):
            save(cashier, bank)
        for bad in ({**bank, "ifsc": "BAD"}, {**bank, "accountNumber": "12ab"}, {**bank, "upiId": "no-at-sign"}):
            with self.assertRaises(ValueError):
                save(admin, bad)

        save(admin, bank)
        stored = server.read_state(self.database)["state"]["store"]["bank"]
        self.assertEqual((stored["accountNumber"], stored["ifsc"]), ("50100123456789", "HDFC0001234"))
        # Staff can still save other settings while the bank details stay unchanged.
        current = server.read_state(self.database)
        current["state"]["store"]["phone"] = "9876543210"
        server.save_state(current["state"], current["revision"], self.database, user=cashier)
        self.assertEqual(server.read_state(self.database)["state"]["store"]["bank"], stored)

    def test_initialization_seeds_sample_data(self):
        server.initialize_database(self.database)
        loaded = server.read_state(self.database)

        self.assertEqual(len(loaded["state"]["products"]), 9)
        self.assertEqual(len(loaded["state"]["customers"]), 6)
        self.assertEqual(len(loaded["state"]["transactions"]), 6)
        self.assertEqual(loaded["revision"], 1)

    @patch.dict(os.environ, {
        "PHONEPE_ENV": "sandbox",
        "PHONEPE_CLIENT_ID": "test-client",
        "PHONEPE_CLIENT_SECRET": "test-secret",
        "PHONEPE_CLIENT_VERSION": "1",
    })
    @patch("server.phonepe_api_request")
    def test_phonepe_checkout_records_sale_only_after_verified_completion(self, gateway_request):
        server.initialize_database(self.database)
        cashier = next(entry for entry in server.list_users(self.database) if entry["username"] == "cashier")
        gateway_request.return_value = {
            "orderId": "phonepe-order-1",
            "redirectUrl": "https://checkout.phonepe.test/session",
        }
        transaction = {
            "id": "INV-1049",
            "customerId": None,
            "customerName": "Walk-in customer",
            "date": "2026-11-03",
            "total": 29.4,
            "items": 1,
            "payment": "UPI",
            "status": "Paid",
            "earned": 0,
            "redeemed": 0,
            "totals": {"subtotal": 28, "tax": 1.4, "discount": 0, "redeem": 0, "total": 29.4},
        }
        lines = [{
            "id": "p1",
            "batchId": "p1-batch-1",
            "name": "Paracetamol 650 mg",
            "batch": "PCM24A18",
            "expiry": "2027-12-28",
            "hsn": "30049099",
            "price": 28,
            "gst": 5,
            "qty": 1,
        }]
        created = server.create_phonepe_payment({
            "merchantOrderId": "PHX-TEST-ORDER-1",
            "amount": 2940,
            "expectedRevision": 1,
            "intent": {"transaction": {**transaction, "soldBy": {"userId": "forged", "username": "forged", "name": "Forged"}}, "lines": lines},
        }, database=self.database, user=cashier)
        self.assertEqual(created["redirectUrl"], "https://checkout.phonepe.test/session")
        self.assertEqual(server.read_state(self.database)["revision"], 1)
        self.assertEqual(len(server.read_state(self.database)["state"]["transactions"]), 6)

        gateway_request.return_value = {
            "state": "COMPLETED",
            "amount": 2940,
            "paymentDetails": [{"transactionId": "phonepe-txn-1", "paymentMode": "UPI_INTENT"}],
        }
        completed = server.complete_phonepe_payment("PHX-TEST-ORDER-1", database=self.database)
        saved = server.read_state(self.database)

        self.assertEqual(completed["status"], "COMPLETED")
        self.assertEqual(saved["revision"], 2)
        self.assertEqual(saved["state"]["transactions"][0]["phonepeTransactionId"], "phonepe-txn-1")
        self.assertEqual(saved["state"]["transactions"][0]["soldBy"]["username"], "cashier")
        self.assertEqual(saved["state"]["products"][0]["stock"], 83)
        duplicate_callback = server.complete_phonepe_payment("PHX-TEST-ORDER-1", database=self.database)
        self.assertEqual(duplicate_callback["status"], "COMPLETED")
        self.assertEqual(server.read_state(self.database)["revision"], 2)

    @patch.dict(os.environ, {
        "PHONEPE_ENV": "sandbox",
        "PHONEPE_CLIENT_ID": "test-client",
        "PHONEPE_CLIENT_SECRET": "test-secret",
        "PHONEPE_CLIENT_VERSION": "1",
    })
    @patch("server.phonepe_api_request")
    def test_phonepe_pending_payment_does_not_change_inventory_or_sales(self, gateway_request):
        server.initialize_database(self.database)
        gateway_request.return_value = {"orderId": "phonepe-order-1", "redirectUrl": "https://checkout.phonepe.test/session"}
        transaction = {
            "id": "INV-1049",
            "customerId": None,
            "customerName": "Walk-in customer",
            "date": "2026-11-03",
            "total": 29.4,
            "payment": "UPI",
        }
        line = {"id": "p1", "batchId": "p1-batch-1", "qty": 1}
        server.create_phonepe_payment({
            "merchantOrderId": "PHX-TEST-ORDER-2",
            "amount": 2940,
            "expectedRevision": 1,
            "intent": {"transaction": transaction, "lines": [line]},
        }, database=self.database)
        gateway_request.return_value = {"state": "PENDING", "amount": 2940}

        result = server.complete_phonepe_payment("PHX-TEST-ORDER-2", database=self.database)
        saved = server.read_state(self.database)

        self.assertEqual(result["status"], "PENDING")
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(len(saved["state"]["transactions"]), 6)
        self.assertEqual(saved["state"]["products"][0]["stock"], 84)

    @patch.dict(os.environ, {
        "PHONEPE_ENV": "sandbox",
        "PHONEPE_CLIENT_ID": "test-client",
        "PHONEPE_CLIENT_SECRET": "test-secret",
        "PHONEPE_CLIENT_VERSION": "1",
    })
    @patch("server.phonepe_api_request")
    def test_phonepe_amount_mismatch_never_records_a_sale(self, gateway_request):
        server.initialize_database(self.database)
        gateway_request.return_value = {"orderId": "phonepe-order-1", "redirectUrl": "https://checkout.phonepe.test/session"}
        transaction = {"id": "INV-1049", "customerId": None, "customerName": "Walk-in customer", "date": "2026-11-03", "total": 29.4, "payment": "UPI"}
        line = {"id": "p1", "batchId": "p1-batch-1", "qty": 1}
        server.create_phonepe_payment({
            "merchantOrderId": "PHX-TEST-ORDER-3",
            "amount": 2940,
            "expectedRevision": 1,
            "intent": {"transaction": transaction, "lines": [line]},
        }, database=self.database)
        gateway_request.return_value = {"state": "COMPLETED", "amount": 100}

        with self.assertRaisesRegex(server.PaymentGatewayError, "does not match"):
            server.complete_phonepe_payment("PHX-TEST-ORDER-3", database=self.database)

        saved = server.read_state(self.database)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(len(saved["state"]["transactions"]), 6)
        self.assertEqual(saved["state"]["products"][0]["stock"], 84)


if __name__ == "__main__":
    unittest.main()
