"""Look and feel plus small formatting helpers."""
import tkinter as tk
from tkinter import ttk

INK, MUTED, LINE = "#202b35", "#87919c", "#e9edf0"
GREEN, GREEN_LIGHT, CORAL, ORANGE = "#287b68", "#e9f4f0", "#df7f69", "#ce904a"
BG, CARD = "#f7f8fa", "#ffffff"
FONT = "Segoe UI"


def inr(value):
    """Rupee amount with Indian digit grouping (12,34,567.50)."""
    negative = value < 0
    whole, frac = f"{abs(value):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if negative else ''}₹{whole}.{frac}"


def inr0(value):
    text = inr(value)
    return text[:-3] if text.endswith(".00") else text


def apply_theme(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(background=BG)
    from tkinter import font as tkfont
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=FONT, size=10)
    style.configure(".", background=BG, foreground=INK, font=(FONT, 10), bordercolor=LINE)
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD, relief="solid", borderwidth=1, bordercolor=LINE)
    style.configure("Side.TFrame", background="#fdfdfd")
    style.configure("TLabel", background=BG, foreground=INK)
    style.configure("Card.TLabel", background=CARD)
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED)
    style.configure("H1.TLabel", font=(FONT, 20, "bold"))
    style.configure("H2.TLabel", font=(FONT, 13, "bold"))
    style.configure("CardH2.TLabel", background=CARD, font=(FONT, 13, "bold"))
    style.configure("Stat.TLabel", background=CARD, font=(FONT, 20, "bold"))
    style.configure("Good.TLabel", foreground=GREEN, background=CARD)
    style.configure("Bad.TLabel", foreground="#c0392b", background=CARD)
    style.configure("Error.TLabel", foreground="#c0392b")
    style.configure("Brand.TLabel", background="#fdfdfd", font=(FONT, 18, "bold"), foreground=INK)
    style.configure("Side.TLabel", background="#fdfdfd", foreground=MUTED, font=(FONT, 9))
    style.configure("TButton", padding=(12, 7), background="#ffffff", borderwidth=1, relief="solid")
    style.map("TButton", background=[("active", GREEN_LIGHT)])
    style.configure("Primary.TButton", background=GREEN, foreground="#ffffff", bordercolor=GREEN)
    style.map("Primary.TButton", background=[("active", "#216a59"), ("disabled", "#9bc3b8")])
    style.configure("Nav.TButton", background="#fdfdfd", anchor="w", padding=(14, 10), borderwidth=0, font=(FONT, 10))
    style.map("Nav.TButton", background=[("active", GREEN_LIGHT)])
    style.configure("NavActive.TButton", background=GREEN_LIGHT, foreground=GREEN, anchor="w", padding=(14, 10),
                    borderwidth=0, font=(FONT, 10, "bold"))
    style.configure("TEntry", padding=6, fieldbackground="#ffffff")
    style.configure("TCombobox", padding=6, fieldbackground="#ffffff")
    style.configure("Treeview", background=CARD, fieldbackground=CARD, rowheight=28, borderwidth=0)
    style.configure("Treeview.Heading", background="#f1f4f6", foreground=MUTED, font=(FONT, 9, "bold"), padding=6)
    style.map("Treeview", background=[("selected", GREEN_LIGHT)], foreground=[("selected", INK)])
    style.configure("TCheckbutton", background=CARD)
    return style


def card(parent, **kwargs):
    return ttk.Frame(parent, style="Card.TFrame", padding=kwargs.pop("padding", 16), **kwargs)


class DataTable(ttk.Frame):
    """Treeview with a scrollbar. columns = [(key, heading, width, anchor)]."""

    def __init__(self, parent, columns, height=10, on_select=None, on_double=None):
        super().__init__(parent, style="Card.TFrame")
        self.columns = columns
        self.tree = ttk.Treeview(self, columns=[c[0] for c in columns], show="headings", height=height,
                                 selectmode="browse")
        for key, heading, width, anchor in columns:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor=anchor, stretch=True)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("warn", foreground=CORAL)
        self.tree.tag_configure("muted", foreground=MUTED)
        if on_select:
            self.tree.bind("<<TreeviewSelect>>", lambda _e: on_select(self.selected()))
        if on_double:
            self.tree.bind("<Double-1>", lambda _e: on_double(self.selected()))

    def set_rows(self, rows):
        """rows = [(iid, values, tag or None)]."""
        keep = self.selected()
        self.tree.delete(*self.tree.get_children())
        for iid, values, tag in rows:
            self.tree.insert("", "end", iid=str(iid), values=values, tags=(tag,) if tag else ())
        if keep and self.tree.exists(keep):
            self.tree.selection_set(keep)

    def selected(self):
        selection = self.tree.selection()
        return selection[0] if selection else None
