"""Low-level SQLite file operations for backup and restore (the data layer owns sqlite3)."""
import sqlite3
from contextlib import closing


class BackupFileError(Exception):
    """The file is not a usable Phoebix database."""


def snapshot(db_path, dest_path):
    """Consistent hot copy of a live database, including anything still in its WAL file."""
    with closing(sqlite3.connect(db_path, timeout=15)) as src, closing(sqlite3.connect(dest_path)) as dst:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")  # self-contained single file, no -wal/-shm


def inspect(path):
    """Validate a database file as an intact Phoebix database, else raise BackupFileError."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupFileError("The backup file is damaged (integrity check failed).")
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"products", "batches", "sales", "settings", "users"} <= tables:
                raise BackupFileError("This file is not a Phoebix database backup.")
    except sqlite3.DatabaseError as error:
        raise BackupFileError(f"This file is not a readable database: {error}") from error


def install(src_path, db_path):
    """Overwrite the live database's contents with src (page-level copy through SQLite, WAL-safe)."""
    with closing(sqlite3.connect(src_path)) as src, closing(sqlite3.connect(db_path, timeout=15)) as dst:
        src.backup(dst)
