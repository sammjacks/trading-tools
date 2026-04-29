param(
    [Parameter(Mandatory = $false)]
    [string]$BackupRoot = "D:\RESET_KIT",
    [Parameter(Mandatory = $false)]
    [string]$BackupFolder = "",
    [Parameter(Mandatory = $false)]
    [string]$ManualInstallerRoot = "",
    [Parameter(Mandatory = $false)]
    [switch]$SkipManualInstallerPrecheck
)

$ErrorActionPreference = "Continue"

$PythonExactVersion = "3.13.2"
$ManualInstallerChecklist = @(
    @{ Name = "mRemoteNG XML export"; Pattern = "*mRemoteNG*.xml"; Optional = $false },
    @{ Name = "WireGuard tunnel .conf"; Pattern = "*.conf"; Optional = $false },
    @{ Name = "Directory Opus"; Pattern = "*opus*"; Optional = $true },
    @{ Name = "Tick Data Suite"; Pattern = "*tick*data*suite*"; Optional = $true },
    @{ Name = "Microsoft Office"; Pattern = "*office*"; Optional = $true }
)

function Install-WingetPackage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,
        [Parameter(Mandatory = $false)]
        [string]$Name = ""
    )

    Write-Host "Installing $Id ..."
    winget install --id $Id --exact --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-Warning "Failed to install $Id ($Name)."
    return $false
}

function Install-WingetPackageWithVersion {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Id,
        [Parameter(Mandatory = $true)]
        [string]$Version,
        [Parameter(Mandatory = $false)]
        [string]$Name = ""
    )

    Write-Host "Installing $Id version $Version ..."
    winget install --id $Id --exact --version $Version --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -eq 0) {
        return $true
    }

    Write-Warning "Failed to install $Id version $Version ($Name)."
    return $false
}

function Install-WingetPackageFromList {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Ids,
        [Parameter(Mandatory = $false)]
        [string]$Name = ""
    )

    foreach ($id in $Ids) {
        if (Install-WingetPackage -Id $id -Name $Name) {
            return $true
        }
    }

    Write-Warning "All fallback package IDs failed for $Name"
    return $false
}

function Get-ManualInstallerChecklistStatus {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Root,
        [Parameter(Mandatory = $true)]
        [object[]]$Checklist
    )

    $results = @()
    foreach ($item in $Checklist) {
        $matches = Get-ChildItem -Path $Root -File -Recurse -ErrorAction SilentlyContinue | Where-Object { $_.Name -like $item.Pattern }
        $count = @($matches).Count
        $status = if ($count -gt 0) {
            "FOUND"
        } elseif ($item.Optional) {
            "OPTIONAL-MISSING"
        } else {
            "REQUIRED-MISSING"
        }

        $results += [PSCustomObject]@{
            Name = $item.Name
            Pattern = $item.Pattern
            Required = -not $item.Optional
            Status = $status
            Count = $count
            Files = (@($matches | Select-Object -ExpandProperty Name) -join "; ")
        }
    }

    return $results
}

function Show-ManualInstallerChecklist {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$ChecklistStatus
    )

    Write-Host "Manual installer checklist status:"
    $ChecklistStatus | Select-Object Name, Required, Status, Count, Pattern | Format-Table -AutoSize | Out-Host
}

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "winget not found. Install App Installer from Microsoft Store first."
}

if ([string]::IsNullOrWhiteSpace($ManualInstallerRoot)) {
    $ManualInstallerRoot = Join-Path $BackupRoot "manual_installers"
}

if (-not (Test-Path $ManualInstallerRoot)) {
    New-Item -ItemType Directory -Path $ManualInstallerRoot -Force | Out-Null
}

$initialChecklistStatus = Get-ManualInstallerChecklistStatus -Root $ManualInstallerRoot -Checklist $ManualInstallerChecklist
Show-ManualInstallerChecklist -ChecklistStatus $initialChecklistStatus

