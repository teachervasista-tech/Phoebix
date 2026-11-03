"""Sign-in, password change and user administration."""
import time
from datetime import datetime, timezone

from ..data.database import DataError
from ..domain import rules
from ..domain.security import DUMMY_HASH, hash_password, verify_password
from .core import AuthError, ServiceError

MAX_FAILURES = 5
LOCK_SECONDS = 60


def public_user(user):
    return {k: v for k, v in user.items() if k != "passwordHash"}


class AuthService:
    def __init__(self, db, session):
        self.db, self.session = db, session
        self._failures = {}

    def login(self, username, password):
        key = (username or "").strip().lower()
        failures, locked_until = self._failures.get(key, (0, 0))
        if locked_until > time.time():
            raise AuthError(f"Too many failed attempts. Try again in {int(locked_until - time.time()) + 1} seconds.")
        with self.db.unit_of_work() as repos:
            user = repos.users.by_username(key)
        valid = verify_password(password or "", user["passwordHash"] if user else DUMMY_HASH)
        if not (user and valid and user["active"]):
            failures += 1
            self._failures[key] = (0, time.time() + LOCK_SECONDS) if failures >= MAX_FAILURES else (failures, 0)
            raise AuthError("Incorrect username or password.")
        self._failures.pop(key, None)
        self.session.user = public_user(user)
        return self.session.user

    def logout(self):
        self.session.user = None

    def change_password(self, current, new):
        user = self.session.require_user()
        rules.validate_password(new)
        if current == new:
            raise ServiceError("Choose a new password that is different from the current one.")
        with self.db.unit_of_work(write=True) as repos:
            row = repos.users.get(user["id"])
            if not verify_password(current or "", row["passwordHash"]):
                raise AuthError("Current password is incorrect.")
            repos.users.update(row["id"], row["name"], row["role"], row["active"], hash_password(new), False)
            self.session.user = public_user(repos.users.get(row["id"]))
        return self.session.user


class UserService:
    def __init__(self, db, session):
        self.db, self.session = db, session

    def list(self):
        self.session.require_admin()
        with self.db.unit_of_work() as repos:
            return [public_user(u) for u in repos.users.all()]

    def create(self, username, name, role, password):
        self.session.require_admin()
        username = rules.clean_text(username, "Username", 32).lower()
        if not rules.USERNAME_PATTERN.match(username):
            raise ServiceError("Username must be 3-32 characters: letters, digits, dot, dash or underscore.")
        name = rules.clean_text(name, "Name", 80)
        if not name:
            raise ServiceError("Enter the user's full name.")
        if role not in ("admin", "staff"):
            raise ServiceError("Role must be admin or staff.")
        rules.validate_password(password)
        with self.db.unit_of_work(write=True) as repos:
            try:
                user_id = repos.users.add(username, name, role, hash_password(password), True, _now())
            except DataError as error:
                raise ServiceError(str(error)) from error
            return public_user(repos.users.get(user_id))

    def update(self, user_id, name, role, active, new_password=None):
        acting = self.session.require_admin()
        name = rules.clean_text(name, "Name", 80)
        if not name:
            raise ServiceError("Enter the user's full name.")
        if role not in ("admin", "staff"):
            raise ServiceError("Role must be admin or staff.")
        if user_id == acting["id"] and (role != "admin" or not active):
            raise ServiceError("You cannot remove your own administrator access or deactivate your own account.")
        with self.db.unit_of_work(write=True) as repos:
            row = repos.users.get(user_id)
            if row is None:
                raise ServiceError("User not found.")
            password_hash, must_change = row["passwordHash"], row["mustChangePassword"]
            if new_password:
                rules.validate_password(new_password)
                password_hash, must_change = hash_password(new_password), True
            repos.users.update(user_id, name, role, active, password_hash, must_change)
            if repos.users.active_admin_count() == 0:
                raise ServiceError("At least one active administrator is required.")
            return public_user(repos.users.get(user_id))


def _now():
    return datetime.now(timezone.utc).isoformat()
