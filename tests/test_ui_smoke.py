import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from phx.services.container import Services
from phx.ui.app import PAGES, PhoebixApp

SAMPLE = Path(__file__).resolve().parents[1] / "sample_state.json"


class UiSmokeTests(unittest.TestCase):
    def setUp(self):
        try:
            probe = tk.Tk()
            probe.destroy()
        except tk.TclError as error:
            self.skipTest(f"No display available: {error}")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.services = Services(Path(self.tmp.name) / "ui.sqlite3", SAMPLE)
        self.app = PhoebixApp(self.services)
        self.addCleanup(self.app.destroy)

    def sign_in(self, username, password):
        self.services.auth.login(username, password)
        self.services.auth.change_password(password, password + "-changed")
        self.app.show_shell()
        self.app.update()

    def test_every_page_renders_for_admin(self):
        self.sign_in("admin", "admin123")
        for key, _label, _cls in PAGES:
            self.app.navigate(key)
            self.app.update()

    def test_staff_has_no_users_page(self):
        self.sign_in("cashier", "cashier123")
        self.assertNotIn("users", self.app._nav)

    def test_pos_checkout_flow(self):
        self.sign_in("cashier", "cashier123")
        self.app.navigate("pos")
        page = self.app._pages["pos"]
        page.add_product(page.products[0]["id"])
        page.add_product(page.products[0]["id"])
        self.assertEqual(page.cart[0]["qty"], 2)
        sales_before = len(self.services.billing.sales())
        opened = []
        self.app.open_invoice = opened.append
        page.checkout()
        self.assertEqual(len(self.services.billing.sales()), sales_before + 1)
        self.assertEqual(self.services.billing.sales()[0]["soldBy"]["username"], "cashier")
        self.assertEqual(len(opened), 1)
        self.assertEqual(page.cart, [])


if __name__ == "__main__":
    unittest.main()
