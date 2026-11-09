# 🚀 Phoebix Release - Quick Reference Guide

## Build Release in 3 Steps

```
Step 1: BUILD
┌─────────────────────────────────────┐
│ build_exe.bat                       │
├─────────────────────────────────────┤
│ • Installs PyInstaller              │
│ • Cleans old builds                 │
│ • Compiles Phoebix.exe              │
│ • Verifies success                  │
└─────────────────────────────────────┘
        ↓ Creates: dist\Phoebix.exe (25-30 MB)

Step 2: TEST
┌─────────────────────────────────────┐
│ dist\Phoebix.exe                    │
├─────────────────────────────────────┤
│ • Initializes database (5-10 sec)   │
│ • Shows login screen                │
│ • Verify with admin/admin123        │
└─────────────────────────────────────┘
        ↓ Success = ready to deploy

Step 3: PACKAGE
┌─────────────────────────────────────┐
│ package_release.bat                 │
├─────────────────────────────────────┤
│ • Creates release folder            │
│ • Bundles exe + documentation       │
│ • Includes installer script         │
└─────────────────────────────────────┘
        ↓ Creates: Phoebix-Release-*/
```

## User Deployment in 2 Steps

```
Step 1: RECEIVE
┌─────────────────────────────────────┐
│ Option A: Get Phoebix.exe            │
│ Option B: Get install.bat + exe      │
└─────────────────────────────────────┘
        ↓

Step 2: LAUNCH
┌─────────────────────────────────────┐
│ Option A: Double-click Phoebix.exe   │
│ Option B: Run install.bat            │
├─────────────────────────────────────┤
│ • Database auto-initializes         │
│ • Login screen appears              │
│ • Ready to use                      │
└─────────────────────────────────────┘
```

## File Structure

```
Repository                Build Artifacts         Release Package         Runtime Data
──────────────            ────────────────        ───────────────         ────────────

C:\Phoebix\               dist/                   Phoebix-Release-*/      %LOCALAPPDATA%\
├── main.py              └── Phoebix.exe          ├── Phoebix.exe         Phoebix\
├── phx/                 build/                   ├── install.bat         ├── data/
├── build_exe.bat        └── (artifacts)          ├── DEPLOYMENT.md       │  └── phoebix_
├── install.bat                                   ├── README.txt          │      desktop.
├── package_release.bat                           ├── VERSION.txt         │      sqlite3
├── sample_state.json                             └── .env.example        └── .env
├── .env.example
└── DEPLOYMENT.md
```

## Database Initialization Flow

```
User launches Phoebix.exe
        ↓
    ┌───────────────────────────────────────┐
    │ main() entry point                    │
    ├───────────────────────────────────────┤
    │ 1. load_environment_file()            │
    │    → Read .env if exists              │
    │                                       │
    │ 2. acquire_single_instance()          │
    │    → Ensure only one running          │
    │                                       │
    │ 3. init_database()  ← NEW!            │
    │    ├─ Database.__init__(path)         │
    │    │  → Create/open SQLite file       │
    │    │                                  │
    │    ├─ conn.executescript(SCHEMA)      │
    │    │  → Create 8 tables (if needed)   │
    │    │                                  │
    │    ├─ bootstrap(db, sample)           │
    │    │  → Seed users & sample data      │
    │    │                                  │
    │    └─ integrity_check()               │
    │       → Verify database ready         │
    │                                       │
    │ 4. Services(database)                 │
    │    → Create service layer             │
    │                                       │
    │ 5. PhoebixApp(services)               │
    │    → Initialize UI                    │
    │                                       │
    │ 6. .mainloop()                        │
    │    → Display login screen             │
    └───────────────────────────────────────┘
        ↓
    Login Screen
        ↓
    Enter: admin / admin123
        ↓
    Forced Password Change
        ↓
    Main Application
```

## Startup Times

```
First Launch (Database Initialization)
├─ Load environment ........... 0.1s
├─ Single instance check ...... 0.1s
├─ Database initialization ... 5-10s ← Includes schema + data
│  ├─ Create database file ........ 0.5s
│  ├─ Create schema ........... 1-2s
│  ├─ Bootstrap data .......... 2-5s
│  └─ Integrity check ......... 0.5s
├─ Services initialization .... 0.5s
├─ UI initialization .......... 1s
└─ Show login screen .......... 0.1s
   TOTAL: 7-12 seconds

Subsequent Launches (Existing Database)
├─ Load environment ........... 0.1s
├─ Single instance check ...... 0.1s
├─ Database connection ........ 0.2s
│  └─ Schema already exists (skip)
├─ Services initialization .... 0.5s
├─ UI initialization .......... 0.5s
└─ Show login screen .......... 0.1s
   TOTAL: 1-2 seconds
```

## Configuration Options

