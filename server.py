import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


FROZEN = getattr(sys, "frozen", False)
# ROOT holds the bundled app files; APP_DIR holds the user's data and .env (writable, survives upgrades).
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Phoebix" if FROZEN else ROOT


def load_environment_file():
    env_path = APP_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        key = key.strip()
        if separator and key and not key.startswith("#"):
            os.environ.setdefault(key, value.strip().strip("\"'"))


load_environment_file()
DATABASE = Path(os.environ.get("PHOEBIX_DB_PATH", APP_DIR / "data" / "phoebix.sqlite3")).expanduser()
PUBLIC_FILES = {"/", "/index.html", "/styles.css", "/app.js", "/icon.svg"}
if not DATABASE.is_absolute():
    DATABASE = APP_DIR / DATABASE
MAX_REQUEST_BYTES = 8 * 1024 * 1024
COLLECTIONS = ("products", "customers", "transactions", "offers")
SAMPLE_STATE_PATH = ROOT / "sample_state.json"
PHONEPE_TOKEN = None
PHONEPE_TOKEN_EXPIRES = 0


class PaymentGatewayError(Exception):
    pass


def phonepe_config():
    environment = os.environ.get("PHONEPE_ENV", "sandbox").lower()
    if environment not in ("sandbox", "production"):
        raise ValueError("PHONEPE_ENV must be 'sandbox' or 'production'.")
    values = {
        "client_id": os.environ.get("PHONEPE_CLIENT_ID", ""),
        "client_secret": os.environ.get("PHONEPE_CLIENT_SECRET", ""),
        "client_version": os.environ.get("PHONEPE_CLIENT_VERSION", ""),
    }
    configured = all(values.values())
    if environment == "sandbox":
        api_base = "https://api-preprod.phonepe.com/apis/pg-sandbox"
        token_url = f"{api_base}/v1/oauth/token"
    else:
        api_base = "https://api.phonepe.com/apis/pg"
        token_url = "https://api.phonepe.com/apis/identity-manager/v1/oauth/token"
    return {**values, "environment": environment, "api_base": api_base, "token_url": token_url, "configured": configured}


def phonepe_request(url, method="GET", headers=None, body=None):
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        try:
            details = json.loads(response_body)
            message = details.get("message") or details.get("code") or f"HTTP {error.code}"
        except (json.JSONDecodeError, AttributeError):
            message = f"HTTP {error.code}"
        raise PaymentGatewayError(f"PhonePe request failed: {message}") from error
    except (urllib.error.URLError, TimeoutError) as error:
        raise PaymentGatewayError("PhonePe could not be reached. Check the internet connection and try again.") from error
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise PaymentGatewayError("PhonePe returned an invalid response.") from error
    if not isinstance(result, dict):
        raise PaymentGatewayError("PhonePe returned an unexpected response.")
    return result


def phonepe_access_token():
    global PHONEPE_TOKEN, PHONEPE_TOKEN_EXPIRES
    config = phonepe_config()
    if not config["configured"]:
        raise PaymentGatewayError("PhonePe is not configured. Add the sandbox credentials to the .env file and restart Phoebix.")
    if PHONEPE_TOKEN and time.time() < PHONEPE_TOKEN_EXPIRES:
        return PHONEPE_TOKEN
    body = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "client_version": config["client_version"],
        "grant_type": "client_credentials",
    }).encode("ascii")
    response = phonepe_request(
        config["token_url"],
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=body,
    )
    token = response.get("access_token")
    if not isinstance(token, str) or not token:
        raise PaymentGatewayError("PhonePe did not return an authorization token.")
    PHONEPE_TOKEN = token
    expires_at = response.get("expires_at")
    PHONEPE_TOKEN_EXPIRES = float(expires_at) - 60 if isinstance(expires_at, (int, float)) else time.time() + 300
    return PHONEPE_TOKEN


def phonepe_api_request(path, method="GET", payload=None):
    config = phonepe_config()
    headers = {"Authorization": f"O-Bearer {phonepe_access_token()}", "Content-Type": "application/json"}
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    return phonepe_request(f"{config['api_base']}{path}", method=method, headers=headers, body=body)


def connect(database=DATABASE):
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def load_sample_state():
    state = json.loads(SAMPLE_STATE_PATH.read_text(encoding="utf-8"))
    today = date.today()
    for product in state["products"]:
        product["expiry"] = (today + timedelta(days=int(product["expiry"].split(":")[1]))).isoformat()
    for transaction in state["transactions"]:
        transaction["date"] = (today + timedelta(days=int(transaction["date"].split(":")[1]))).isoformat()
    return state


