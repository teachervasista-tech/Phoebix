"""Phoebix desktop entry point and composition root.

This is the only module that knows about every layer: it prepares the data location, builds the
services on top of the data layer, and hands them to the UI.
"""
import ctypes
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox

FROZEN = getattr(sys, "frozen", False)
# ROOT holds bundled read-only files; APP_DIR holds the user's database and .env.
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Phoebix" if FROZEN else ROOT
sys.path.insert(0, str(ROOT))


def load_environment_file():
    env_path = APP_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def acquire_single_instance():
    """Keep a second copy from opening the same database. Returns a handle to hold, or None if taken."""
    if os.name != "nt":
        return object()
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PhoebixDesktopApp")
    return None if ctypes.windll.kernel32.GetLastError() == 183 else handle


def main():
    load_environment_file()
    from phx.services.container import Services
    from phx.ui.app import PhoebixApp

    guard = acquire_single_instance()
    if guard is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Phoebix", "Phoebix is already open on this computer.")
        return 0
    database = Path(os.environ.get("PHOEBIX_DB_PATH", APP_DIR / "data" / "phoebix_desktop.sqlite3")).expanduser()
    database.parent.mkdir(parents=True, exist_ok=True)
    try:
        services = Services(database, ROOT / "sample_state.json")
        if not services.db.integrity_ok():
            raise RuntimeError(f"The database file {database} failed its integrity check.")
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Phoebix could not start", f"The database could not be opened.\n\n{error}")
        return 1
    PhoebixApp(services).mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
