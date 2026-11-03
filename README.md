# Phoebix — Pharmacy desktop application

A native Windows desktop app for Indian pharmacies: GST billing, batch/expiry inventory, customers, loyalty points & offers, reports, PhonePe payments, user logins and bank details for payments.

There is **no server and no browser**. Phoebix is one process (`Phoebix.exe`) that talks to a local SQLite file, so it works fully offline (only PhonePe payments need internet).

## Architecture

Strict layers; dependencies point downward only.

```
phx/ui        Tkinter screens. Only calls services. No SQL, no business rules.
phx/services  Application use-cases: auth, billing, payments, inventory, customers,
              loyalty, reports. Enforces roles, orchestrates units of work.
phx/domain    Pure business rules: GST/discount/points maths, validation, password hashing.
              No I/O.
phx/data      SQLite schema, repositories, unit of work. The only code that imports sqlite3.
main.py       Composition root: builds Database -> Services -> UI.
```

| Layer | May import | Must not import |
|---|---|---|
| `ui` | `services` | `data`, `domain`, `sqlite3` |
| `services` | `domain`, `data` | `ui`, `tkinter`, `sqlite3` |
| `domain` | standard library only | `data`, `services`, `ui` |
| `data` | `sqlite3` | `domain`, `services`, `ui` |

`tests/test_layers.py` fails if any of these rules is broken. Checkout (stock, points, invoice number, sale) runs in a single SQLite transaction through `Database.unit_of_work()`.

## Run

Build once (Python 3.10+ is needed on the build PC only), then double-click the result:

```powershell
build_exe.bat
dist\Phoebix.exe
```

From source: `python main.py`. Run the tests with `python -m unittest discover -s tests -t .`.

The database and `.env` live in `%LOCALAPPDATA%\Phoebix\` when run as the exe (`data\phoebix_desktop.sqlite3`), or in the project folder when run from source. Set `PHOEBIX_DB_PATH` to use another file. This edition uses a new database file; data from the earlier web edition is not imported.

## Sign-in and users

| Login ID | Password | Role |
|---|---|---|
| `admin` | `admin123` | Administrator |
| `cashier` | `cashier123` | Staff |

Both must choose a new password at first sign-in (or set `PHOEBIX_ADMIN_PASSWORD` in `.env` before the first start). Passwords are PBKDF2-SHA256 hashes; five wrong attempts lock a login ID for one minute.

- Every sale records the signed-in login ID (`Sold by`), shown on invoices, reports and CSV exports. It comes from the session, never from a form.
- Only administrators manage users, bank details, reward rules/offers and point adjustments. These rules are enforced in the service layer, not just by disabling buttons.

## Features

- **New Sale**: product search, earliest-expiry batch picking, offers, manual discount, points redemption, add a customer without leaving the screen, Cash / Credit / UPI / Card, printable GST invoice.
- **Inventory**: batches and expiry, low-stock and near-expiry filters, add product, receive stock, CSV export.
- **Customers**: profiles, tiers (Member / Silver / Gold), points, CSV export.
- **Rewards & Offers**: earn/redeem rules, bonus toggles, percentage or fixed offers.
- **Reports**: sales, payment mix, inventory value by category, all invoices.
- **Settings**: store profile and the bank account payments are made to (printed as "Pay to" on invoices).

## PhonePe payments

UPI and card use PhonePe Standard Checkout. Phoebix creates the order, opens PhonePe's payment page in your browser, then polls the order status every few seconds (or use **Check payment status**). The sale, stock and points are written only after PhonePe confirms the order is `COMPLETED` for the exact invoice amount. If stock changed while the customer was paying, the order is marked for reconciliation instead of silently selling.

1. Get the Client ID, Client Secret and Client Version from the PhonePe Business dashboard.
2. Copy `.env.example` to `.env` (in `%LOCALAPPDATA%\Phoebix\` for the exe) and fill them in.
3. Restart Phoebix. For live payments set `PHONEPE_ENV=production`.

This has not been run against a live PhonePe account yet; test in the sandbox first.