def initialize_database(database=DATABASE, seed=True):
    with closing(connect(database)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """CREATE TABLE IF NOT EXISTS app_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                store_json TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        for collection in COLLECTIONS:
            connection.execute(
                f"""CREATE TABLE IF NOT EXISTS {collection} (
                    id TEXT PRIMARY KEY,
                    position INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                )"""
            )
            connection.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{collection}_position ON {collection}(position)"
            )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS phonepe_payments (
                merchant_order_id TEXT PRIMARY KEY,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL,
                intent_json TEXT NOT NULL,
                provider_order_id TEXT NOT NULL,
                transaction_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'staff')),
                password_hash TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            )"""
        )
        connection.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            )"""
        )
        if seed:
            seed_users(connection)
        connection.commit()
    if seed and read_state(database)["state"] is None:
        save_state(load_sample_state(), expected_revision=0, database=database)


def read_state(database=DATABASE):
    with closing(connect(database)) as connection:
        return read_state_from_connection(connection)


def read_state_from_connection(connection):
    metadata = connection.execute(
        "SELECT store_json, rules_json, revision, updated_at FROM app_state WHERE id = 1"
    ).fetchone()
    if metadata is None:
        return {"state": None, "revision": 0, "updatedAt": None}

    state = {
        "store": json.loads(metadata["store_json"]),
        "rules": json.loads(metadata["rules_json"]),
    }
    for collection in COLLECTIONS:
        rows = connection.execute(
            f"SELECT payload_json FROM {collection} ORDER BY position"
        ).fetchall()
        state[collection] = [json.loads(row["payload_json"]) for row in rows]

    return {
        "state": state,
        "revision": metadata["revision"],
        "updatedAt": metadata["updated_at"],
    }


def validate_state(state):
    if not isinstance(state, dict):
        raise ValueError("state must be an object")
    if not isinstance(state.get("store"), dict) or not isinstance(state.get("rules"), dict):
        raise ValueError("state must include store and rules objects")
    for collection in COLLECTIONS:
        entries = state.get(collection)
        if not isinstance(entries, list):
            raise ValueError(f"{collection} must be an array")
        identifiers = []
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not entry["id"].strip():
                raise ValueError(f"every {collection} record must have a non-empty string id")
            identifiers.append(entry["id"])
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"{collection} record ids must be unique")
    try:
        json.dumps(state, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ValueError("state must contain valid JSON values") from error


class StateConflict(Exception):
    def __init__(self, revision):
        super().__init__("The database changed since this client last loaded it.")
        self.revision = revision


def save_state(state, expected_revision, database=DATABASE, user=None):
    validate_state(state)
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expectedRevision must be a non-negative integer")

    connection = connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        result = write_state_in_transaction(connection, state, expected_revision, user)
        connection.commit()
        return result
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def sold_by(user):
    return {"userId": user["id"], "username": user["username"], "name": user["name"]}


def stamp_sales(connection, state, user):
    # The sale owner is decided here, never by the client: new sales get the signed-in user,
    # existing sales keep the owner already stored in the database.
    existing = {
        row["id"]: json.loads(row["payload_json"]).get("soldBy")
        for row in connection.execute("SELECT id, payload_json FROM transactions")
    }
    for transaction in state["transactions"]:
        if transaction["id"] in existing:
            owner = existing[transaction["id"]]
            if owner:
                transaction["soldBy"] = owner
            else:
                transaction.pop("soldBy", None)
        else:
            transaction["soldBy"] = sold_by(user)


BANK_FIELDS = ("accountHolder", "bankName", "branch", "accountNumber", "ifsc", "accountType", "upiId")


def clean_bank_details(bank):
    if bank is None:
        bank = {}
    if not isinstance(bank, dict):
        raise ValueError("Bank details must be an object")
    cleaned = {}
    for field in BANK_FIELDS:
        value = bank.get(field, "")
        if not isinstance(value, str):
            raise ValueError(f"Bank detail {field} must be text")
        cleaned[field] = value.strip()[:100]
    cleaned["ifsc"] = cleaned["ifsc"].upper()
    cleaned["accountNumber"] = re.sub(r"\s+", "", cleaned["accountNumber"])
    if cleaned["accountNumber"] and not re.fullmatch(r"\d{9,18}", cleaned["accountNumber"]):
        raise ValueError("Account number must be 9 to 18 digits")
    if cleaned["ifsc"] and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", cleaned["ifsc"]):
        raise ValueError("IFSC must be 11 characters, e.g. HDFC0001234")
    if cleaned["upiId"] and not re.fullmatch(r"[A-Za-z0-9.\-_]{2,64}@[A-Za-z0-9]{2,64}", cleaned["upiId"]):
        raise ValueError("Enter a valid UPI ID, e.g. pharmacy@okhdfcbank")
    if cleaned["accountType"] not in ("", "Current", "Savings", "Overdraft / Cash credit"):
        raise ValueError("Choose a valid account type")
    return cleaned


def protect_bank_details(connection, state, user):
    # The payee account is the one setting worth stealing, so only administrators may change it.
    state["store"]["bank"] = clean_bank_details(state["store"].get("bank"))
    row = connection.execute("SELECT store_json FROM app_state WHERE id = 1").fetchone()
    current = json.loads(row["store_json"]).get("bank") if row else None
    current = {field: (current or {}).get(field, "") for field in BANK_FIELDS}
    if state["store"]["bank"] != current and user["role"] != "admin":
        raise AuthError("Only an administrator can change the bank details.", 403)


def write_state_in_transaction(connection, state, expected_revision, user=None):
    if user is not None:
        stamp_sales(connection, state, user)
        protect_bank_details(connection, state, user)
    encoded = {
        "store": json.dumps(state["store"], ensure_ascii=False, allow_nan=False),
        "rules": json.dumps(state["rules"], ensure_ascii=False, allow_nan=False),
    }
    collection_rows = {
        collection: [
            (
                entry["id"],
                position,
                json.dumps(entry, ensure_ascii=False, allow_nan=False),
            )
            for position, entry in enumerate(state[collection])
        ]
        for collection in COLLECTIONS
    }

    row = connection.execute(
        "SELECT revision FROM app_state WHERE id = 1"
    ).fetchone()
    current_revision = row["revision"] if row else 0
    if expected_revision != current_revision:
        raise StateConflict(current_revision)

    revision = current_revision + 1
    updated_at = datetime.now(timezone.utc).isoformat()
    connection.execute(
        """INSERT INTO app_state (id, store_json, rules_json, revision, updated_at)
           VALUES (1, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
               store_json = excluded.store_json,
               rules_json = excluded.rules_json,
               revision = excluded.revision,
               updated_at = excluded.updated_at""",
        (encoded["store"], encoded["rules"], revision, updated_at),
    )
    for collection in COLLECTIONS:
        connection.execute(f"DELETE FROM {collection}")
        connection.executemany(
            f"INSERT INTO {collection} (id, position, payload_json) VALUES (?, ?, ?)",
            collection_rows[collection],
        )
    return {"revision": revision, "updatedAt": updated_at}


GSTIN_PATTERN = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]$")


def clean_text(value, field, limit=200):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = value.strip()
    if len(value) > limit:
        raise ValueError(f"{field} is too long")
    return value


def add_customer(payload, database=DATABASE):
    name = clean_text(payload.get("name"), "Name", 120)
    phone = clean_text(payload.get("phone"), "Mobile number", 30)
    if not name:
        raise ValueError("Enter the customer's name.")
    digits = re.sub(r"\D", "", phone)
    if not 10 <= len(digits) <= 13:
        raise ValueError("Enter a valid mobile number.")
    gstin = clean_text(payload.get("gstin"), "GSTIN", 15).upper()
    if gstin and not GSTIN_PATTERN.match(gstin):
        raise ValueError("Enter a valid 15-character GSTIN or leave the field blank.")
    expected_revision = payload.get("expectedRevision")
    if expected_revision is not None and (
        not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0
    ):
        raise ValueError("expectedRevision must be a non-negative integer")

    customer = {
        "id": f"c{secrets.token_hex(6)}",
        "name": name,
        "phone": phone,
        "email": clean_text(payload.get("email"), "Email", 120) or "—",
        "address": clean_text(payload.get("address"), "Address", 300),
        "state": clean_text(payload.get("state"), "State", 80),
        "gstin": gstin,
        "drugLicense": clean_text(payload.get("drugLicense"), "Drug licence", 60),
        "points": 0,
        "tier": "Member",
        "spent": 0,
        "visits": 0,
        "joined": datetime.now().date().isoformat(),
        "initials": "".join(part[0] for part in name.split()[:2]).upper(),
    }

    connection = connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
        if row is None:
            raise ValueError("The database is not initialized. Restart Phoebix.")
        current_revision = row["revision"]
        if expected_revision is not None and expected_revision != current_revision:
            raise StateConflict(current_revision)
        for existing in connection.execute("SELECT payload_json FROM customers"):
            existing_phone = re.sub(r"\D", "", json.loads(existing["payload_json"]).get("phone", ""))
            if existing_phone[-10:] == digits[-10:]:
                raise ValueError("A customer with this mobile number already exists.")
        position = connection.execute("SELECT COALESCE(MIN(position), 1) - 1 FROM customers").fetchone()[0]
        connection.execute(
            "INSERT INTO customers (id, position, payload_json) VALUES (?, ?, ?)",
            (customer["id"], position, json.dumps(customer, ensure_ascii=False, allow_nan=False)),
        )
        revision = current_revision + 1
        connection.execute(
            "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
            (revision, datetime.now(timezone.utc).isoformat()),
        )
        connection.commit()
        return {"customer": customer, "revision": revision}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


SESSION_COOKIE = "phoebix_session"
SESSION_SECONDS = 12 * 3600
PASSWORD_ITERATIONS = 240_000
MAX_FAILED_LOGINS = 5
LOCKOUT_SECONDS = 60
USER_ROLES = ("admin", "staff")
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
failed_logins = {}
failed_logins_lock = threading.Lock()


class AuthError(Exception):
    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


def hash_password(password, salt=None):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, iterations, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


DUMMY_PASSWORD_HASH = hash_password("phoebix-dummy-password")


def validate_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 128:
        raise ValueError("Password must be 8 to 128 characters long.")
    return password


def public_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "name": row["name"],
        "role": row["role"],
        "active": bool(row["active"]),
        "mustChangePassword": bool(row["must_change_password"]),
        "createdAt": row["created_at"],
        "lastLoginAt": row["last_login_at"],
    }


def insert_user(connection, username, name, role, password, must_change):
    connection.execute(
        """INSERT INTO users (id, username, name, role, password_hash, active, must_change_password, created_at)
           VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
        (f"u{secrets.token_hex(6)}", username, name, role, hash_password(password),
         1 if must_change else 0, datetime.now(timezone.utc).isoformat()),
    )


