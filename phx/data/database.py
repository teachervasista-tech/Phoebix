"""Data layer: the only package that touches sqlite3."""
import json
import sqlite3
from contextlib import closing, contextmanager

from .schema import SCHEMA


class DataError(Exception):
    """Raised for constraint violations the caller can report."""


def _bool(row, key):
    return bool(row[key])


class UserRepo:
    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _map(row):
        if row is None:
            return None
        return {"id": row["id"], "username": row["username"], "name": row["name"], "role": row["role"],
                "passwordHash": row["password_hash"], "mustChangePassword": _bool(row, "must_change_password"),
                "active": _bool(row, "active"), "createdAt": row["created_at"]}

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def active_admin_count(self):
        return self.conn.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]

    def all(self):
        return [self._map(r) for r in self.conn.execute("SELECT * FROM users ORDER BY created_at, username")]

    def get(self, user_id):
        return self._map(self.conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def by_username(self, username):
        return self._map(self.conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone())

    def add(self, username, name, role, password_hash, must_change, created_at):
        try:
            cursor = self.conn.execute(
                "INSERT INTO users (username,name,role,password_hash,must_change_password,active,created_at)"
                " VALUES (?,?,?,?,?,1,?)", (username, name, role, password_hash, int(must_change), created_at))
        except sqlite3.IntegrityError as error:
            raise DataError("That username is already taken.") from error
        return cursor.lastrowid

    def update(self, user_id, name, role, active, password_hash, must_change):
        self.conn.execute(
            "UPDATE users SET name=?, role=?, active=?, password_hash=?, must_change_password=? WHERE id=?",
            (name, role, int(active), password_hash, int(must_change), user_id))


class SettingsRepo:
    def __init__(self, conn):
        self.conn = conn

    def get(self, key, default):
        row = self.conn.execute("SELECT value_json FROM settings WHERE key=?", (key,)).fetchone()
        return {**default, **json.loads(row[0])} if row else dict(default)

    def has(self, key):
        return self.conn.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone() is not None

    def put(self, key, value):
        self.conn.execute("INSERT INTO settings (key,value_json) VALUES (?,?)"
                          " ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                          (key, json.dumps(value, ensure_ascii=False)))


class ProductRepo:
    def __init__(self, conn):
        self.conn = conn

    def _hydrate(self, row):
        batches = [dict(id=b["id"], batch=b["batch"], expiry=b["expiry"], stock=b["stock"]) for b in
                   self.conn.execute("SELECT * FROM batches WHERE product_id=? ORDER BY expiry, batch", (row["id"],))]
        product = {k: row[k] for k in row.keys()}
        product.update(batches=batches, stock=sum(b["stock"] for b in batches),
                       batch=batches[0]["batch"] if batches else "", expiry=batches[0]["expiry"] if batches else "")
        return product

    def all(self):
        return [self._hydrate(r) for r in self.conn.execute("SELECT * FROM products ORDER BY name")]

    def get(self, product_id):
        row = self.conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone()
        return self._hydrate(row) if row else None

    def count(self):
        return self.conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]

    def add(self, p):
        self.conn.execute(
            "INSERT INTO products (id,name,brand,category,hsn,reorder,price,mrp,gst,emoji,tone)"
            " VALUES (:id,:name,:brand,:category,:hsn,:reorder,:price,:mrp,:gst,:emoji,:tone)", p)

    def add_batch(self, batch_id, product_id, batch, expiry, stock):
        self.conn.execute("INSERT INTO batches (id,product_id,batch,expiry,stock) VALUES (?,?,?,?,?)",
                          (batch_id, product_id, batch, expiry, stock))

    def set_batch_stock(self, batch_id, stock):
        self.conn.execute("UPDATE batches SET stock=? WHERE id=?", (stock, batch_id))

    def decrement_batch(self, batch_id, qty):
        """Atomically reduce stock; returns False when stock is insufficient."""
        cursor = self.conn.execute("UPDATE batches SET stock = stock - ? WHERE id=? AND stock >= ?",
                                   (qty, batch_id, qty))
        return cursor.rowcount == 1

    def next_batch_id(self, product_id):
        n = self.conn.execute("SELECT COUNT(*) FROM batches WHERE product_id=?", (product_id,)).fetchone()[0]
        existing = {r[0] for r in self.conn.execute("SELECT id FROM batches WHERE product_id=?", (product_id,))}
        while f"{product_id}-batch-{n + 1}" in existing:
            n += 1
        return f"{product_id}-batch-{n + 1}"

    def new_id(self):
        n = self.count() + 1
        while self.get(f"p{n}"):
            n += 1
        return f"p{n}"


class CustomerRepo:
    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _map(row):
        if row is None:
            return None
        c = {k: row[k] for k in row.keys()}
        c["drugLicense"] = c.pop("drug_license")
        return c

    def all(self):
        return [self._map(r) for r in self.conn.execute("SELECT * FROM customers ORDER BY name")]

    def get(self, customer_id):
        return self._map(self.conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone())

    def phones(self):
        return [r[0] for r in self.conn.execute("SELECT phone FROM customers")]

    def new_id(self):
        n = self.conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] + 1
        while self.get(f"c{n}"):
            n += 1
        return f"c{n}"

    def add(self, c):
        self.conn.execute(
            "INSERT INTO customers (id,name,phone,email,address,state,gstin,drug_license,points,tier,spent,visits,joined,initials)"
            " VALUES (:id,:name,:phone,:email,:address,:state,:gstin,:drugLicense,:points,:tier,:spent,:visits,:joined,:initials)",
            {"address": "", "state": "", "gstin": "", "drugLicense": "", "email": "—", **c})

    def update_loyalty(self, customer_id, points, spent, visits, tier):
        self.conn.execute("UPDATE customers SET points=?, spent=?, visits=?, tier=? WHERE id=?",
                          (points, spent, visits, tier, customer_id))