if (-not $SkipManualInstallerPrecheck) {
    Write-Host "Manual installer pre-check"
    Write-Host "Place manual installers in: $ManualInstallerRoot"

    while ($true) {
        $checklistStatus = Get-ManualInstallerChecklistStatus -Root $ManualInstallerRoot -Checklist $ManualInstallerChecklist
        Show-ManualInstallerChecklist -ChecklistStatus $checklistStatus

        $requiredMissing = @($checklistStatus | Where-Object { $_.Status -eq "REQUIRED-MISSING" })
        if ($requiredMissing.Count -eq 0) {
            $files = Get-ChildItem -Path $ManualInstallerRoot -File -Recurse -ErrorAction SilentlyContinue
            Write-Host "Ready. Detected $($files.Count) file(s) in manual installer folder."
            break
        }

        Write-Warning "Required manual installers are still missing."
        $response = Read-Host "Copy missing installers, then press Enter to re-check (or type SKIP to continue anyway)"
        if ($response -match '^(?i)skip$') {
            Write-Warning "Continuing without staged manual installers."
            break
        }
    }
}

Write-Host "Installing approved applications..."

# Core development stack
Install-WingetPackage -Id "Anaconda.Anaconda3" -Name "Anaconda"
if (-not (Install-WingetPackageWithVersion -Id "Python.Python.3.13" -Version $PythonExactVersion -Name "Python")) {
    Write-Warning "Exact Python version install failed. Falling back to latest Python 3.13."
    Install-WingetPackage -Id "Python.Python.3.13" -Name "Python"
}
Install-WingetPackage -Id "Microsoft.VisualStudioCode" -Name "VS Code"
Install-WingetPackage -Id "Google.Chrome" -Name "Google Chrome"
Install-WingetPackage -Id "Git.Git" -Name "Git"

# Sync/storage/comms/productivity
Install-WingetPackage -Id "Google.Drive" -Name "Google Drive"
Install-WingetPackage -Id "Dropbox.Dropbox" -Name "Dropbox"
Install-WingetPackage -Id "Microsoft.PowerToys" -Name "PowerToys"
Install-WingetPackage -Id "Telegram.TelegramDesktop" -Name "Telegram"
Install-WingetPackage -Id "Appest.TickTick" -Name "TickTick"
Install-WingetPackage -Id "mRemoteNG.mRemoteNG" -Name "mRemoteNG"
$directoryOpusInstalled = Install-WingetPackageFromList -Ids @("GPSoftware.DirectoryOpus", "DirectoryOpus.DirectoryOpus") -Name "Directory Opus"

# Trading/network/security/media/tools
Install-WingetPackage -Id "WireGuard.WireGuard" -Name "WireGuard"
Install-WingetPackage -Id "Valve.Steam" -Name "Steam"
Install-WingetPackage -Id "WinMerge.WinMerge" -Name "WinMerge"
Install-WingetPackage -Id "OBSProject.OBSStudio" -Name "OBS Studio"
Install-WingetPackage -Id "NordSecurity.NordVPN" -Name "NordVPN"
$officeInstalled = Install-WingetPackageFromList -Ids @("Microsoft.Office", "Microsoft.Office.Desktop") -Name "Microsoft Office"

Write-Host "Attempting Tick Data Suite install via winget (may not be available)..."
$tickDataSuiteInstalled = Install-WingetPackage -Id "StrategyQuant.TickDataSuite" -Name "Tick Data Suite"

if (-not $directoryOpusInstalled -or -not $officeInstalled -or -not $tickDataSuiteInstalled) {
    Write-Warning "One or more apps failed via winget. Use staged installers from: $ManualInstallerRoot"
    if (-not $directoryOpusInstalled) {
        Write-Warning " - Directory Opus"
    }
    if (-not $officeInstalled) {
        Write-Warning " - Microsoft Office"
    }
    if (-not $tickDataSuiteInstalled) {
        Write-Warning " - Tick Data Suite"
    }
}

Write-Host "Locating latest backup folder..."
if ([string]::IsNullOrWhiteSpace($BackupFolder)) {
    $candidate = Get-ChildItem -Path $BackupRoot -Directory -Filter "backup_*" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($null -eq $candidate) {
        Write-Warning "No backup_* folder found in $BackupRoot. Skipping restore of configs."
        exit 0
    }
    $backupPath = $candidate.FullName
} else {
    $backupPath = Join-Path $BackupRoot $BackupFolder
}