def seed_users(connection):
    if connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    admin_password = os.environ.get("PHOEBIX_ADMIN_PASSWORD")
    insert_user(connection, "admin", "Arjun Sharma", "admin", admin_password or "admin123", not admin_password)
    insert_user(connection, "cashier", "Priya Nair", "staff", "cashier123", True)


def login(username, password, database=DATABASE):
    if not isinstance(username, str) or not isinstance(password, str) or not username.strip():
        raise AuthError("Enter your username and password.", 400)
    key = username.strip().lower()
    now = time.time()
    with failed_logins_lock:
        _, locked_until = failed_logins.get(key, (0, 0))
        if locked_until > now:
            raise AuthError("Too many failed attempts. Try again in a minute.", 429)
    with closing(connect(database)) as connection:
        row = connection.execute("SELECT * FROM users WHERE username = ?", (key,)).fetchone()
        valid = verify_password(password, row["password_hash"] if row else DUMMY_PASSWORD_HASH) and row is not None
        if not valid or not row["active"]:
            with failed_logins_lock:
                count = failed_logins.get(key, (0, 0))[0] + 1
                failed_logins[key] = (0, now + LOCKOUT_SECONDS) if count >= MAX_FAILED_LOGINS else (count, 0)
            raise AuthError("Incorrect username or password.")
        with failed_logins_lock:
            failed_logins.pop(key, None)
        token = secrets.token_urlsafe(32)
        connection.execute("DELETE FROM sessions WHERE expires_at < ?", (int(now),))
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode()).hexdigest(), row["id"], int(now) + SESSION_SECONDS),
        )
        connection.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (datetime.now(timezone.utc).isoformat(), row["id"]))
        connection.commit()
        row = connection.execute("SELECT * FROM users WHERE id = ?", (row["id"],)).fetchone()
        return token, public_user(row)


