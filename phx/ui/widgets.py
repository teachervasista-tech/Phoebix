"""Reusable form dialog and page base class."""
import calendar
import tkinter as tk
from datetime import date, datetime
from tkinter import commondialog, messagebox, ttk

from ..services.core import ServiceError
from . import theme


def main_window(widget):
    """The application's main window (the root), whatever window `widget` lives in."""
    return widget.winfo_toplevel()._root()


def center_on_main(window, width=None, height=None):
    """Place `window` in the middle of the main app window (kept on screen).

    Call with the window withdrawn; it is shown (deiconified) here so it never flashes in the corner."""
    owner = main_window(window)
    window.update_idletasks()
    w = width or window.winfo_reqwidth()
    h = height or window.winfo_reqheight()
    if owner.winfo_ismapped():
        # Centre the outer frames (title bar + borders), not just the client areas, so it looks centred.
        border = max(0, owner.winfo_rootx() - owner.winfo_x())
        title = max(0, owner.winfo_rooty() - owner.winfo_y())
        owner_w, owner_h = owner.winfo_width() + 2 * border, owner.winfo_height() + title + border
        own_w, own_h = w + 2 * border, h + title + border
        x = owner.winfo_x() + (owner_w - own_w) // 2
        y = owner.winfo_y() + (owner_h - own_h) // 2
    else:
        x = (window.winfo_screenwidth() - w) // 2
        y = (window.winfo_screenheight() - h) // 2
    x = max(0, min(x, window.winfo_screenwidth() - w))
    y = max(0, min(y, window.winfo_screenheight() - h - 40))
    size = f"{w}x{h}" if width or height else ""
    window.geometry(f"{size}+{x}+{y}")
    window.deiconify()


def install_native_dialog_centering():
    """Centre Windows message boxes and file/folder pickers over the window that opened them.

    Tk hands these to Windows, which puts file pickers at the owner's top-left corner. Every one of them goes
    through tkinter.commondialog.Dialog.show, so while a dialog is open we find its window and move it once."""
    import os
    if os.name != "nt" or getattr(commondialog.Dialog, "_phoebix_centred", False):
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    enum_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    original_show = commondialog.Dialog.show

    def rect(hwnd):
        r = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right, r.bottom

    def frame(widget):
        try:
            return int(widget.winfo_toplevel().wm_frame(), 16)
        except (tk.TclError, ValueError):
            return None

    def centre_when_open(owner_widget, tries=100):
        owner = frame(owner_widget)
        if owner is None:
            return
        found = []

        def visit(hwnd, _):
            cls = ctypes.create_unicode_buffer(32)
            user32.GetClassNameW(hwnd, cls, 32)
            if cls.value == "#32770" and user32.IsWindowVisible(hwnd) and user32.GetWindow(hwnd, 4) == owner:
                found.append(hwnd)
            return True
        user32.EnumWindows(enum_proc(visit), 0)
        if not found:
            if tries:
                owner_widget.after(30, lambda: centre_when_open(owner_widget, tries - 1))
            return
        ol, ot, orr, ob = rect(owner)
        dl, dt, dr, db = rect(found[0])
        w, h = dr - dl, db - dt
        x, y = ol + (orr - ol - w) // 2, ot + (ob - ot - h) // 2
        user32.SetWindowPos(found[0], 0, max(0, x), max(0, y), 0, 0, 0x0001 | 0x0004 | 0x0010)

    def show(self, **options):
        owner = options.get("parent") or self.options.get("parent") or self.master or tk._default_root
        if owner is not None:
            owner.after(20, lambda: centre_when_open(owner))
        return original_show(self, **options)

    commondialog.Dialog.show = show
    commondialog.Dialog._phoebix_centred = True


