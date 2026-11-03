SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','staff')),
  password_hash TEXT NOT NULL,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT 'Others', hsn TEXT NOT NULL DEFAULT '',
  reorder INTEGER NOT NULL DEFAULT 0, price REAL NOT NULL, mrp REAL NOT NULL,
  gst INTEGER NOT NULL DEFAULT 0, emoji TEXT NOT NULL DEFAULT '', tone TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS batches (
  id TEXT PRIMARY KEY, product_id TEXT NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  batch TEXT NOT NULL, expiry TEXT NOT NULL, stock INTEGER NOT NULL CHECK (stock >= 0)
);
CREATE TABLE IF NOT EXISTS customers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, email TEXT NOT NULL DEFAULT '—',
  address TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT '', gstin TEXT NOT NULL DEFAULT '',
  drug_license TEXT NOT NULL DEFAULT '', points INTEGER NOT NULL DEFAULT 0 CHECK (points >= 0),
  tier TEXT NOT NULL DEFAULT 'Member', spent REAL NOT NULL DEFAULT 0, visits INTEGER NOT NULL DEFAULT 0,
  joined TEXT NOT NULL, initials TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS offers (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, discount REAL NOT NULL, type TEXT NOT NULL,
  end TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sales (
  id TEXT PRIMARY KEY, seq INTEGER NOT NULL, customer_id TEXT, customer_name TEXT NOT NULL,
  date TEXT NOT NULL, total REAL NOT NULL, items INTEGER NOT NULL, payment TEXT NOT NULL,
  status TEXT NOT NULL, earned INTEGER NOT NULL DEFAULT 0, redeemed INTEGER NOT NULL DEFAULT 0,
  sold_by_id INTEGER, sold_by_username TEXT, sold_by_name TEXT,
  gateway TEXT, phonepe_order_id TEXT, phonepe_transaction_id TEXT,
  lines_json TEXT, totals_json TEXT
);
CREATE TABLE IF NOT EXISTS payments (
  merchant_order_id TEXT PRIMARY KEY, amount INTEGER NOT NULL, status TEXT NOT NULL,
  intent_json TEXT NOT NULL, provider_order_id TEXT, sale_id TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""
