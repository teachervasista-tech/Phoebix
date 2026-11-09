# Phoebix Pharmacy Management System - Release & Deployment

A lightweight, database-agnostic pharmacy management system for Windows with GST billing, inventory, customers, payments, and loyalty rewards.

## 📦 Release Overview

Phoebix is packaged as a **single self-contained Windows executable** with all dependencies bundled. No installation, no external dependencies, no registry modifications.

### Key Features

- ✅ **Zero Dependencies** - Runs on any Windows 10/11 without additional software
- ✅ **Single File** - `Phoebix.exe` contains the entire application
- ✅ **Auto Database** - SQLite database initialized on first run
- ✅ **Sample Data** - Comes with products, customers, and transactions
- ✅ **Portable** - Copy and run from any location
- ✅ **Secure** - Single-instance lock, encrypted passwords, role-based access

## 🚀 Quick Start

### For Users (Running the App)

1. **Get the executable**:
   - Download `Phoebix.exe` from the release package
   - Or run from the repository: `dist\Phoebix.exe`

2. **Run it**:
   ```cmd
   Phoebix.exe
   ```

3. **First launch**:
   - Database initializes automatically (takes 5-10 seconds)
   - Sample data loads
   - Login screen appears
   - Default credentials: `admin` / `admin123`
   - Set a new password when prompted

### For Developers (Building the Release)

1. **Build the executable**:
   ```cmd
   cd C:\path\to\Phoebix
   build_exe.bat
   ```

2. **Create release package**:
   ```cmd
   package_release.bat
   ```

3. **Distribute**:
   - Share the `Phoebix-Release-YYYYMMDD-HHMM` folder
   - Users can run `install.bat` or just double-click `Phoebix.exe`

## 📋 Building for Release

### Prerequisites

- Windows 10 or later
- Python 3.10+ installed and in PATH
- ~500 MB disk space for build artifacts

### Build Process

```cmd
REM Clone or extract repository
cd C:\path\to\Phoebix

REM Build the executable
build_exe.bat

REM This will:
REM  1. Install/upgrade PyInstaller
REM  2. Clean previous builds
REM  3. Compile to dist\Phoebix.exe (~25 MB)
REM  4. Display build status
```

**Build output**:
```
dist\
└── Phoebix.exe          (25-30 MB single executable)
```

### Create Distribution Package

```cmd
package_release.bat

REM This will:
REM  1. Create timestamped folder (Phoebix-Release-20240101-1430)
REM  2. Copy executable and installation files
REM  3. Create README and documentation
REM  4. Ready for distribution
```

**Release package**:
```
Phoebix-Release-20240101-1430\
├── Phoebix.exe              (main executable)
├── install.bat              (installer script)
├── DEPLOYMENT.md            (deployment guide)
├── README.txt               (quick start)
├── VERSION.txt              (build info)
└── .env.example             (configuration template)
```

## 💾 Database Initialization

### Automatic Initialization

On first launch, Phoebix automatically:

1. **Create directories**:
   ```
   %LOCALAPPDATA%\Phoebix\
   ├── data\
   │   └── phoebix_desktop.sqlite3    (new database)
   └── .env                            (optional config)
   ```

2. **Create database schema** with 8 tables:
   - `users` - Administrator and staff accounts
   - `products` - Medicine catalog with pricing
   - `batches` - Stock and expiry tracking
   - `customers` - Customer profiles and loyalty
   - `offers` - Promotional offers
   - `sales` - Transaction records
   - `payments` - Payment gateway integration
   - `settings` - Store configuration

3. **Seed default data**:
   - Admin account: `admin` / `admin123`
   - Staff account: `cashier` / `cashier123`
   - Sample medicines, customers, and transactions
   - Store settings and loyalty rules

4. **Verify integrity**:
   - Run `PRAGMA integrity_check`
   - Confirm database is ready

### Empty Database Start

For a fresh installation with no sample data:

