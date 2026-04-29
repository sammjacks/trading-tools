# Windows Fresh Reset Kit (Custom App Restore)

This kit is tailored to your requirement:
- Keep a **clean reset**
- Reinstall only approved apps (including Chrome, Git, Directory Opus, and Microsoft Office)
- Restore your VS Code setup
- Reapply lightweight Windows performance settings (reduced animations)

Python is pinned to your current version: **3.13.2** (with a fallback to latest 3.13 if that exact build is unavailable in winget).

## Files
- `01_pre_reset_backup.ps1` - Run before reset. Exports app/config data.
- `02_post_reset_install.ps1` - Run after reset. Reinstalls approved apps and restores VS Code.
- `03_post_reset_tweaks.ps1` - Run after reset. Applies low-overhead UI/performance tweaks.

## 1) Before resetting Windows
1. Open PowerShell as your normal user (not required to be admin for backup).
2. Run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\01_pre_reset_backup.ps1 -BackupRoot "D:\RESET_KIT"
```

3. Confirm `D:\RESET_KIT` contains exported files.
4. Keep this folder on external drive / cloud.

## 2) Reset Windows
Use Windows Reset and choose full clean reset per your preference.

## 3) After reset (in order)
1. Install latest Windows updates first.
2. Open PowerShell as Administrator in this folder.
3. Before app reinstall, put manual installers in:

```text
D:\RESET_KIT\manual_installers
```

Manual installer checklist (what the script checks):
- Required: Directory Opus (filename contains `opus`)
- Required: Tick Data Suite (filename contains `tick` + `data` + `suite`)
- Optional: Microsoft Office (filename contains `office`)

4. Run app reinstall:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\02_post_reset_install.ps1 -BackupRoot "D:\RESET_KIT"
```

The script will pause and keep reminding you until files are present in the manual installer folder (or you type `SKIP`).

5. Run performance tweaks:

```powershell
.\03_post_reset_tweaks.ps1
```

6. Sign in where needed (Google Drive, Dropbox, Telegram, TickTick, Steam, VPNs).

## Notes
- Some apps may prompt for manual login/license activation.
- If a package ID changes in winget, the script will continue and print what failed.
- `Tick Data Suite` may require manual installer/license depending on vendor distribution.
