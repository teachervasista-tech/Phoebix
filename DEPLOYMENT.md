# Phoebix Pharmacy App - Windows Deployment Guide

This guide explains how to build and deploy the Phoebix pharmacy management system on Windows computers.

## System Requirements

- **Windows 10/11** (64-bit)
- **Disk Space**: 200 MB minimum
- **RAM**: 2 GB minimum
- No additional software required (Python not needed on target machines)

## Building the Release

### On Development Machine

1. **Prerequisites**: Python 3.10+ must be installed
   ```cmd
   python --version
   ```

2. **Build the executable**:
   ```cmd
   cd C:\path\to\Phoebix
   build_exe.bat
   ```

3. The build process will:
   - Install/upgrade PyInstaller
   - Clean previous builds
   - Compile the application to `dist\Phoebix.exe`
   - Display build status and size

4. **Verify the build**:
   ```cmd
   dir dist\Phoebix.exe
   dist\Phoebix.exe
   ```

## Deployment on New Computers

### Simple Single-File Deployment

The entire application is packaged in a single `.exe` file with no external dependencies:

1. **Copy to target computer**:
   - Transfer `dist\Phoebix.exe` to the target machine
   - No need to copy any other files
   - Can be placed anywhere on the computer

2. **Run the application**:
   - Double-click `Phoebix.exe`
   - On first launch, the application will:
     - Create data directory at `%LOCALAPPDATA%\Phoebix\data\`
     - Initialize empty SQLite database: `phoebix_desktop.sqlite3`
     - Create schema tables
     - Load sample data
     - Seed default user accounts

3. **Wait for startup**:
   - Database initialization takes 2-5 seconds on first run
   - Subsequent launches are faster (< 1 second)

### Initial Setup Steps

1. **First Login**:
   - Username: `admin`
   - Password: `admin123` (temporary)

2. **Set New Password**:
   - The app will prompt you to set a new password on first login
   - Password must be 8+ characters
   - Only administrators can change user passwords later

3. **Secondary User**:
   - Username: `cashier`
   - Password: `cashier123` (temporary)
   - This account is a staff member with limited permissions

4. **Customize Settings**:
   - Go to Settings → Store Profile
   - Update pharmacy name and details
   - Configure bank account for payments (if using PhonePe)

## Database Location

The database and configuration files are stored in:
```
%LOCALAPPDATA%\Phoebix\
├── data\
│   └── phoebix_desktop.sqlite3    (main database)
└── .env                            (optional configuration)
```

### Find Your Phoebix Folder
- Press `Win + R`, type: `%LOCALAPPDATA%\Phoebix`, click OK
- Or: `C:\Users\YourUsername\AppData\Local\Phoebix\`

## Environment Configuration

### Optional .env File

Create `.env` in `%LOCALAPPDATA%\Phoebix\` for configuration:

```env
# Database path (default: %LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3)
PHOEBIX_DB_PATH=/path/to/database.sqlite3

# Admin password on first run (skips password change prompt)
PHOEBIX_ADMIN_PASSWORD=YourSecurePassword123

# PhonePe payment gateway
PHONEPE_ENV=sandbox
PHONEPE_CLIENT_ID=your_client_id
PHONEPE_CLIENT_SECRET=your_client_secret
PHONEPE_CLIENT_VERSION=1
```

**Note**: Create this file BEFORE first run to auto-set passwords and payment credentials.

## Single Instance Lock

The application enforces a single instance per computer:
- If Phoebix is already running, attempting to launch another instance shows a message
- This prevents database conflicts
- Close the first instance to launch a new one

## Backup and Data Recovery

### Regular Backups

The database is critical. Regular backups are recommended:

1. **Manual backup**:
   ```cmd
   copy "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3" "D:\Backups\phoebix_backup.sqlite3"
   ```

2. **Automated backup** (Windows Task Scheduler):
   - Create a batch file to copy the database
   - Schedule it to run daily after closing time

### Database Restoration

If the database becomes corrupted or you need to restore from backup:

1. Close Phoebix completely
2. Replace the corrupted database:
   ```cmd
   copy "D:\Backups\phoebix_backup.sqlite3" "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3"
   ```
3. Restart Phoebix

### Fresh Start (Clear All Data)

To reset the application and start fresh:

1. Close Phoebix
2. Delete the database:
   ```cmd
   del "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3"
   ```
3. Restart Phoebix (it will re-initialize with sample data and default users)

## Uninstallation

Phoebix has no installer and creates no registry entries:

1. Delete `Phoebix.exe`
2. (Optional) Delete `%LOCALAPPDATA%\Phoebix\` to remove all data

## Troubleshooting

### Database Initialization Fails

**Error**: "The database could not be initialized"

- Check disk space in `%LOCALAPPDATA%\` (need ~50 MB minimum)
- Ensure write permissions to `%LOCALAPPDATA%\Phoebix\`
- Try deleting the database and let it reinitialize:
  ```cmd
  del "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3"
  ```

### Cannot Start - Database Already In Use

**Error**: "Phoebix is already open on this computer"

- Close all Phoebix windows
- Check Task Manager for running `python.exe` or `Phoebix.exe` processes
- Kill any orphaned processes

### Slow Startup

- First startup is slower due to database initialization
- Check system resources (RAM, disk speed)
- Subsequent launches should be much faster

### Data Corruption

If experiencing crashes or data integrity errors:

1. Close the application
2. Run database repair:
   ```cmd
   sqlite3 "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3" "PRAGMA integrity_check;"
   ```
3. If repair fails, restore from backup or reinitialize

## Upgrading

To upgrade to a new version:

1. Backup current database:
   ```cmd
   copy "%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3" "phoebix_backup.sqlite3"
   ```

2. Replace `Phoebix.exe` with the new version

3. Run the new version - it will automatically upgrade the database schema if needed

4. If issues occur, restore from backup and try again

## Support

For issues or questions:

1. Check that you have the latest build of `Phoebix.exe`
2. Verify Windows has the latest updates
3. Ensure sufficient disk space and permissions
4. Check the Phoebix GitHub issues page for known problems

## Technical Details

### Database

- **Type**: SQLite 3
- **Location**: `%LOCALAPPDATA%\Phoebix\data\phoebix_desktop.sqlite3`
- **Size**: ~2 MB (grows with data)
- **Locking**: WAL (Write-Ahead Logging) mode for reliability
- **Transactions**: ACID compliant

### Startup Sequence

1. Load environment configuration (`.env`)
2. Check for existing instance
3. **Initialize database** (CREATE SCHEMA IF NOT EXISTS)
4. **Bootstrap data** (seed default users and sample data)
5. Verify database integrity
6. Start UI services
7. Display login screen

### File Locations

| File | Location | Purpose |
|------|----------|---------|
| `Phoebix.exe` | Any location | Application executable |
| `phoebix_desktop.sqlite3` | `%LOCALAPPDATA%\Phoebix\data\` | Main database |
| `.env` | `%LOCALAPPDATA%\Phoebix\` | Optional configuration |
| `sample_state.json` | Embedded in exe | Initial sample data |
