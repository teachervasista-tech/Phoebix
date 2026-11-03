"""Sign-in screen and the forced first-login password change."""
import tkinter as tk
from tkinter import ttk

from ..services.core import ServiceError
from . import theme
from .widgets import FormDialog


class LoginFrame(ttk.Frame):
    def __init__(self, parent, services, on_success):
        super().__init__(parent)
        self.services, self.on_success = services, on_success
        box = theme.card(self, padding=32)
        box.place(relx=0.5, rely=0.45, anchor="center")
        ttk.Label(box, text="Phoebix", style="CardH2.TLabel", font=(theme.FONT, 26, "bold"),
                  foreground=theme.GREEN).grid(row=0, column=0, sticky="w")
        ttk.Label(box, text="Pharmacy billing, inventory & rewards", style="CardMuted.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 18))
        self.username, self.password = tk.StringVar(), tk.StringVar()
        ttk.Label(box, text="Login ID", style="Card.TLabel").grid(row=2, column=0, sticky="w")
        user_entry = ttk.Entry(box, textvariable=self.username, width=34)
        user_entry.grid(row=3, column=0, sticky="ew", pady=(2, 10))
        ttk.Label(box, text="Password", style="Card.TLabel").grid(row=4, column=0, sticky="w")
        pass_entry = ttk.Entry(box, textvariable=self.password, show="•", width=34)
        pass_entry.grid(row=5, column=0, sticky="ew", pady=(2, 10))
        self.error = ttk.Label(box, text="", style="Error.TLabel", wraplength=300)
        self.error.grid(row=6, column=0, sticky="w")
        ttk.Button(box, text="Sign in", style="Primary.TButton", command=self.submit).grid(
            row=7, column=0, sticky="ew", pady=(8, 0))
        for widget in (user_entry, pass_entry):
            widget.bind("<Return>", lambda _e: self.submit())
        user_entry.focus_set()

    def submit(self):
        try:
            user = self.services.auth.login(self.username.get(), self.password.get())
        except ServiceError as error:
            self.error.configure(text=str(error))
            self.password.set("")
            return
        self.password.set("")
        self.on_success(user)


def force_password_change(root, services, on_done, on_cancel):
    def save(values):
        if values["new"] != values["confirm"]:
            raise ServiceError("The new passwords do not match.")
        services.auth.change_password(values["current"], values["new"])

    dialog = FormDialog(root, "Choose a new password", [
        ("current", "Current password", "password", None, ""),
        ("new", "New password", "password", None, ""),
        ("confirm", "Confirm new password", "password", None, ""),
    ], save, "Change password",
        note="This account uses a temporary password. Set your own (8 or more characters) to continue.")
    def finished(event):
        if event.widget is dialog:
            (on_cancel if services.session.user["mustChangePassword"] else on_done)()

    dialog.bind("<Destroy>", finished, add="+")
    return dialog
