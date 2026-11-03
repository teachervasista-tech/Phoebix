"""Reusable form dialog and page base class."""
import tkinter as tk
from tkinter import messagebox, ttk

from ..services.core import ServiceError
from . import theme


class FormDialog(tk.Toplevel):
    """Modal form. fields = [(key, label, kind, options, default)]; kind: text | password | combo | readonly.

    on_submit(values) runs the service call and may raise ServiceError, which is shown inline
    so the dialog stays open and the user can correct the input.
    """

    def __init__(self, parent, title, fields, on_submit, submit_text="Save", note=None, width=420):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.configure(background=theme.CARD, padx=22, pady=18)
        self.resizable(False, False)
        self._on_submit, self._vars = on_submit, {}
        ttk.Label(self, text=title, style="CardH2.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")
        row = 1
        if note:
            ttk.Label(self, text=note, style="CardMuted.TLabel", wraplength=width, justify="left").grid(
                row=row, column=0, columnspan=2, sticky="w", pady=(4, 0))
            row += 1
        first = None
        for key, label, kind, options, default in fields:
            ttk.Label(self, text=label, style="Card.TLabel").grid(row=row, column=0, sticky="w", pady=(10, 0), padx=(0, 14))
            var = tk.StringVar(value="" if default is None else str(default))
            self._vars[key] = var
            if kind == "combo":
                widget = ttk.Combobox(self, textvariable=var, values=options, state="readonly", width=28)
            elif kind == "readonly":
                widget = ttk.Entry(self, textvariable=var, state="readonly", width=30)
            else:
                widget = ttk.Entry(self, textvariable=var, show="•" if kind == "password" else "", width=30)
            widget.grid(row=row, column=1, sticky="ew", pady=(10, 0))
            first = first or widget
            row += 1
        self.error = ttk.Label(self, text="", style="Error.TLabel", wraplength=width, justify="left")
        self.error.grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(self, style="Card.TFrame")
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        self.submit_button = ttk.Button(buttons, text=submit_text, style="Primary.TButton", command=self.submit)
        self.submit_button.pack(side="right")
        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        self.grab_set()
        if first:
            first.focus_set()

    def submit(self):
        values = {key: var.get().strip() for key, var in self._vars.items()}
        try:
            self._on_submit(values)
        except ServiceError as error:
            self.error.configure(text=str(error))
            return
        self.destroy()


def show_error(parent, error):
    messagebox.showerror("Phoebix", str(error), parent=parent.winfo_toplevel())


def guarded(parent, action):
    """Run action(); show ServiceError to the user instead of crashing. Returns (ok, result)."""
    try:
        return True, action()
    except ServiceError as error:
        show_error(parent, error)
        return False, None


class Page(ttk.Frame):
    """Base for screens. `app` exposes services, navigation and notifications."""
    title = ""
    subtitle = ""
    admin_only = False

    def __init__(self, parent, app):
        super().__init__(parent, padding=(28, 22))
        self.app, self.svc = app, app.services
        self.build()

    def header(self, actions=()):
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 16))
        titles = ttk.Frame(bar)
        titles.pack(side="left")
        ttk.Label(titles, text=self.title, style="H1.TLabel").pack(anchor="w")
        if self.subtitle:
            ttk.Label(titles, text=self.subtitle, style="Muted.TLabel").pack(anchor="w")
        for text, command, primary in reversed(actions):
            ttk.Button(bar, text=text, command=command, style="Primary.TButton" if primary else "TButton").pack(
                side="right", padx=(8, 0))
        return bar

    def build(self):
        raise NotImplementedError

    def refresh(self):
        """Reload data from the services."""
