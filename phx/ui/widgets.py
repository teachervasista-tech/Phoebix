"""Reusable form dialog and page base class."""
import calendar
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from ..services.core import ServiceError
from . import theme


class DatePickerEntry(ttk.Frame):
    """Date picker widget with calendar popup. Value stored as YYYY-MM-DD string."""

    def __init__(self, parent, textvariable=None, **kwargs):
        super().__init__(parent)
        self.var = textvariable or tk.StringVar()
        self.calendar_window = None

        # Entry field with calendar button
        entry_frame = ttk.Frame(self)
        entry_frame.pack(side="left", fill="x", expand=True)

        self.entry = ttk.Entry(entry_frame, textvariable=self.var, width=28)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<FocusOut>", self._validate_date)

        button = ttk.Button(self, text="📅", width=3, command=self._show_calendar)
        button.pack(side="left", padx=(4, 0))

    def _validate_date(self, event=None):
        """Validate date format (YYYY-MM-DD)."""
        value = self.var.get().strip()
        if not value:
            return
        try:
            datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            messagebox.showerror("Invalid Date", "Please enter date in YYYY-MM-DD format")
            self.var.set("")
            self.entry.focus_set()

    def _show_calendar(self):
        """Show calendar popup for date selection."""
        if self.calendar_window:
            self.calendar_window.lift()
            return

        # Parse current date or use today
        try:
            date_str = self.var.get().strip()
            year, month, day = map(int, date_str.split("-"))
        except (ValueError, AttributeError):
            now = datetime.now()
            year, month, day = now.year, now.month, now.day

        # Create calendar window
        self.calendar_window = tk.Toplevel(self.winfo_toplevel())
        self.calendar_window.title("Select Date")
        self.calendar_window.geometry("320x250")
        self.calendar_window.resizable(False, False)

        # Make it transient and modal
        self.calendar_window.transient(self.winfo_toplevel())

        # Top navigation frame
        nav_frame = ttk.Frame(self.calendar_window)
        nav_frame.pack(fill="x", padx=8, pady=8)

        ttk.Button(nav_frame, text="◀", width=3, command=lambda: self._prev_month(year, month)).pack(side="left")

        month_year = ttk.Label(nav_frame, text=f"{calendar.month_name[month]} {year}", style="CardH2.TLabel")
        month_year.pack(side="left", expand=True)
        self.month_year_label = month_year

        ttk.Button(nav_frame, text="▶", width=3, command=lambda: self._next_month(year, month)).pack(side="left")

        # Calendar grid
        cal_frame = ttk.Frame(self.calendar_window)
        cal_frame.pack(fill="both", expand=True, padx=8, pady=8)

        # Days of week header
        for i, day_name in enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]):
            label = ttk.Label(cal_frame, text=day_name, style="CardMuted.TLabel")
            label.grid(row=0, column=i, sticky="w", padx=2)

        # Calendar days
        cal = calendar.monthcalendar(year, month)
        for week_num, week in enumerate(cal, start=1):
            for day_num, day in enumerate(week):
                if day == 0:
                    continue
                is_selected = day == datetime.now().day and month == datetime.now().month and year == datetime.now().year
                btn = ttk.Button(
                    cal_frame,
                    text=str(day),
                    width=4,
                    command=lambda d=day, m=month, y=year: self._select_date(d, m, y)
                )
                btn.grid(row=week_num, column=day_num, sticky="ew", padx=2, pady=2)

        # Store references for navigation
        self._calendar_state = {"year": year, "month": month, "frame": cal_frame, "label": month_year}

        # Close handler
        def on_close():
            self.calendar_window = None

        self.calendar_window.protocol("WM_DELETE_WINDOW", on_close)

    def _prev_month(self, year, month):
        """Navigate to previous month."""
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        self._refresh_calendar(year, month)

    def _next_month(self, year, month):
        """Navigate to next month."""
        month += 1
        if month > 12:
            month = 1
            year += 1
        self._refresh_calendar(year, month)

    def _refresh_calendar(self, year, month):
        """Refresh calendar display."""
        # Clear existing calendar
        for widget in self._calendar_state["frame"].winfo_children():
            if widget != self._calendar_state["label"]:
                widget.destroy()

        # Recreate calendar
        self.calendar_window.destroy()
        self._show_calendar()

    def _select_date(self, day, month, year):
        """Set selected date and close calendar."""
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        self.var.set(date_str)
        if self.calendar_window:
            self.calendar_window.destroy()
            self.calendar_window = None


class FormDialog(tk.Toplevel):
    """Modal form. fields = [(key, label, kind, options, default)]; kind: text | password | combo | date | readonly.

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
            elif kind == "date":
                widget = DatePickerEntry(self, textvariable=var)
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