Write-Host "Using backup: $backupPath"

# Restore VS Code user settings
$vscodeBackup = Join-Path $backupPath "vscode\User"
$vscodeTarget = Join-Path $env:APPDATA "Code\User"
if (Test-Path $vscodeBackup) {
    New-Item -ItemType Directory -Path $vscodeTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $vscodeBackup "*") -Destination $vscodeTarget -Recurse -Force
}

# Restore VS Code extensions
$extFile = Join-Path $backupPath "vscode\extensions.txt"
if (Test-Path $extFile) {
    Get-Content $extFile | ForEach-Object {
        if (-not [string]::IsNullOrWhiteSpace($_)) {
            try {
                code --install-extension $_ --force
            } catch {
                Write-Warning "Failed to install VS Code extension: $_"
            }
        }
    }
}

# Restore app configs (best-effort)
$configSrc = Join-Path $backupPath "configs"
if (Test-Path $configSrc) {
    $map = @(
        @{ Src = "WireGuard"; Dst = Join-Path $env:LOCALAPPDATA "WireGuard" },
        @{ Src = "PowerToys"; Dst = Join-Path $env:LOCALAPPDATA "Microsoft\PowerToys" },
        @{ Src = "OBS"; Dst = Join-Path $env:APPDATA "obs-studio" },
        @{ Src = "Telegram"; Dst = Join-Path $env:APPDATA "Telegram Desktop" },
        @{ Src = "TickTick"; Dst = Join-Path $env:APPDATA "TickTick" },
        @{ Src = "WinMerge"; Dst = Join-Path $env:APPDATA "WinMerge" },
        @{ Src = "mRemoteNG"; Dst = Join-Path $env:APPDATA "mRemoteNG" }
    )

    foreach ($entry in $map) {
        $srcPath = Join-Path $configSrc $entry.Src
        if (Test-Path $srcPath) {
            New-Item -ItemType Directory -Path $entry.Dst -Force | Out-Null
            Copy-Item -Path (Join-Path $srcPath "*") -Destination $entry.Dst -Recurse -Force
        }
    }
}

# Restore mRemoteNG connections from manual_installers XML export
Write-Host "Restoring mRemoteNG connections from manual installer XML..."
$mRemoteNGXml = Get-ChildItem -Path $ManualInstallerRoot -Filter "*mRemoteNG*.xml" -File -Recurse | Select-Object -First 1
if ($mRemoteNGXml) {
    $mRemoteNGDst = Join-Path $env:APPDATA "mRemoteNG"
    New-Item -ItemType Directory -Path $mRemoteNGDst -Force | Out-Null
    Copy-Item -Path $mRemoteNGXml.FullName -Destination (Join-Path $mRemoteNGDst "confCons.xml") -Force
    Write-Host "  mRemoteNG connections restored from: $($mRemoteNGXml.Name)"
} else {
    Write-Warning "mRemoteNG XML export not found in $ManualInstallerRoot - restore connections manually."
}

# Import WireGuard .conf tunnel(s) from manual_installers
Write-Host "Importing WireGuard tunnel configs..."
$wgConfs = Get-ChildItem -Path $ManualInstallerRoot -Filter "*.conf" -File -Recurse
if ($wgConfs) {
    foreach ($conf in $wgConfs) {
        Write-Host "  Importing tunnel: $($conf.Name)"
        & "C:\Program Files\WireGuard\wireguard.exe" /installtunnelservice $conf.FullName
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "  Auto-import failed for $($conf.Name). Open WireGuard app and import manually: File > Import tunnel(s) from file."
        }
    }
} else {
    Write-Warning "No .conf tunnel files found in $ManualInstallerRoot. Import tunnels manually in the WireGuard app."
}

Write-Host ""
Write-Host "Post-reset install and restore complete."
Write-Host "Manual steps if not auto-completed:"
Write-Host "  - Sign in to Google Drive and let it sync"
Write-Host "  - Activate Tick Data Suite license"
Write-Host "  - Verify mRemoteNG connections loaded (File > Open > confCons.xml if not auto-loaded)"
Write-Host "  - Check WireGuard tunnel is listed and activate it"