def _parse_date(text):
    try:
        return datetime.strptime((text or "").strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


class CalendarPopup(tk.Toplevel):
    """Month calendar shown under a date field. Click a day to pick it; Esc or clicking away closes it."""

    def __init__(self, anchor, initial, on_pick, min_date=None):
        super().__init__(anchor.winfo_toplevel())
        self.withdraw()  # stay hidden until positioned, or Windows maps it at the screen's top-left corner
        self.on_pick, self.min_date, self.field = on_pick, min_date, anchor
        self.today = date.today()
        self.selected = initial
        start = initial or max(self.today, min_date or self.today)
        self.year, self.month = start.year, start.month
        self.overrideredirect(True)
        self.configure(background=theme.LINE, padx=1, pady=1)
        self.transient(anchor.winfo_toplevel())
        body = tk.Frame(self, background=theme.CARD, padx=8, pady=8)
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, background=theme.CARD)
        nav.pack(fill="x")
        for text, step in (("«", -12), ("‹", -1)):
            ttk.Button(nav, text=text, width=3, command=lambda s=step: self.shift(s)).pack(side="left")
        for text, step in (("»", 12), ("›", 1)):
            ttk.Button(nav, text=text, width=3, command=lambda s=step: self.shift(s)).pack(side="right")
        self.title_label = ttk.Label(nav, text="", style="CardH2.TLabel", anchor="center")
        self.title_label.pack(side="left", fill="x", expand=True)
        self.grid_frame = tk.Frame(body, background=theme.CARD)
        self.grid_frame.pack(pady=(6, 0))
        foot = tk.Frame(body, background=theme.CARD)
        foot.pack(fill="x", pady=(6, 0))
        ttk.Button(foot, text="Today", command=lambda: self.pick(self.today)).pack(side="left")
        ttk.Button(foot, text="Clear", command=lambda: self.pick(None)).pack(side="right")
        self.bind("<Escape>", lambda _e: self.destroy())
        self.draw()
        self.update_idletasks()
        x, y = anchor.winfo_rootx(), anchor.winfo_rooty() + anchor.winfo_height() + 2
        # Keep the popup on screen.
        x = min(x, self.winfo_screenwidth() - self.winfo_reqwidth() - 4)
        if y + self.winfo_reqheight() > self.winfo_screenheight() - 40:
            y = anchor.winfo_rooty() - self.winfo_reqheight() - 2
        self.geometry(f"+{max(0, x)}+{max(0, y)}")
        self.deiconify()
        self.lift()
        self.focus_set()
        # Clicking anywhere else in the owning window closes the calendar.
        self.owner = anchor.winfo_toplevel()
        self._click_bind = self.owner.bind("<Button-1>", self._outside_click, add="+")
        self.bind("<Destroy>", self._release_owner_click, add="+")

    def _outside_click(self, event):
        widget = str(event.widget)
        # Clicks inside the calendar, or on its own date field / button (which toggles), are not "outside".
        if self.winfo_exists() and not widget.startswith(str(self)) and not widget.startswith(str(self.field)):
            self.destroy()

    def _release_owner_click(self, event):
        if event.widget is self:
            try:
                self.owner.unbind("<Button-1>", self._click_bind)
            except tk.TclError:
                pass

    def shift(self, months):
        index = self.year * 12 + (self.month - 1) + months
        self.year, self.month = divmod(index, 12)
        self.month += 1
        self.draw()

    def draw(self):
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.title_label.configure(text=f"{calendar.month_name[self.month]} {self.year}")
        for col, name in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")):
            tk.Label(self.grid_frame, text=name, background=theme.CARD, foreground=theme.MUTED, width=4,
                     font=(theme.FONT, 9)).grid(row=0, column=col)
        for row, week in enumerate(calendar.monthcalendar(self.year, self.month), start=1):
            for col, day in enumerate(week):
                if not day:
                    continue
                current = date(self.year, self.month, day)
                disabled = bool(self.min_date and current < self.min_date)
                is_selected = current == self.selected
                is_today = current == self.today
                button = tk.Button(
                    self.grid_frame, text=str(day), width=3, relief="flat", cursor="hand2",
                    font=(theme.FONT, 9, "bold" if is_today or is_selected else "normal"),
                    background=theme.GREEN if is_selected else theme.CARD,
                    foreground="white" if is_selected else (theme.MUTED if disabled else theme.INK),
                    activebackground=theme.LINE, state="disabled" if disabled else "normal",
                    command=lambda d=current: self.pick(d))
                if is_today and not is_selected:
                    button.configure(highlightthickness=1, highlightbackground=theme.GREEN)
                button.grid(row=row, column=col, padx=1, pady=1)

    def pick(self, value):
        self.on_pick(value)
        self.destroy()