1. Create `.env` file before first run:
   ```env
   # Any existing .env skips database initialization
   PHOEBIX_DB_PATH=%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3
   ```

2. On first run:
   - Schema is created (empty tables)
   - Default users are seeded
   - No sample data is loaded

3. Manually add:
   - Products in Inventory → Add Product
   - Customers in Customers → Add Customer
   - Store settings in Settings

### Database Startup Verification

The main entry point (`main.py`) now ensures database readiness:

```python
def init_database():
    """Initialize database with schema and bootstrap data."""
    # 1. Create/open database
    # 2. Execute schema (CREATE TABLE IF NOT EXISTS)
    # 3. Bootstrap default users
    # 4. Load sample data
    # 5. Verify integrity_check
    # Return Database object or raise error
```

**Startup sequence**:
```
main() entry point
  ↓
load_environment_file()        (read .env if exists)
  ↓
acquire_single_instance()      (ensure only one running)
  ↓
init_database()                (DATABASE STARTS HERE!)
  ├─ Database.__init__         (create DB file)
  ├─ conn.executescript(SCHEMA) (create tables)
  ├─ bootstrap()               (seed users & data)
  └─ integrity_check()         (verify success)
  ↓
Services(database)             (only if DB ready)
  ↓
PhoebixApp(services)           (start UI)
  ↓
.mainloop()                    (display window)
```

## 📁 File Structure for Release

### Build Scripts

```
C:\Phoebix\
├── build_exe.bat              (main build script)
├── package_release.bat         (create distribution)
├── install.bat                 (deployment installer)
├── Phoebix.spec               (PyInstaller config)
└── main.py                     (entry point with DB init)
```

### Distribution Contents

When creating a release, these files are packaged:

- `Phoebix.exe` - Complete application
- `install.bat` - Automated setup (creates shortcuts, config)
- `DEPLOYMENT.md` - Comprehensive deployment guide
- `README.txt` - Quick reference
- `VERSION.txt` - Build information
- `.env.example` - Configuration template

### Data Locations (Runtime)

```
%LOCALAPPDATA%\Phoebix\
├── data\
│   └── phoebix_desktop.sqlite3
│       ├── Stores all transactions, inventory, customers
│       ├── ~2-50 MB depending on usage
│       └── Backed by WAL (Write-Ahead Logging)
└── .env (optional)
    └── PHOEBIX_ADMIN_PASSWORD=...
        PHOEBIX_DB_PATH=...
        PHONEPE_ENV=...
```

## 🔒 Security

### Single Instance Lock

```python
handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\PhoebixDesktopApp")
```

- Only one Phoebix process per computer
- Prevents database corruption from concurrent access
- Clear error message if already running

### Password Security

- PBKDF2-SHA256 hashing
- Salted and iterated
- Temporary passwords force change on first login
- Role-based access control (admin/staff)

### Database Integrity

- Foreign key constraints enabled
- Transaction support with rollback
- Integrity check on startup
- WAL mode for crash recovery

## 📊 Deployment Scenarios

### Scenario 1: Single Computer

```
1. Double-click Phoebix.exe
2. Done! Database auto-initializes
```

### Scenario 2: Multiple Locations

```
1. Distribute Phoebix.exe to each location
2. Each computer gets its own database in %LOCALAPPDATA%
3. No data sharing (separate databases)
```

### Scenario 3: Networked Database

```
1. Modify PHOEBIX_DB_PATH in .env to point to network location
2. Place .env in %LOCALAPPDATA%\Phoebix\ before first run
3. Phoebix.exe runs on multiple computers against same database
4. Must handle concurrent access properly (test thoroughly!)
```

### Scenario 4: Pre-Configured Deployment

```
1. Create .env with all configuration
2. Create .env.template for documentation
3. Provide .env alongside Phoebix.exe
4. Users extract both before first run
5. Database and settings pre-configured
```

## 🔄 Upgrade Path

### Upgrading to New Version