def get_session_user(token, database=DATABASE):
    if not token:
        return None
    with closing(connect(database)) as connection:
        row = connection.execute(
            """SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id
               WHERE sessions.token_hash = ? AND sessions.expires_at > ? AND users.active = 1""",
            (hashlib.sha256(token.encode()).hexdigest(), int(time.time())),
        ).fetchone()
    return public_user(row) if row else None


def logout(token, database=DATABASE):
    if not token:
        return
    with closing(connect(database)) as connection:
        connection.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
        connection.commit()


def change_password(user_id, current_password, new_password, keep_token, database=DATABASE):
    validate_password(new_password)
    if not isinstance(current_password, str) or current_password == new_password:
        raise ValueError("Choose a new password that is different from the current one.")
    with closing(connect(database)) as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise AuthError("Current password is incorrect.", 403)
        connection.execute(
            "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        connection.execute(
            "DELETE FROM sessions WHERE user_id = ? AND token_hash != ?",
            (user_id, hashlib.sha256((keep_token or "").encode()).hexdigest()),
        )
        connection.commit()
        return public_user(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def list_users(database=DATABASE):
    with closing(connect(database)) as connection:
        return [public_user(row) for row in connection.execute("SELECT * FROM users ORDER BY created_at, username")]


def create_user(payload, database=DATABASE):
    username = clean_text(payload.get("username"), "Username", 32)
    if not USERNAME_PATTERN.match(username):
        raise ValueError("Username must be 3-32 characters: letters, digits, dot, dash or underscore.")
    name = clean_text(payload.get("name"), "Name", 80)
    if not name:
        raise ValueError("Enter the user's full name.")
    role = payload.get("role", "staff")
    if role not in USER_ROLES:
        raise ValueError("Role must be admin or staff.")
    password = validate_password(payload.get("password"))
    with closing(connect(database)) as connection:
        try:
            insert_user(connection, username.lower(), name, role, password, True)
        except sqlite3.IntegrityError as error:
            raise ValueError("That username is already taken.") from error
        connection.commit()
        return public_user(connection.execute("SELECT * FROM users WHERE username = ?", (username.lower(),)).fetchone())


def update_user(user_id, payload, acting_user, database=DATABASE):
    with closing(connect(database)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError("User not found.")
        name = clean_text(payload.get("name", row["name"]), "Name", 80)
        if not name:
            raise ValueError("Enter the user's full name.")
        role = payload.get("role", row["role"])
        if role not in USER_ROLES:
            raise ValueError("Role must be admin or staff.")
        active = payload.get("active", bool(row["active"]))
        if not isinstance(active, bool):
            raise ValueError("active must be true or false.")
        if user_id == acting_user["id"] and (role != "admin" or not active):
            raise ValueError("You cannot remove your own administrator access or deactivate your own account.")
        new_password = payload.get("newPassword")
        password_hash, must_change = row["password_hash"], row["must_change_password"]
        if new_password:
            password_hash, must_change = hash_password(validate_password(new_password)), 1
        connection.execute(
            "UPDATE users SET name = ?, role = ?, active = ?, password_hash = ?, must_change_password = ? WHERE id = ?",
            (name, role, 1 if active else 0, password_hash, must_change, user_id),
        )
        if connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0] == 0:
            raise ValueError("At least one active administrator is required.")
        if not active or new_password or role != row["role"]:
            connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        connection.commit()
        return public_user(connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def phonepe_return_url(merchant_order_id):
    base_url = os.environ.get("PHOEBIX_PUBLIC_URL", "http://127.0.0.1:4173/")
    parsed = urllib.parse.urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("PHOEBIX_PUBLIC_URL must be an absolute HTTP or HTTPS URL.")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query.extend((("phonepe", "return"), ("merchantOrderId", merchant_order_id)))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", urllib.parse.urlencode(query), ""))


def create_phonepe_payment(payload, database=DATABASE, user=None):
    config = phonepe_config()
    if not config["configured"]:
        raise PaymentGatewayError("PhonePe sandbox is not configured. Set PHONEPE_CLIENT_ID, PHONEPE_CLIENT_SECRET and PHONEPE_CLIENT_VERSION in .env, then restart Phoebix.")
    merchant_order_id = payload.get("merchantOrderId")
    if not isinstance(merchant_order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", merchant_order_id):
        raise ValueError("merchantOrderId must contain 1-63 letters, digits, underscores, or hyphens.")
    expected_revision = payload.get("expectedRevision")
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool) or expected_revision < 0:
        raise ValueError("expectedRevision must be a non-negative integer.")
    amount = payload.get("amount")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 100:
        raise ValueError("Payment amount must be at least ₹1 and provided in paise.")
    intent = payload.get("intent")
    if not isinstance(intent, dict) or not isinstance(intent.get("transaction"), dict) or not isinstance(intent.get("lines"), list) or not intent["lines"]:
        raise ValueError("Payment intent must include a transaction and at least one sale line.")
    transaction = intent["transaction"]
    if user is not None:
        intent["soldBy"] = sold_by(user)
    else:
        intent.pop("soldBy", None)
    if round(float(transaction.get("total", 0)) * 100) != amount:
        raise ValueError("Payment amount does not match the invoice total.")

    current = read_state(database)
    if current["revision"] != expected_revision:
        raise StateConflict(current["revision"])
    if any(entry.get("phonepeOrderId") == merchant_order_id for entry in current["state"]["transactions"]):
        raise ValueError("This PhonePe order has already been recorded.")
    for line in intent["lines"]:
        if not isinstance(line, dict) or not isinstance(line.get("qty"), int) or isinstance(line.get("qty"), bool) or line["qty"] < 1:
            raise ValueError("Each payment line must have a positive whole quantity.")
        product = next((entry for entry in current["state"]["products"] if entry["id"] == line.get("id")), None)
        batches = product.get("batches") if product else []
        if product and not batches:
            batches = [{"id": f"{product['id']}-batch-1", "batch": product.get("batch", ""), "expiry": product.get("expiry", ""), "stock": product.get("stock", 0)}]
        batch = next((entry for entry in batches if entry["id"] == line.get("batchId")), None) if product else None
        if not batch or batch["stock"] < line["qty"] or batch["expiry"] < date.today().isoformat():
            raise ValueError("A selected product batch is expired or has insufficient stock.")

    connection = connect(database)
    try:
        existing = connection.execute(
            "SELECT status FROM phonepe_payments WHERE merchant_order_id = ?",
            (merchant_order_id,),
        ).fetchone()
        if existing:
            raise ValueError("This payment order already exists. Start a new checkout.")
    finally:
        connection.close()

    order = phonepe_api_request("/checkout/v2/pay", method="POST", payload={
        "merchantOrderId": merchant_order_id,
        "amount": amount,
        "expireAfter": 1200,
        "paymentFlow": {
            "type": "PG_CHECKOUT",
            "merchantUrls": {"redirectUrl": phonepe_return_url(merchant_order_id)},
        },
        "metaInfo": {"udf1": transaction.get("id", "")[:256]},
    })
    redirect_url = order.get("redirectUrl")
    provider_order_id = order.get("orderId")
    if not isinstance(redirect_url, str) or not redirect_url.startswith("https://") or not isinstance(provider_order_id, str):
        raise PaymentGatewayError("PhonePe did not return a valid checkout session.")
    now = datetime.now(timezone.utc).isoformat()
    with closing(connect(database)) as connection:
        connection.execute(
            """INSERT INTO phonepe_payments
               (merchant_order_id, amount, status, intent_json, provider_order_id, created_at, updated_at)
               VALUES (?, ?, 'PENDING', ?, ?, ?, ?)""",
            (merchant_order_id, amount, json.dumps(intent, ensure_ascii=False), provider_order_id, now, now),
        )
        connection.commit()
    return {"merchantOrderId": merchant_order_id, "redirectUrl": redirect_url, "status": "PENDING"}


def complete_phonepe_payment(merchant_order_id, database=DATABASE):
    if not isinstance(merchant_order_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,63}", merchant_order_id):
        raise ValueError("Invalid merchantOrderId.")
    with closing(connect(database)) as connection:
        intent_row = connection.execute(
            "SELECT * FROM phonepe_payments WHERE merchant_order_id = ?",
            (merchant_order_id,),
        ).fetchone()
    if intent_row is None:
        raise ValueError("PhonePe payment order was not found.")
    if intent_row["status"] == "COMPLETED":
        saved = read_state(database)
        transaction = next((entry for entry in saved["state"]["transactions"] if entry.get("phonepeOrderId") == merchant_order_id), None)
        return {"status": "COMPLETED", "revision": saved["revision"], "transaction": transaction}

    status_result = phonepe_api_request(
        f"/checkout/v2/order/{urllib.parse.quote(merchant_order_id, safe='')}/status?details=false"
    )
    provider_status = status_result.get("state")
    provider_amount = status_result.get("amount")
    if provider_status != "COMPLETED":
        now = datetime.now(timezone.utc).isoformat()
        with closing(connect(database)) as connection:
            connection.execute(
                "UPDATE phonepe_payments SET status = ?, updated_at = ? WHERE merchant_order_id = ?",
                (str(provider_status or "PENDING"), now, merchant_order_id),
            )
            connection.commit()
        return {"status": str(provider_status or "PENDING"), "revision": read_state(database)["revision"]}
    if provider_amount != intent_row["amount"]:
        raise PaymentGatewayError("PhonePe reports a completed payment with an amount that does not match the invoice. Do not issue goods; reconcile this payment in the PhonePe dashboard.")

    intent = json.loads(intent_row["intent_json"])
    transaction = intent["transaction"]
    lines = intent["lines"]
    payment_details = status_result.get("paymentDetails") or []
    provider_transaction_id = payment_details[0].get("transactionId") if payment_details and isinstance(payment_details[0], dict) else None
    provider_payment_mode = payment_details[0].get("paymentMode") if payment_details and isinstance(payment_details[0], dict) else None
    transaction["lines"] = lines
    if isinstance(intent.get("soldBy"), dict):
        transaction["soldBy"] = intent["soldBy"]
    else:
        transaction.pop("soldBy", None)
    if isinstance(provider_payment_mode, str):
        if provider_payment_mode.startswith("UPI"):
            transaction["payment"] = "UPI"
        elif "CARD" in provider_payment_mode:
            transaction["payment"] = "Card"
    connection = connect(database)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current_payment = connection.execute(
            "SELECT status FROM phonepe_payments WHERE merchant_order_id = ?",
            (merchant_order_id,),
        ).fetchone()
        current = read_state_from_connection(connection)
        if current_payment["status"] == "COMPLETED":
            saved_transaction = next((entry for entry in current["state"]["transactions"] if entry.get("phonepeOrderId") == merchant_order_id), None)
            connection.commit()
            return {"status": "COMPLETED", "revision": current["revision"], "transaction": saved_transaction}
        state = current["state"]
        if any(entry.get("phonepeOrderId") == merchant_order_id for entry in state["transactions"]):
            connection.execute(
                "UPDATE phonepe_payments SET status = 'COMPLETED', updated_at = ? WHERE merchant_order_id = ?",
                (datetime.now(timezone.utc).isoformat(), merchant_order_id),
            )
            connection.commit()
            return {"status": "COMPLETED", "revision": current["revision"], "transaction": transaction}
        for line in lines:
            product = next((entry for entry in state["products"] if entry["id"] == line.get("id")), None)
            if product and not product.get("batches"):
                product["batches"] = [{"id": f"{product['id']}-batch-1", "batch": product.get("batch", ""), "expiry": product.get("expiry", ""), "stock": product.get("stock", 0)}]
            batch = next((entry for entry in product.get("batches", []) if entry["id"] == line.get("batchId")), None) if product else None
            if not batch or batch["stock"] < line["qty"] or batch["expiry"] < date.today().isoformat():
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "UPDATE phonepe_payments SET status = 'RECONCILIATION_REQUIRED', updated_at = ? WHERE merchant_order_id = ?",
                    (now, merchant_order_id),
                )
                connection.commit()
                return {"status": "RECONCILIATION_REQUIRED", "message": "Payment completed, but the stock changed during checkout. Reconcile this order before dispensing.", "revision": current["revision"]}
            batch["stock"] -= line["qty"]
            product["stock"] = sum(entry["stock"] for entry in product["batches"])
            product["batch"] = product["batches"][0]["batch"] if product["batches"] else ""
            product["expiry"] = product["batches"][0]["expiry"] if product["batches"] else ""

        customer = next((entry for entry in state["customers"] if entry["id"] == transaction.get("customerId")), None)
        if customer:
            redeemed = int(transaction.get("redeemed", 0))
            if customer["points"] < redeemed:
                connection.execute(
                    "UPDATE phonepe_payments SET status = 'RECONCILIATION_REQUIRED', updated_at = ? WHERE merchant_order_id = ?",
                    (datetime.now(timezone.utc).isoformat(), merchant_order_id),
                )
                connection.commit()
                return {"status": "RECONCILIATION_REQUIRED", "message": "Payment completed, but the customer's points changed during checkout. Reconcile this order.", "revision": current["revision"]}
            customer["points"] = customer["points"] - redeemed + int(transaction.get("earned", 0))
            customer["spent"] = customer.get("spent", 0) + float(transaction["total"])
            customer["visits"] = customer.get("visits", 0) + 1
            customer["tier"] = "Gold" if customer["spent"] >= 10000 else "Silver" if customer["spent"] >= 5000 else "Member"

        prefix = f"{state['store']['invoicePrefix']}-"
        used_ids = {entry["id"] for entry in state["transactions"]}
        if transaction.get("id") in used_ids:
            max_number = max((int(match.group(1)) for entry in state["transactions"] if (match := re.search(r"(\d+)$", entry["id"]))), default=0)
            transaction["id"] = f"{prefix}{max_number + 1}"
        transaction["phonepeOrderId"] = merchant_order_id
        transaction["phonepeTransactionId"] = provider_transaction_id
        transaction["status"] = "Paid"
        state["transactions"].insert(0, transaction)
        validate_state(state)
        saved = write_state_in_transaction(connection, state, current["revision"])
        connection.execute(
            """UPDATE phonepe_payments
               SET status = 'COMPLETED', transaction_id = ?, updated_at = ?
               WHERE merchant_order_id = ?""",
            (transaction["id"], saved["updatedAt"], merchant_order_id),
        )
        connection.commit()
        return {"status": "COMPLETED", "revision": saved["revision"], "transaction": transaction}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


class PhoebixHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.dispatch("GET", path)
        elif path in PUBLIC_FILES:
            super().do_GET()
        else:
            self.send_json(404, {"error": "Not found"})

    def do_HEAD(self):
        if urlparse(self.path).path in PUBLIC_FILES:
            super().do_HEAD()
        else:
            self.send_json(404, {"error": "Not found"})

    def do_PUT(self):
        self.dispatch("PUT", urlparse(self.path).path)

    def do_POST(self):
        self.dispatch("POST", urlparse(self.path).path)

    def session_token(self):
        morsel = SimpleCookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def authenticate(self, admin=False, allow_password_change=False):
        user = get_session_user(self.session_token())
        if user is None:
            raise AuthError("Sign in to continue.")
        if user["mustChangePassword"] and not allow_password_change:
            raise AuthError("Change your temporary password before continuing.", 403)
        if admin and user["role"] != "admin":
            raise AuthError("Only administrators can do this.", 403)
        return user

    def read_json(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Invalid Content-Length") from error
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            raise ValueError("Request body must be between 1 byte and 8 MB")
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("Request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("Request body must be a JSON object")
        return payload

    def session_cookie(self, token, max_age=SESSION_SECONDS):
        secure = "; Secure" if os.environ.get("PHOEBIX_PUBLIC_URL", "").startswith("https://") else ""
        return f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def dispatch(self, method, path):
        try:
            self.route(method, path)
        except AuthError as error:
            self.send_json(error.status, {"error": str(error)})
        except StateConflict as error:
            self.send_json(409, {"error": str(error), "revision": error.revision})
        except ValueError as error:
            self.send_json(400, {"error": str(error)})
        except PaymentGatewayError as error:
            self.send_json(502, {"error": str(error)})
        except sqlite3.Error as error:
            self.log_error("SQLite operation failed: %s", error)
            self.send_json(500, {"error": "Could not save to SQLite."})

    def route(self, method, path):
        route = (method, path)
        user_match = re.fullmatch(r"/api/users/(u[0-9a-f]+)", path)
        if route == ("GET", "/api/health"):
            result = read_state()
            self.send_json(200, {"status": "ok", "database": "sqlite", "revision": result["revision"], "updatedAt": result["updatedAt"]})
        elif route == ("POST", "/api/auth/login"):
            payload = self.read_json()
            token, user = login(payload.get("username"), payload.get("password"))
            self.send_json(200, {"user": user}, {"Set-Cookie": self.session_cookie(token)})
        elif route == ("POST", "/api/auth/logout"):
            logout(self.session_token())
            self.send_json(200, {"ok": True}, {"Set-Cookie": self.session_cookie("", 0)})
        elif route == ("GET", "/api/auth/session"):
            self.send_json(200, {"user": self.authenticate(allow_password_change=True)})
        elif route == ("POST", "/api/auth/password"):
            user = self.authenticate(allow_password_change=True)
            payload = self.read_json()
            self.send_json(200, {"user": change_password(user["id"], payload.get("currentPassword"), payload.get("newPassword"), self.session_token())})
        elif route == ("GET", "/api/users"):
            self.authenticate(admin=True)
            self.send_json(200, {"users": list_users()})
        elif route == ("POST", "/api/users"):
            self.authenticate(admin=True)
            self.send_json(201, {"user": create_user(self.read_json())})
        elif method == "PUT" and user_match:
            acting_user = self.authenticate(admin=True)
            self.send_json(200, {"user": update_user(user_match.group(1), self.read_json(), acting_user)})
        elif route == ("GET", "/api/state"):
            self.authenticate()
            self.send_json(200, read_state())
        elif route == ("PUT", "/api/state"):
            user = self.authenticate()
            payload = self.read_json()
            self.send_json(200, save_state(payload.get("state"), payload.get("expectedRevision"), user=user))
        elif route == ("POST", "/api/customers"):
            self.authenticate()
            self.send_json(201, add_customer(self.read_json()))
        elif route == ("GET", "/api/payments/phonepe/config"):
            self.authenticate()
            config = phonepe_config()
            self.send_json(200, {"configured": config["configured"], "environment": config["environment"]})
        elif route == ("POST", "/api/payments/phonepe/create"):
            user = self.authenticate()
            self.send_json(200, create_phonepe_payment(self.read_json(), user=user))
        elif route == ("POST", "/api/payments/phonepe/complete"):
            self.authenticate()
            self.send_json(200, complete_phonepe_payment(self.read_json().get("merchantOrderId")))
        else:
            self.send_json(404, {"error": "API endpoint not found"})

    def send_json(self, status, payload, headers=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format_string, *args):
        if self.path.startswith("/api/"):
            super().log_message(format_string, *args)


def open_app_window(url):
    """Open Phoebix in its own Edge/Chrome app window and return the browser process, if trackable."""
    # A dedicated profile makes the browser process live exactly as long as the Phoebix window.
    profile = APP_DIR / "window-profile"
    for base in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        for relative in ("Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe"):
            browser = Path(os.environ.get(base, "")) / relative
            if browser.is_file():
                return subprocess.Popen([str(browser), f"--app={url}", f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"])
    webbrowser.open(url)
    return None


def already_running(host, port):
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as response:
            return response.status == 200
    except OSError:
        return False


def start_database():
    print(f"[1/3] Starting database: {DATABASE}")
    initialize_database()
    result = read_state()
    if result["state"] is None:
        raise RuntimeError("The database opened but is empty.")
    with closing(connect()) as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"      Database ready (revision {result['revision']}, {users} users).")


def main():
    if not FROZEN and os.environ.get("PHOEBIX_DEV") != "1":
        raise RuntimeError("This is the desktop-only edition. Run Phoebix.exe (build it with build_exe.bat).")
    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)
    # Desktop-only: the server is reachable from this PC alone, whatever the environment says.
    host = "127.0.0.1"
    port = int(os.environ.get("PHOEBIX_PORT", "4173"))
    url = f"http://{'127.0.0.1' if host in ('0.0.0.0', '') else host}:{port}"
    open_window = os.environ.get("PHOEBIX_OPEN_BROWSER", "1") != "0"
    if already_running(host, port):
        print(f"Phoebix is already running at {url}")
        if open_window:
            open_app_window(url)
        return
    # The database must be up and verified before the web server or the window starts.
    start_database()
    print(f"[2/3] Starting app server at {url}")
    server = ThreadingHTTPServer((host, port), PhoebixHandler)
    print("[3/3] Opening Phoebix. Closing the Phoebix window stops it.")

    def launch_window():
        window = open_app_window(url)
        if window is not None:
            window.wait()
            print("\nPhoebix window closed. Stopping Phoebix.")
            server.shutdown()

    if open_window:
        threading.Thread(target=launch_window, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Phoebix server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\nPhoebix could not start: {error}")
        if FROZEN:
            input("Press Enter to close this window...")
        sys.exit(1)