class OfferRepo:
    def __init__(self, conn):
        self.conn = conn

    def all(self):
        return [{**{k: r[k] for k in r.keys()}, "enabled": bool(r["enabled"])}
                for r in self.conn.execute("SELECT * FROM offers ORDER BY rowid DESC")]

    def get(self, offer_id):
        return next((o for o in self.all() if o["id"] == offer_id), None)

    def add(self, offer_id, name, discount, kind, end):
        self.conn.execute("INSERT INTO offers (id,name,discount,type,end,enabled) VALUES (?,?,?,?,?,1)",
                          (offer_id, name, discount, kind, end))

    def set_enabled(self, offer_id, enabled):
        self.conn.execute("UPDATE offers SET enabled=? WHERE id=?", (int(enabled), offer_id))

    def delete(self, offer_id):
        self.conn.execute("DELETE FROM offers WHERE id=?", (offer_id,))


class SaleRepo:
    def __init__(self, conn):
        self.conn = conn

    @staticmethod
    def _map(row):
        sold = ({"userId": row["sold_by_id"], "username": row["sold_by_username"], "name": row["sold_by_name"]}
                if row["sold_by_username"] else None)
        return {"id": row["id"], "customerId": row["customer_id"], "customerName": row["customer_name"],
                "date": row["date"], "total": row["total"], "items": row["items"], "payment": row["payment"],
                "status": row["status"], "earned": row["earned"], "redeemed": row["redeemed"], "soldBy": sold,
                "gateway": row["gateway"], "phonepeOrderId": row["phonepe_order_id"],
                "phonepeTransactionId": row["phonepe_transaction_id"],
                "lines": json.loads(row["lines_json"]) if row["lines_json"] else None,
                "totals": json.loads(row["totals_json"]) if row["totals_json"] else None}

    def all(self):
        return [self._map(r) for r in self.conn.execute("SELECT * FROM sales ORDER BY seq DESC")]

    def get(self, sale_id):
        row = self.conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
        return self._map(row) if row else None

    def by_phonepe_order(self, order_id):
        row = self.conn.execute("SELECT * FROM sales WHERE phonepe_order_id=?", (order_id,)).fetchone()
        return self._map(row) if row else None

    def max_seq(self):
        return self.conn.execute("SELECT COALESCE(MAX(seq), 1048) FROM sales").fetchone()[0]

    def add(self, s):
        sold = s.get("soldBy") or {}
        self.conn.execute(
            "INSERT INTO sales (id,seq,customer_id,customer_name,date,total,items,payment,status,earned,redeemed,"
            "sold_by_id,sold_by_username,sold_by_name,gateway,phonepe_order_id,phonepe_transaction_id,lines_json,totals_json)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["id"], s["seq"], s.get("customerId"), s["customerName"], s["date"], s["total"], s["items"],
             s["payment"], s["status"], s.get("earned", 0), s.get("redeemed", 0), sold.get("userId"),
             sold.get("username"), sold.get("name"), s.get("gateway"), s.get("phonepeOrderId"),
             s.get("phonepeTransactionId"),
             json.dumps(s["lines"], ensure_ascii=False) if s.get("lines") else None,
             json.dumps(s["totals"]) if s.get("totals") else None))


class PaymentRepo:
    def __init__(self, conn):
        self.conn = conn

    def get(self, order_id):
        row = self.conn.execute("SELECT * FROM payments WHERE merchant_order_id=?", (order_id,)).fetchone()
        if not row:
            return None
        return {"merchantOrderId": row["merchant_order_id"], "amount": row["amount"], "status": row["status"],
                "intent": json.loads(row["intent_json"]), "providerOrderId": row["provider_order_id"],
                "saleId": row["sale_id"]}

    def add(self, order_id, amount, intent, provider_order_id, now):
        self.conn.execute(
            "INSERT INTO payments (merchant_order_id,amount,status,intent_json,provider_order_id,created_at,updated_at)"
            " VALUES (?,?,'PENDING',?,?,?,?)",
            (order_id, amount, json.dumps(intent, ensure_ascii=False), provider_order_id, now, now))

    def set_status(self, order_id, status, now, sale_id=None):
        self.conn.execute("UPDATE payments SET status=?, updated_at=?, sale_id=COALESCE(?, sale_id)"
                          " WHERE merchant_order_id=?", (status, now, sale_id, order_id))


class Repositories:
    """Repositories bound to one connection, i.e. one unit of work."""

    def __init__(self, conn):
        self.users, self.settings = UserRepo(conn), SettingsRepo(conn)
        self.products, self.customers = ProductRepo(conn), CustomerRepo(conn)
        self.offers, self.sales, self.payments = OfferRepo(conn), SaleRepo(conn), PaymentRepo(conn)


class Database:
    def __init__(self, path):
        self.path = str(path)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)

    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    @contextmanager
    def unit_of_work(self, write=False):
        """Yield repositories; commit on success, roll back on any error."""
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield Repositories(conn)
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def integrity_ok(self):
        with closing(self._connect()) as conn:
            return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