```
1. Backup current database:
   copy %LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3 backup.sqlite3

2. Replace Phoebix.exe with new version

3. Run new Phoebix.exe
   - Schema is updated if needed (CREATE TABLE IF NOT EXISTS)
   - Existing data is preserved
   - New features available

4. If issues occur:
   - Close Phoebix
   - Restore backup
   - Test upgrade again
```

## 📝 Building and Deployment Checklist

### Development (Before Release)

- [ ] Test on clean Windows 10/11 VM
- [ ] Verify database initializes correctly
- [ ] Test with empty database
- [ ] Test with sample data
- [ ] Test password change flow
- [ ] Test all main features
- [ ] Check executable file size (should be ~25-30 MB)
- [ ] Verify no external dependencies needed

### Build Process

- [ ] Run `build_exe.bat` successfully
- [ ] Verify `dist\Phoebix.exe` exists
- [ ] Test `Phoebix.exe` directly
- [ ] Run `package_release.bat`
- [ ] Verify release folder created
- [ ] Test installation from release package

### Deployment

- [ ] Create deployment documentation
- [ ] Test on target computer (clean install)
- [ ] Verify database initializes
- [ ] Test login and password change
- [ ] Test main features
- [ ] Verify no errors in event log
- [ ] Create user guide

### Post-Deployment

- [ ] Monitor first week for issues
- [ ] Collect user feedback
- [ ] Backup customer data regularly
- [ ] Plan upgrade strategy

## 🆘 Troubleshooting

### Build Fails

```
Error: PyInstaller not found
Solution: build_exe.bat will auto-install it

Error: Python version too old
Solution: Upgrade to Python 3.10+

Error: Out of disk space
Solution: Clean old build artifacts or upgrade disk space
```

### Database Initialization Fails

```
Error: Cannot create directory
Solution: Check write permissions in %LOCALAPPDATA%

Error: Database corruption
Solution: Delete phoebix_desktop.sqlite3, let it reinitialize

Error: Already running
Solution: Close all Phoebix windows, check Task Manager
```

### Deployment Issues

```
Issue: Cannot write to %LOCALAPPDATA%
Solution: Run as Administrator once, or fix user permissions

Issue: Antivirus blocks Phoebix.exe
Solution: Add to antivirus whitelist or disable for testing

Issue: Works on dev machine but not on user's PC
Solution: Check Windows version, disk space, RAM, permissions
```

## 📞 Support & Documentation

- **DEPLOYMENT.md** - Complete deployment guide
- **README.md** - Main project documentation
- **install.bat** - Interactive installer
- **main.py** - Database initialization code

## 📦 Version Control

Include these in repository:

```
Git tracked:
  ✓ main.py                    (improved entry point)
  ✓ Phoebix.spec              (PyInstaller config)
  ✓ build_exe.bat             (build script)
  ✓ package_release.bat        (packaging script)
  ✓ install.bat               (installer script)
  ✓ DEPLOYMENT.md             (deployment guide)
  ✓ README.md                 (main docs)

Git ignored:
  ✗ dist/                      (build artifacts)
  ✗ build/                     (build artifacts)
  ✗ *.spec                     (auto-generated)
  ✗ Phoebix-Release-*          (release packages)
```

## 🎯 Next Steps

1. **Run build**: `build_exe.bat` to create `dist\Phoebix.exe`
2. **Test it**: Double-click the executable to verify
3. **Package it**: `package_release.bat` to create distribution
4. **Deploy it**: Share the release folder or individual files
5. **Support it**: Refer users to DEPLOYMENT.md

That's it! Users can now:
- Copy `Phoebix.exe` anywhere and run it
- Or run `install.bat` for automated setup
- Database initializes automatically
- Ready to use in under 1 minute

---

**Key Achievement**: Database and all dependencies are now bundled. Every new computer gets:
- ✅ Empty database (or with sample data)
- ✅ Automatic schema creation
- ✅ Default user accounts
- ✅ All in one `.exe` file
- ✅ No external dependencies
- ✅ Zero configuration needed
