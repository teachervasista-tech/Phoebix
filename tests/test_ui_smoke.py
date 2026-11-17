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

    def test_settings_is_admin_only(self):
        self.sign_in("cashier", "cashier123")
        self.assertNotIn("settings", self.app._nav)
        self.app.navigate("settings")
        self.assertNotIn("settings", self.app._pages)
        self.assertEqual(self.app._current, "dashboard")

    def test_settings_scrolls_when_window_is_small(self):
        self.sign_in("admin", "admin123")
        self.app.geometry("1100x600")
        self.app.navigate("settings")
        for _ in range(5):
            self.app.update()
        scroller = self.app._pages["settings"].scroller
        self.assertTrue(scroller.scrollbar.winfo_ismapped(), "scrollbar shown when content is taller than window")
        scroller.canvas.yview_moveto(1.0)
        self.app.update()
        self.assertGreater(scroller.canvas.yview()[0], 0)

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


    def test_pos_quantity_popup_and_row_controls(self):
        from phx.ui.page_pos import QuantityDialog
        self.sign_in("cashier", "cashier123")
        self.app.navigate("pos")
        page = self.app._pages["pos"]
        tabs = next(p for p in page.products if p["name"] == "Paracetamol 650 mg")  # 15 per strip
        page.pick_product(tabs["id"])
        self.app.update()
        dialog = next(w for w in page.winfo_children() if isinstance(w, QuantityDialog))
        dialog.strips.set("2")
        dialog.tabs.set("5")
        self.assertEqual(dialog.total.cget("text"), f"Total ₹{2 * 28 + 5 * round(28 / 15, 2):.2f}")
        dialog.submit()
        self.assertFalse(dialog.winfo_exists())
        self.assertEqual(sorted((l["unit"], l["qty"]) for l in page.cart), [("loose", 5), ("pack", 2)])
        rows = page.cart_list.row_widgets
        self.assertEqual(len(rows), 2)
        loose_row = next(r for r in rows if r["line"]["unit"] == "loose")
        loose_row["plus"].invoke()
        self.assertEqual(next(l for l in page.cart if l["unit"] == "loose")["qty"], 6)
        loose_row = next(r for r in page.cart_list.row_widgets if r["line"]["unit"] == "loose")
        loose_row["minus"].invoke()
        self.assertEqual(next(l for l in page.cart if l["unit"] == "loose")["qty"], 5)
        next(r for r in page.cart_list.row_widgets if r["line"]["unit"] == "pack")["remove"].invoke()
        self.assertEqual([(l["unit"], l["qty"]) for l in page.cart], [("loose", 5)])
        # Too many: error shown, nothing added.
        page.pick_product(tabs["id"])
        self.app.update()
        dialog = next(w for w in page.winfo_children() if isinstance(w, QuantityDialog))
        dialog.strips.set("9999")
        dialog.submit()
        self.assertIn("available", dialog.error.cget("text"))
        dialog.destroy()
        self.assertEqual([(l["unit"], l["qty"]) for l in page.cart], [("loose", 5)])
        # Pack-only products are added directly, without the popup.
        syrup = next(p for p in page.products if p["name"] == "Cough Relief Syrup")
        page.pick_product(syrup["id"])
        self.app.update()
        self.assertFalse(any(isinstance(w, QuantityDialog) for w in page.winfo_children()))
        self.assertIn(("pack", 1), [(l["unit"], l["qty"]) for l in page.cart if l["productId"] == syrup["id"]])

    def test_pos_scan_adds_to_bill(self):
        from phx.ui.page_pos import QuantityDialog
        self.sign_in("admin", "admin123")
        products = {p["name"]: p for p in self.services.inventory.products()}
        syrup, tabs = products["Cough Relief Syrup"], products["Paracetamol 650 mg"]
        self.services.inventory.link_barcode(syrup["id"], "4006381333931")
        self.services.inventory.link_barcode(tabs["id"], "8901234567894")
        # A second Paracetamol batch, expiring later than the first, to check the scanned batch is billed.
        self.services.inventory.receive_stock(tabs["id"], "LATE1", "2099-01-01", 3)
        self.app.navigate("pos")
        page = self.app._pages["pos"]
        # Pack-only item: each scan adds one, no popup.
        for _ in range(2):
            page.search.set("4006381333931")
            page.on_search_enter()
        self.assertEqual([(l["productId"], l["qty"]) for l in page.cart], [(syrup["id"], 2)])
        self.assertEqual(page.search.get(), "")
        # Tablets with a 2D code naming batch LATE1: popup, Enter = 1 strip from that batch.
        page.search.set("0108901234567894\x1d17990101\x1d10LATE1")
        page.on_search_enter()
        dialog = self.open_dialog(page, QuantityDialog)
        dialog.submit()
        line = next(l for l in page.cart if l["productId"] == tabs["id"])
        self.assertEqual((line["unit"], line["qty"], line["batch"]), ("pack", 1, "LATE1"))
        # Unknown code: nothing added.
        before = len(page.cart)
        page.search.set("5012345678900")
        page.on_search_enter()
        self.assertEqual(len(page.cart), before)
        # Name search with a single match + Enter adds it.
        page.search.set("thermometer")
        page.on_search_enter()
        self.assertTrue(any(l["name"] == "Digital Thermometer" for l in page.cart))

    def test_pos_strip_and_loose_tablet(self):
        self.sign_in("cashier", "cashier123")
        self.app.navigate("pos")
        page = self.app._pages["pos"]
        product = next(p for p in page.products if p["allowLoose"])
        page.add_product(product["id"], "pack")
        page.add_product(product["id"], "loose")
        page.add_product(product["id"], "loose")
        self.assertEqual([(l["unit"], l["qty"]) for l in page.cart], [("pack", 1), ("loose", 2)])
        syrup = next(p for p in page.products if not p["allowLoose"])
        page.add_product(syrup["id"], "loose")
        self.assertEqual(len(page.cart), 2, "loose sale of a pack-only product is refused")
        opened = []
        self.app.open_invoice = opened.append
        page.checkout()
        from phx.ui.invoice import InvoiceWindow, invoice_html
        invoice = self.services.billing.invoice(opened[0])
        self.assertIn("2 tab", invoice_html(invoice))
        window = InvoiceWindow(self.app, invoice)
        self.assertIn("1 strip", window.render_text())
        window.destroy()


    def test_date_fields_use_calendar(self):
        from datetime import date
        from phx.ui.widgets import CalendarPopup, DatePickerEntry, FormDialog
        self.sign_in("admin", "admin123")
        self.app.navigate("inventory")
        page = self.app._pages["inventory"]
        page.add()
        self.app.update()
        dialog = next(w for w in page.winfo_children() if isinstance(w, FormDialog))
        picker = next(w for w in dialog.winfo_children() if isinstance(w, DatePickerEntry))
        picker.open_calendar()
        self.app.update()
        popup = picker.popup
        self.assertIsInstance(popup, CalendarPopup)
        start = (popup.year, popup.month)
        popup.shift(1)
        self.assertNotEqual((popup.year, popup.month), start, "month navigation moves")
        popup.shift(-13)
        past_buttons = [b for b in popup.grid_frame.winfo_children()
                        if b.winfo_class() == "Button" and b.cget("state") == "disabled"]
        self.assertTrue(past_buttons, "days before today are disabled for expiry dates")
        popup.pick(date(2099, 3, 4))
        self.assertEqual(dialog._vars["expiry"].get(), "2099-03-04")
        self.assertFalse(popup.winfo_exists())
        dialog.destroy()

    def open_dialog(self, page, cls):
        self.app.update()
        return next(w for w in page.winfo_children() if isinstance(w, cls) and w.winfo_exists())

    def test_edit_product_dialog_saves(self):
        from phx.ui.widgets import FormDialog
        self.sign_in("admin", "admin123")
        self.app.navigate("inventory")
        page = self.app._pages["inventory"]
        product = next(p for p in page.products if p["name"] == "Antiseptic Cream")
        page.table.tree.selection_set(f"{product['id']}|{product['batches'][0]['id']}")
        page.edit_product()
        dialog = self.open_dialog(page, FormDialog)
        self.assertEqual(dialog._vars["name"].get(), "Antiseptic Cream")
        dialog._vars["unitsPerPack"].set("10")
        dialog._vars["allowLoose"].set("Yes")
        dialog._vars["barcode"].set("8901234567894")
        dialog._vars["mrp"].set("60")
        dialog.submit()
        self.assertFalse(dialog.winfo_exists(), dialog.error.cget("text") if dialog.winfo_exists() else "")
        after = next(p for p in self.services.inventory.products() if p["id"] == product["id"])
        self.assertEqual((after["unitsPerPack"], after["allowLoose"], after["mrp"], after["barcode"]),
                         (10, True, 60.0, "08901234567894"))

    def test_scan_known_and_unknown_barcodes(self):
        from phx.ui.page_inventory import UnknownBarcodeDialog
        from phx.ui.widgets import FormDialog
        self.sign_in("cashier", "cashier123")
        self.app.navigate("inventory")
        page = self.app._pages["inventory"]
        # Unknown GS1 DataMatrix scan -> choose "new product" -> Add form pre-filled from the scan.
        page.scan_text.set("0108901234567894\x1d17271231\x1d10AB123")
        page.on_scan()
        self.open_dialog(page, UnknownBarcodeDialog).new_product()
        add = self.open_dialog(page, FormDialog)
        self.assertEqual((add._vars["barcode"].get(), add._vars["batch"].get(), add._vars["expiry"].get()),
                         ("08901234567894", "AB123", "2027-12-31"))
        for key, value in (("name", "Scanned Tabs"), ("price", "40"), ("mrp", "45"), ("unitsPerPack", "10"),
                           ("stock", "3")):
            add._vars[key].set(value)
        add.submit()
        self.assertFalse(add.winfo_exists(), add.error.cget("text") if add.winfo_exists() else "")
        # Scanning it again finds the product and opens Receive stock with batch/expiry from the code.
        page.scan_text.set("(01)08901234567894(17)280630(10)CD9")
        page.on_scan()
        receive = self.open_dialog(page, FormDialog)
        self.assertEqual(receive._vars["product"].get(), "Scanned Tabs")
        self.assertEqual((receive._vars["batch"].get(), receive._vars["expiry"].get()), ("CD9", "2028-06-30"))
        receive._vars["quantity"].set("2")
        receive.submit()
        product = next(p for p in self.services.inventory.products() if p["name"] == "Scanned Tabs")
        self.assertEqual(product["stock"], 50)
        # Unknown plain EAN -> link to an existing product.
        page.scan_text.set("4006381333931")
        page.on_scan()
        dialog = self.open_dialog(page, UnknownBarcodeDialog)
        dialog.choice.set(next(k for k in dialog.choices if k.startswith("Cough Relief Syrup")))
        dialog.link()
        receive = self.open_dialog(page, FormDialog)
        self.assertEqual(receive._vars["product"].get(), "Cough Relief Syrup")
        receive.destroy()
        syrup = next(p for p in self.services.inventory.products() if p["name"] == "Cough Relief Syrup")
        self.assertEqual(syrup["barcode"], "04006381333931")


if __name__ == "__main__":
    unittest.main()