class DatePickerEntry(ttk.Frame):
    """Date field with a calendar button. Value is a YYYY-MM-DD string (typing still works).

    min_date: earliest selectable day in the calendar (e.g. today for expiry dates)."""

    def __init__(self, parent, textvariable=None, min_date=None, width=24, **kwargs):
        super().__init__(parent, **kwargs)
        self.var = textvariable or tk.StringVar()
        self.min_date = min_date
        self.popup = None
        self.entry = ttk.Entry(self, textvariable=self.var, width=width)
        self.entry.pack(side="left", fill="x", expand=True)
        self.entry.bind("<Alt-Down>", lambda _e: self.open_calendar())
        self.entry.bind("<Double-Button-1>", lambda _e: self.open_calendar())
        self.button = ttk.Button(self, text="📅", width=3, command=self.open_calendar)
        self.button.pack(side="left", padx=(4, 0))

    def focus_set(self):
        self.entry.focus_set()

    def open_calendar(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
            return
        self.popup = CalendarPopup(self, _parse_date(self.var.get()), self._picked, self.min_date)

    def _picked(self, value):
        self.var.set(value.isoformat() if value else "")
        self.entry.focus_set()
        self.entry.icursor("end")


class FormDialog(tk.Toplevel):
    """Modal form. fields = [(key, label, kind, options, default)]; kind: text | password | combo | date | readonly.

    on_submit(values) runs the service call and may raise ServiceError, which is shown inline
    so the dialog stays open and the user can correct the input.
    """

    def __init__(self, parent, title, fields, on_submit, submit_text="Save", note=None, width=420):
        super().__init__(parent)
        self.withdraw()  # shown by center_on_main once laid out
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.configure(background=theme.CARD, padx=22, pady=18)
        self.resizable(False, False)
        self._on_submit, self._vars = on_submit, {}
        # Long forms use two columns so they fit on small (e.g. 1366x768) screens.
        pairs = 2 if len(fields) > 9 else 1
        per_column = -(-len(fields) // pairs)
        span = pairs * 2
        if pairs == 2:
            width = width * 2
        ttk.Label(self, text=title, style="CardH2.TLabel").grid(row=0, column=0, columnspan=span, sticky="w")
        start = 1
        if note:
            ttk.Label(self, text=note, style="CardMuted.TLabel", wraplength=width, justify="left").grid(
                row=start, column=0, columnspan=span, sticky="w", pady=(4, 0))
            start += 1
        first = None
        for index, (key, label, kind, options, default) in enumerate(fields):
            row, pair = start + index % per_column, index // per_column
            ttk.Label(self, text=label, style="Card.TLabel").grid(
                row=row, column=pair * 2, sticky="w", pady=(10, 0), padx=(28 if pair else 0, 14))
            var = tk.StringVar(value="" if default is None else str(default))
            self._vars[key] = var
            if kind == "combo":
                widget = ttk.Combobox(self, textvariable=var, values=options, state="readonly", width=28)
            elif kind == "date":
                # options="future" blocks past days in the calendar (e.g. expiry dates).
                widget = DatePickerEntry(self, textvariable=var, width=26,
                                         min_date=date.today() if options == "future" else None)
            elif kind == "readonly":
                widget = ttk.Entry(self, textvariable=var, state="readonly", width=30)
            else:
                widget = ttk.Entry(self, textvariable=var, show="•" if kind == "password" else "", width=30)
            widget.grid(row=row, column=pair * 2 + 1, sticky="ew", pady=(10, 0))
            first = first or widget
        row = start + per_column
        self.error = ttk.Label(self, text="", style="Error.TLabel", wraplength=width, justify="left")
        self.error.grid(row=row, column=0, columnspan=span, sticky="w", pady=(10, 0))
        buttons = ttk.Frame(self, style="Card.TFrame")
        buttons.grid(row=row + 1, column=0, columnspan=span, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(8, 0))
        self.submit_button = ttk.Button(buttons, text=submit_text, style="Primary.TButton", command=self.submit)
        self.submit_button.pack(side="right")
        self.bind("<Return>", lambda _e: self.submit())
        self.bind("<Escape>", lambda _e: self.destroy())
        center_on_main(self)
        self._grab()
        if first:
            first.focus_set()

    def _grab(self, tries=20):
        """Make the dialog modal; a just-shown window may not be viewable yet, so retry briefly."""
        try:
            self.grab_set()
        except tk.TclError:
            if tries and self.winfo_exists():
                self.after(50, lambda: self._grab(tries - 1))

    def submit(self):
        values = {key: var.get().strip() for key, var in self._vars.items()}
        try:
            self._on_submit(values)
        except ServiceError as error:
            self.error.configure(text=str(error))
            return
        except Exception as error:  # noqa: BLE001 - never fail silently in the windowed exe
            self.error.configure(text=f"Could not save: {error}")
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


class ScrollFrame(ttk.Frame):
    """Vertically scrollable area: put content in `.inner`. The scrollbar appears only when needed and the
    mouse wheel scrolls while the pointer is over the area."""

    def __init__(self, parent, **kwargs):
        super().__init__(parent, **kwargs)
        self.canvas = tk.Canvas(self, background=theme.BG, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", lambda _e: self._update())
        self.canvas.bind("<Configure>", self._resize)
        self.bind("<Enter>", lambda _e: self.bind_all("<MouseWheel>", self._wheel))
        self.bind("<Leave>", self._leave)

    def _leave(self, _event):
        # <Leave> also fires when the pointer moves onto a child widget; only stop when truly outside.
        x, y = self.winfo_pointerxy()
        inside = self.winfo_containing(x, y)
        if inside is None or not str(inside).startswith(str(self)):
            self.unbind_all("<MouseWheel>")

    def _resize(self, event):
        self.canvas.itemconfigure(self._window, width=event.width)
        self._update()

    def _update(self):
        self.canvas.configure(scrollregion=(0, 0, self.inner.winfo_reqwidth(), self.inner.winfo_reqheight()))
        needed = self.inner.winfo_reqheight() > self.canvas.winfo_height() > 1
        if needed and not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y", before=self.canvas)
        elif not needed and self.scrollbar.winfo_ismapped():
            self.scrollbar.pack_forget()
            self.canvas.yview_moveto(0)

    def _wheel(self, event):
        if self.scrollbar.winfo_ismapped():
            self.canvas.yview_scroll(int(-event.delta / 120), "units")


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
