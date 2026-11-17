"""Backups: local zipped snapshots plus an optional copy into a cloud-synced folder.

Cloud upload is delegated to the Google Drive / OneDrive desktop app: Phoebix copies each backup into a
folder that app syncs, so no cloud credentials are stored here.
"""
import os
import re
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from ..data import backup_store
from ..data.backup_store import BackupFileError
from .core import ServiceError

PREFIX = "Phoebix-"
NAME_PATTERN = re.compile(r"^Phoebix-\d{8}-\d{6}-[a-z0-9-]+\.zip$")
DB_MEMBER = "phoebix.sqlite3"
DEFAULT_KEEP = 30
AUTO_INTERVAL = timedelta(hours=24)
WARN_AFTER = timedelta(days=3)
DEFAULT_SETTINGS = {"localDir": "", "cloudDir": "", "keep": DEFAULT_KEEP, "auto": True,
                    "lastRun": "", "lastOk": "", "lastStatus": "", "lastFile": ""}


def _now():
    return datetime.now().replace(microsecond=0)


def _clean_reason(reason):
    return re.sub(r"[^a-z0-9-]+", "-", (reason or "manual").lower()).strip("-")[:24] or "manual"


def write_backup(db_path, folder, reason):
    """Snapshot db_path into folder as a verified zip; returns the zip path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    target = folder / f"{PREFIX}{stamp}-{_clean_reason(reason)}.zip"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{PREFIX}{stamp}-{_clean_reason(reason)}-{n}.zip"
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        raw = Path(tmp) / DB_MEMBER
        backup_store.snapshot(db_path, str(raw))
        backup_store.inspect(str(raw))
        partial = target.with_suffix(".part")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(raw, DB_MEMBER)
        os.replace(partial, target)
    return target


def prune(folder, keep):
    """Delete the oldest Phoebix backups in folder beyond `keep`; never touches other files."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    # Oldest first by modification time (names alone mis-order same-second "-2" suffixes).
    ours = sorted((p for p in folder.iterdir() if p.is_file() and NAME_PATTERN.match(p.name)),
                  key=lambda p: (p.stat().st_mtime_ns, p.name))
    doomed = ours[:-keep] if keep > 0 else []
    for path in doomed:
        try:
            path.unlink()
        except OSError:
            pass
    return doomed


