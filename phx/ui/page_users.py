from ..services.core import ServiceError
from .theme import DataTable
from .widgets import FormDialog, Page, guarded


class UsersPage(Page):
    title = "Users"
    subtitle = "Login IDs for staff — every sale is stamped with the signed-in user"
    admin_only = True

    def build(self):
        self.header([("Edit / reset password", self.edit, False), ("+ New user", self.add, True)])
        self.table = DataTable(self, [("username", "Login ID", 140, "w"), ("name", "Name", 200, "w"),
                                      ("role", "Role", 80, "w"), ("active", "Status", 80, "w"),
                                      ("must", "Password", 140, "w")], height=16, on_double=lambda _i: self.edit())
        self.table.pack(fill="both", expand=True)
        self.users = []

    def refresh(self):
        self.users = self.svc.users.list()
        self.table.set_rows([(u["id"], (u["username"], u["name"], u["role"], "Active" if u["active"] else "Disabled",
                                        "Must change at next sign-in" if u["mustChangePassword"] else "Set"),
                              None if u["active"] else "muted") for u in self.users])

    def add(self):
        def save(values):
            self.svc.users.create(values["username"], values["name"], values["role"], values["password"])
            self.refresh()
        FormDialog(self, "New user", [("username", "Login ID *", "text", None, ""), ("name", "Full name *", "text", None, ""),
                                      ("role", "Role", "combo", ["staff", "admin"], "staff"),
                                      ("password", "Temporary password *", "password", None, "")], save, "Create user",
                   note="The user must choose their own password at first sign-in.")

    def edit(self):
        user = next((u for u in self.users if str(u["id"]) == self.table.selected()), None)
        if not user:
            self.app.toast("Select a user first.")
            return

        def save(values):
            self.svc.users.update(user["id"], values["name"], values["role"], values["status"] == "Active",
                                  values["newPassword"] or None)
            self.refresh()
        FormDialog(self, f"Edit {user['username']}", [
            ("name", "Full name", "text", None, user["name"]), ("role", "Role", "combo", ["staff", "admin"], user["role"]),
            ("status", "Status", "combo", ["Active", "Disabled"], "Active" if user["active"] else "Disabled"),
            ("newPassword", "Reset password (optional)", "password", None, "")], save, "Save changes")
