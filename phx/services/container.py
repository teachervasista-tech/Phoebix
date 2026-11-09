"""Wires the data layer into the services; the single object handed to the UI."""
from ..data.database import Database
from .accounts import AuthService, UserService
from .billing import BillingService
from .bootstrap import bootstrap
from .catalog import CustomerService, InventoryService, LoyaltyService, SettingsService
from .core import Session
from .payments import PaymentService
from .phonepe import PhonePeGateway
from .reports import ReportService


class Services:
    def __init__(self, database, sample_path=None, gateway=None):
        # Accept either a Database object (already initialized) or a path string
        if isinstance(database, Database):
            self.db = database
            if sample_path:
                bootstrap(self.db, sample_path)
        else:
            # Legacy path-based initialization
            self.db = Database(database)
            if sample_path:
                bootstrap(self.db, sample_path)

        self.session = Session()
        self.auth = AuthService(self.db, self.session)
        self.users = UserService(self.db, self.session)
        self.settings = SettingsService(self.db, self.session)
        self.inventory = InventoryService(self.db, self.session)
        self.customers = CustomerService(self.db, self.session)
        self.loyalty = LoyaltyService(self.db, self.session)
        self.billing = BillingService(self.db, self.session)
        self.payments = PaymentService(self.db, self.session, gateway or PhonePeGateway())
        self.reports = ReportService(self.db, self.session)