def cloud_folder_suggestions():
    """Likely cloud-synced folders on this PC (OneDrive / Google Drive desktop)."""
    candidates = [os.environ.get(k) for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    home = Path.home()
    candidates += [str(home / "Google Drive"), str(home / "My Drive"), "G:\\My Drive"]
    seen, result = set(), []
    for c in candidates:
        if c and c not in seen and Path(c).is_dir():
            seen.add(c)
            result.append(str(Path(c) / "Phoebix Backups"))
    return result


def backup_warning(settings, now=None):
    """Dashboard text when backups look neglected, else None."""
    now = now or _now()
    last_ok = settings.get("lastOk")
    if not last_ok:
        return "No backup has been taken yet"
    try:
        age = now - datetime.fromisoformat(last_ok)
    except ValueError:
        return None
    if age > WARN_AFTER:
        return f"Last backup {age.days} days ago"
    if settings.get("lastStatus", "").startswith("Cloud copy failed"):
        return "Cloud backup copy failing"
    return None


class BackupService:
    def __init__(self, db, session, default_dir):
        self.db, self.session = db, session
        self.default_dir = Path(default_dir)
        self._lock = threading.Lock()

    # ---- settings ------------------------------------------------------
    def settings(self):
        with self.db.unit_of_work() as repos:
            s = repos.settings.get("backup", DEFAULT_SETTINGS)
        s["effectiveLocalDir"] = s["localDir"] or str(self.default_dir)
        return s

    def save_settings(self, data):
        self.session.require_admin()
        local_dir = (data.get("localDir") or "").strip()
        cloud_dir = (data.get("cloudDir") or "").strip()
        try:
            keep = int(data.get("keep") or DEFAULT_KEEP)
        except (TypeError, ValueError):
            raise ServiceError("Number of backups to keep must be a whole number.") from None
        if not 3 <= keep <= 365:
            raise ServiceError("Keep between 3 and 365 backups.")
        for label, folder in (("Backup folder", local_dir), ("Cloud folder", cloud_dir)):
            if folder and not Path(folder).is_absolute():
                raise ServiceError(f"{label} must be a full path, e.g. D:\\Backups.")
        if local_dir and cloud_dir and Path(local_dir).resolve() == Path(cloud_dir).resolve():
            raise ServiceError("Choose a different cloud folder from the local backup folder.")
        auto = data.get("auto")
        auto = auto if isinstance(auto, bool) else str(auto).lower() in ("1", "true", "yes", "on")
        with self.db.unit_of_work(write=True) as repos:
            current = repos.settings.get("backup", DEFAULT_SETTINGS)
            current.update(localDir=local_dir, cloudDir=cloud_dir, keep=keep, auto=auto)
            repos.settings.put("backup", current)
        return self.settings()

    def _record(self, **fields):
        with self.db.unit_of_work(write=True) as repos:
            current = repos.settings.get("backup", DEFAULT_SETTINGS)
            current.update(fields)
            repos.settings.put("backup", current)

    # ---- backup --------------------------------------------------------
    def backup_now(self, reason="manual"):
        """Manual backup from the UI (admin only)."""
        self.session.require_admin()
        return self.run(reason)

    def run(self, reason):
        """Take a backup. Local failure raises; a cloud-copy failure is reported in the result."""
        with self._lock:
            s = self.settings()
            local_dir = Path(s["effectiveLocalDir"])
            started = _now().isoformat()
            try:
                path = write_backup(self.db.path, local_dir, reason)
            except (OSError, BackupFileError) as error:
                self._record(lastRun=started, lastStatus=f"Failed: {error}")
                raise ServiceError(f"Backup failed: {error}") from error
            cloud_path, cloud_error = None, None
            if s["cloudDir"]:
                cloud = Path(s["cloudDir"])
                try:
                    if not cloud.parent.is_dir():
                        raise OSError(f"{cloud.parent} is not available (is the Drive/OneDrive app running?)")
                    cloud.mkdir(exist_ok=True)
                    cloud_path = Path(shutil.copy2(path, cloud / path.name))
                    prune(cloud, s["keep"])
                except OSError as error:
                    cloud_error = str(error)
            prune(local_dir, s["keep"])
            status = "OK" if not s["cloudDir"] else (
                "OK · copied to cloud folder" if cloud_path else f"Cloud copy failed: {cloud_error}")
            self._record(lastRun=started, lastOk=started, lastStatus=status, lastFile=str(path))
            return {"file": str(path), "cloudFile": str(cloud_path) if cloud_path else None,
                    "cloudError": cloud_error, "status": status}

    def auto_backup(self, reason, force=False):
        """Startup/close hook: back up if enabled and due. Never raises."""
        try:
            s = self.settings()
            if not s.get("auto", True):
                return None
            if not force and s.get("lastOk"):
                try:
                    if _now() - datetime.fromisoformat(s["lastOk"]) < AUTO_INTERVAL:
                        return None
                except ValueError:
                    pass
            return self.run(reason)
        except Exception:  # noqa: BLE001 - background safety net; status is recorded by run()
            return None

    def auto_backup_async(self, reason):
        thread = threading.Thread(target=self.auto_backup, args=(reason,), daemon=True)
        thread.start()
        return thread

    def list_backups(self):
        s = self.settings()
        found = []
        for where, folder in (("Local", s["effectiveLocalDir"]), ("Cloud", s["cloudDir"])):
            if folder and Path(folder).is_dir():
                for p in Path(folder).iterdir():
                    if p.is_file() and NAME_PATTERN.match(p.name):
                        found.append({"name": p.name, "path": str(p), "where": where,
                                      "size": p.stat().st_size,
                                      "modified": datetime.fromtimestamp(p.stat().st_mtime).replace(microsecond=0).isoformat()})
        return sorted(found, key=lambda b: (b["modified"], b["name"]), reverse=True)

    @staticmethod
    def cloud_suggestions():
        return cloud_folder_suggestions()

    def warning(self):
        return backup_warning(self.settings())

    # ---- restore -------------------------------------------------------
    def restore(self, path):
        """Replace all data with a backup. A safety backup of the current data is taken first.

        The app must be restarted afterwards (the restored file may need a schema upgrade)."""
        self.session.require_admin()
        path = Path(path)
        if not path.is_file():
            raise ServiceError("Backup file not found.")
        with self._lock, tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / DB_MEMBER
            try:
                if path.suffix.lower() == ".zip":
                    with zipfile.ZipFile(path) as zf:
                        if DB_MEMBER not in zf.namelist():
                            raise ServiceError("This zip is not a Phoebix backup.")
                        with zf.open(DB_MEMBER) as src, open(raw, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                else:
                    shutil.copy2(path, raw)
                backup_store.inspect(str(raw))
            except zipfile.BadZipFile as error:
                raise ServiceError("The backup zip is damaged.") from error
            except BackupFileError as error:
                raise ServiceError(str(error)) from error
            try:
                safety = write_backup(self.db.path, self.settings()["effectiveLocalDir"], "pre-restore")
            except (OSError, BackupFileError) as error:
                raise ServiceError(f"Could not back up current data before restoring: {error}") from error
            backup_store.install(str(raw), self.db.path)
        return {"safetyBackup": str(safety)}