```
.env File Location: %LOCALAPPDATA%\Phoebix\.env

┌─────────────────────────────────────────────────────────┐
│ BASIC CONFIGURATION                                     │
├─────────────────────────────────────────────────────────┤
│ PHOEBIX_ADMIN_PASSWORD=SecurePass123                    │
│   → Auto-set admin password, skip change prompt         │
│   → Must be 8+ characters                               │
│                                                          │
│ PHOEBIX_DB_PATH=/path/to/database.sqlite3              │
│   → Custom database location                            │
│   → Default: %LOCALAPPDATA%\Phoebix\data\               │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ PAYMENT GATEWAY (PhonePe)                               │
├─────────────────────────────────────────────────────────┤
│ PHONEPE_ENV=sandbox|production                          │
│ PHONEPE_CLIENT_ID=your_client_id                        │
│ PHONEPE_CLIENT_SECRET=your_client_secret                │
│ PHONEPE_CLIENT_VERSION=1                                │
└─────────────────────────────────────────────────────────┘
```

## Error Handling

```
Database Initialization Fails
        ↓
┌─────────────────────────────────────────┐
│ "Database initialization failed: ..."   │
│ "The database could not be opened."     │
├─────────────────────────────────────────┤
│ CAUSES:                                 │
│ • No write permission to %LOCALAPPDATA% │
│ • Insufficient disk space               │
│ • Database file corrupted               │
│ • Another process has database locked   │
├─────────────────────────────────────────┤
│ SOLUTIONS:                              │
│ • Check permissions                     │
│ • Free up disk space                    │
│ • Delete database, let it reinitialize  │
│ • Close other Phoebix instances         │
│ • Restart computer                      │
└─────────────────────────────────────────┘
```

## Deployment Decision Tree

```
How many computers?
        ↓
     ┌──┴──┐
     │     │
    1PC  MANY
     │     │
     ↓     ↓
┌────────────────────┐    ┌──────────────────────┐
│ SINGLE MACHINE     │    │ MULTIPLE MACHINES    │
├────────────────────┤    ├──────────────────────┤
│ • Copy Phoebix.exe │    │ Option A: SEPARATE   │
│ • Run directly     │    │ • Copy exe to each   │
│ • Database auto    │    │ • Each has own DB    │
│   initializes      │    │ • Works offline      │
│                    │    │                      │
│ Time: 5 minutes    │    │ Option B: CENTRALIZED
│                    │    │ • Network database   │
│                    │    │ • All access same DB │
│                    │    │ • Setup required     │
└────────────────────┘    └──────────────────────┘
```

## Backup & Recovery

```
BACKUP
┌────────────────────────────────────┐
│ copy "%LOCALAPPDATA%\Phoebix\data  │
│   \phoebix_desktop.sqlite3"        │
│ "D:\Backups\phoebix_backup.sqlite3"│
│                                    │
│ → Keep in multiple locations       │
│ → Test restore procedures          │
│ → Document backup process          │
└────────────────────────────────────┘

RESTORE
┌────────────────────────────────────┐
│ 1. Close Phoebix                   │
│ 2. Delete corrupted database       │
│ 3. Copy backup to data directory   │
│ 4. Restart Phoebix                 │
│ 5. Verify data integrity           │
└────────────────────────────────────┘

FRESH START
┌────────────────────────────────────┐
│ 1. Close Phoebix                   │
│ 2. Delete database file            │
│ 3. Run Phoebix.exe                 │
│ 4. Initializes with sample data    │
│ 5. Start fresh                     │
└────────────────────────────────────┘
```

## Key Files and Their Purpose

| File | Purpose | Size | Type |
|------|---------|------|------|
| Phoebix.exe | Main application | 25-30 MB | Executable |
| install.bat | Interactive installer | 6 KB | Batch script |
| package_release.bat | Release packaging | 3 KB | Batch script |
| DEPLOYMENT.md | User guide | 30 KB | Documentation |
| .env.example | Config template | 4 KB | Configuration |
| phoebix_desktop.sqlite3 | Main database | 2-50 MB | Data |

## Keyboard Shortcuts

```
While login screen visible:
  [Tab]   → Move between fields
  [Enter] → Submit login
  
While in main app:
  Alt+F4 → Close application
  Alt+Tab → Switch windows
  
Navigation (after login):
  Sidebar buttons → Switch screens
```

## Troubleshooting Quick Answers

| Problem | Answer |
|---------|--------|
| Phoebix.exe won't start | Check Windows version (need 10/11) |
| Database won't initialize | Check disk space and permissions |
| Forgot admin password | Delete database, reinitialize |
| App is slow | First launch is slow, normal after |
| Two instances running | Close all windows, check Task Manager |
| Can't connect network DB | Check network path and permissions |
| Antivirus blocks exe | Add to antivirus whitelist |

---

**Print this page as a quick reference during deployment!**
