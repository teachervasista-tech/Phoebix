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
if FROZEN:
    localappdata = os.environ.get("LOCALAPPDATA", "")
    if localappdata:
        APP_DIR = Path(localappdata) / "Phoebix"
    else:
        APP_DIR = Path.home() / "AppData" / "Local" / "Phoebix"
else:
    APP_DIR = ROOT
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


def init_database():
    """Initialize database with schema and bootstrap data."""
    from phx.data.database import Database
    from phx.services.bootstrap import bootstrap

    # Diagnose path resolution
    debug_info = []
    debug_info.append(f"FROZEN: {FROZEN}")
    debug_info.append(f"ROOT: {ROOT}")
    debug_info.append(f"LOCALAPPDATA env: {os.environ.get('LOCALAPPDATA', '<not set>')}")
    debug_info.append(f"APP_DIR: {APP_DIR}")

    db_path_str = os.environ.get("PHOEBIX_DB_PATH")
    if db_path_str:
        database_path = Path(db_path_str)
        debug_info.append(f"Using PHOEBIX_DB_PATH: {db_path_str}")
    else:
        database_path = APP_DIR / "data" / "phoebix_desktop.sqlite3"
        debug_info.append(f"Using default path: {database_path}")

    database_path = database_path.resolve()
    debug_info.append(f"Resolved path: {database_path}")

    # Check if database should be reset
    reset_db = os.environ.get("PHOEBIX_RESET_DB", "").lower() in ("1", "true", "yes")
    if reset_db and database_path.exists():
        try:
            database_path.unlink()
            debug_info.append(f"Reset: Deleted existing database")
            # Also delete WAL files
            for wal_file in database_path.parent.glob(f"{database_path.name}-*"):
                wal_file.unlink()
        except Exception as error:
            debug_info.append(f"Reset: Failed to delete database: {error}")

    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        debug_info.append(f"Directory created/verified: {database_path.parent}")
    except Exception as error:
        debug_msg = "\n".join(debug_info)
        raise RuntimeError(f"Could not create database directory:\n{debug_msg}\n\nError: {error}") from error

    # Find sample_state.json: first try bundled location, then next to exe
    sample_data_path = ROOT / "sample_state.json"
    if not sample_data_path.exists() and FROZEN:
        sample_data_path = Path(sys.executable).parent / "sample_state.json"

    try:
        # Database __init__ creates schema if needed
        db = Database(database_path)

        # Bootstrap default users and sample data on first run
        bootstrap(db, sample_data_path)

        # Verify database integrity
        if not db.integrity_ok():
            raise RuntimeError(f"Database {database_path} failed integrity check.")

        return db
    except Exception as error:
        raise RuntimeError(f"Database initialization failed at {database_path}: {error}") from error


def main():
    load_environment_file()

    guard = acquire_single_instance()
    if guard is None:
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo("Phoebix", "Phoebix is already open on this computer.")
        return 0

    try:
        # Initialize database BEFORE importing UI components
        database = init_database()
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Phoebix could not start",
            f"The database could not be initialized.\n\n{error}"
        )
        return 1

    try:
        from phx.services.container import Services
        from phx.ui.app import PhoebixApp

        # Find sample_state.json: first try bundled location, then next to exe
        sample_data_path = ROOT / "sample_state.json"
        if not sample_data_path.exists() and FROZEN:
            sample_data_path = Path(sys.executable).parent / "sample_state.json"

        services = Services(database, sample_data_path)
        PhoebixApp(services).mainloop()
        return 0
    except Exception as error:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(
            "Phoebix could not start",
            f"An error occurred while starting the application.\n\n{error}"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
