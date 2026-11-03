"""Main window: sign-in flow, sidebar navigation and page hosting."""
import tkinter as tk
from tkinter import ttk

from ..services.container import Services
from . import theme
from .login import LoginFrame, force_password_change
from .page_customers import CustomersPage
from .page_dashboard import DashboardPage
from .page_inventory import InventoryPage
from .page_pos import PosPage
from .page_reports import ReportsPage
from .page_rewards import RewardsPage
from .page_settings import SettingsPage
from .page_users import UsersPage
from .invoice import InvoiceWindow

PAGES = [("dashboard", "▦  Dashboard", DashboardPage), ("pos", "🧾  New Sale", PosPage),
         ("inventory", "💊  Inventory", InventoryPage), ("customers", "👥  Customers", CustomersPage),
         ("rewards", "🎁  Rewards & Offers", RewardsPage), ("reports", "📊  Reports", ReportsPage),
         ("users", "🔑  Users", UsersPage), ("settings", "⚙  Settings", SettingsPage)]


class PhoebixApp(tk.Tk):
    def __init__(self, services: Services):
        super().__init__()
        self.services = services
        self.title("Phoebix — Pharmacy")
        self.geometry("1320x820")
        self.minsize(1080, 680)
        theme.apply_theme(self)
        self._body = None
        self._pages, self._nav, self._current = {}, {}, None
        self._toast_job = None
        self.show_login()

    # ---- sign-in flow -------------------------------------------------
    def show_login(self):
        self._reset_body()
        self._pages.clear()
        self._body = LoginFrame(self, self.services, self.after_login)
        self._body.pack(fill="both", expand=True)

    def after_login(self, user):
        if user["mustChangePassword"]:
            force_password_change(self, self.services, self.show_shell, self.sign_out)
        else:
            self.show_shell()

    def sign_out(self):
        self.services.auth.logout()
        self.show_login()

    def _reset_body(self):
        if self._body is not None:
            self._body.destroy()
            self._body = None

    # ---- shell ---------------------------------------------------------
    def show_shell(self):
        self._reset_body()
        user = self.services.session.user
        shell = ttk.Frame(self)
        shell.pack(fill="both", expand=True)
        self._body = shell
        side = ttk.Frame(shell, style="Side.TFrame", padding=(14, 22, 14, 14), width=230)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        ttk.Label(side, text="Phoebix", style="Brand.TLabel").pack(anchor="w", padx=8)
        store = self.services.settings.store()
        ttk.Label(side, text=f"{store['name']} · {store['branch']}", style="Side.TLabel", wraplength=190).pack(
            anchor="w", padx=8, pady=(2, 18))
        self._nav.clear()
        for key, label, page_class in PAGES:
            if page_class.admin_only and not self.services.session.is_admin:
                continue
            button = ttk.Button(side, text=label, style="Nav.TButton", command=lambda k=key: self.navigate(k))
            button.pack(fill="x", pady=1)
            self._nav[key] = button
        ttk.Label(side, text="").pack(expand=True)
        ttk.Label(side, text=f"{user['name']}\n@{user['username']} · {user['role']}", style="Side.TLabel",
                  justify="left").pack(anchor="w", padx=8, pady=(0, 8))
        ttk.Button(side, text="Sign out", command=self.sign_out).pack(fill="x")
        self.content = ttk.Frame(shell)
        self.content.pack(side="left", fill="both", expand=True)
        self.status = ttk.Label(self.content, text="", style="Muted.TLabel", padding=(28, 4))
        self.status.pack(side="bottom", fill="x")
        self._host = ttk.Frame(self.content)
        self._host.pack(fill="both", expand=True)
        self._current = None
        self.navigate("dashboard")

    def navigate(self, key):
        if self._current:
            self._pages[self._current].pack_forget()
            self._nav[self._current].configure(style="Nav.TButton")
        if key not in self._pages:
            page_class = next(c for k, _l, c in PAGES if k == key)
            self._pages[key] = page_class(self._host, self)
        self._current = key
        self._nav[key].configure(style="NavActive.TButton")
        self._pages[key].pack(fill="both", expand=True)
        self._pages[key].refresh()

    def refresh_pages(self, *keys):
        """Mark other pages stale so they reload when next shown (the visible one reloads now)."""
        for key, page in self._pages.items():
            if key == self._current:
                page.refresh()

    # ---- helpers used by pages ----------------------------------------
    def toast(self, message):
        self.status.configure(text=message)
        if self._toast_job:
            self.after_cancel(self._toast_job)
        self._toast_job = self.after(5000, lambda: self.status.configure(text=""))

    def open_invoice(self, sale_id):
        from .widgets import guarded
        ok, invoice = guarded(self, lambda: self.services.billing.invoice(sale_id))
        if ok:
            InvoiceWindow(self, invoice)
