# Phoebix Pharmacy Workspace (desktop edition)

A desktop-only pharmacy workspace for Indian retail and wholesale operations, with a local Python API and persistent SQLite database. It runs only as `Phoebix.exe` on the PC that holds the data: there is no web or browser install, and the server listens on this PC (`127.0.0.1`) only.

## Run

Build the app once (needs Python 3.10+ on the build PC only), then double-click the result:

```powershell
build_exe.bat
dist\Phoebix.exe
```

Developers can run from source with `$env:PHOEBIX_DEV="1"; python server.py`. Set `PHOEBIX_OPEN_BROWSER=0` to start without opening a window.

## One-click Windows app

`dist\Phoebix.exe` is a single file that needs no Python. Double-click it to start the database and server and open Phoebix in its own window. Closing the Phoebix window also stops the server and closes the black console window. Opening it again just reopens the window.

When run as the exe, the database and `.env` live in `%LOCALAPPDATA%\Phoebix\` (so they survive upgrades). Everything works offline except PhonePe payments.

## Sign-in and users

Phoebix requires a login. A fresh or existing database is given two starter accounts the first time the server starts:

| Login ID | Password | Role |
|---|---|---|
| `admin` | `admin123` | Administrator |
| `cashier` | `cashier123` | Staff |

Both start with a temporary password, and Phoebix forces a new one at first sign-in. Set `PHOEBIX_ADMIN_PASSWORD` in `.env` before the first start to seed the admin with your own password instead.

- Administrators open **Users & access** to add users, change names and roles, disable accounts, and reset passwords. Staff cannot call the user-management API. At least one active administrator must always exist.
- Passwords are stored as salted PBKDF2-SHA256 hashes. Sessions are random tokens in an HttpOnly, SameSite=Strict cookie that lasts 12 hours. Five wrong passwords lock a login ID for one minute.
- Every sale stores the login ID that made it (`soldBy`: user id, login ID, name). The server sets it from the signed-in session, so the browser cannot forge or reassign it, and it is shown on invoices, the dashboard, reports and the CSV export. PhonePe sales are credited to the user who started the checkout. Sample sales created before login existed show "—".
- Roles currently separate user administration only. Both roles can use sales, inventory, customers and rewards.
- Only the app files are served as static files. The database, `.env` and `server.py` are not downloadable.

## Database and API

- The SQLite database is created at `data/phoebix.sqlite3` on first run. Set `PHOEBIX_DB_PATH` to choose another file location.
- Pharmacy profile, inventory and batch lots, customers, invoices, loyalty rules, and offers are persisted in SQLite.
- `GET /api/health` reports database connectivity and revision; `GET /api/state` reads the saved pharmacy workspace; `PUT /api/state` saves changes with a revision check to prevent overwriting another client’s edits.
- Phoebix reads and writes workspace data only through the SQLite API. It does not import browser-only data, use browser storage, or allow changes while the database is unavailable; the workspace stays locked until a database connection is restored.
- A new or empty database is seeded by the server from `sample_state.json` before the app is served. The service worker may cache app files, but all workspace data is loaded from and saved to SQLite.
- Back up the database by stopping the server and copying the SQLite file together with any `-wal`/`-shm` files, or use SQLite’s online backup API.

The server always binds to `127.0.0.1` and is reachable only from this PC. User login protects the API.

## PhonePe payments (sandbox)

UPI and card checkout use PhonePe's hosted Standard Checkout. Customers are redirected to PhonePe to pay; Phoebix does not collect or store card details. A sale and its stock/loyalty updates are written to SQLite only after the backend checks the order status and amount with PhonePe. Cash and credit remain manual checkout methods.

1. Create a PhonePe Payment Gateway account and obtain the sandbox Client ID, Client Secret, and Client Version from the PhonePe Business Developer settings.
2. Copy `.env.example` to `.env` and fill in the sandbox credentials. Keep `.env` private; it is excluded from Git.
3. Restart Phoebix.exe. UPI and card choices become available in point of sale when the server confirms the credentials are configured.
4. For production, use PhonePe's production credentials, set `PHONEPE_ENV=production`, and set `PHOEBIX_PUBLIC_URL` to the app's public HTTPS URL. Complete PhonePe's merchant onboarding and enable the desired payment methods before accepting live payments.

PhonePe API documentation: [authorization](https://developer.phonepe.com/payment-gateway/website-integration/standard-checkout/api-integration/api-reference/authorization), [initiate payment](https://developer.phonepe.com/payment-gateway/website-integration/standard-checkout/api-integration/api-reference/create-payment/initiate-payment), and [check order status](https://developer.phonepe.com/payment-gateway/website-integration/standard-checkout/api-integration/api-reference/order-status).

## Included workflows

- GST-ready point of sale with HSN, product tax slabs, customer selection, discounts, points redemption, and printable invoice.
- Pharmacy profile settings for invoice identity, GSTIN, address, drug licence and invoice numbering; the pharmacy's bank account (holder, bank, branch, account number, IFSC, account type, UPI ID) printed as "Pay to" on every invoice, editable by administrators only; customer GSTIN/licence/address fields.
- Multi-batch inventory with expiry dates, FIFO batch selection, expired-stock sale prevention, low-stock indicators, search, and stock intake.
- Customer profiles with pharmacy contact details, loyalty balances, and purchase history.
- Configurable loyalty earning/redemption, membership tiers, and offer toggles.
- Overview and sales reports with daily totals, recent invoices, and stock alerts.

## Demo and production use

The initial catalog and customer list are fictional sample data for demonstration and are inserted into the SQLite database at server startup when it is empty. The SQLite database persists records on this server but is not a cloud backup or multi-store sync service. This starter does not connect to a GST filing service or regulated dispensing system; configure and verify the business's GSTIN, tax treatment, and operational policies before real-world use. Until a GSTIN is configured, bills are explicitly labelled as demo bills rather than tax invoices.
