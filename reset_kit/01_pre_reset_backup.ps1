param(
    [Parameter(Mandatory = $false)]
    [string]$BackupRoot = "D:\RESET_KIT"
)

$ErrorActionPreference = "Continue"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$dest = Join-Path $BackupRoot "backup_$timestamp"

New-Item -ItemType Directory -Path $dest -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest "vscode") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest "python") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest "configs") -Force | Out-Null

Write-Host "[1/8] Exporting winget package snapshot..."
try {
    winget export -o (Join-Path $dest "winget_all_packages.json") --include-versions --accept-source-agreements
} catch {
    Write-Warning "winget export failed: $($_.Exception.Message)"
}

Write-Host "[2/8] Exporting VS Code extension list..."
try {
    code --list-extensions | Out-File -FilePath (Join-Path $dest "vscode\extensions.txt") -Encoding ascii
} catch {
    Write-Warning "VS Code extension export failed. Is 'code' in PATH?"
}

Write-Host "[3/8] Copying VS Code user settings..."
$vscodeUser = Join-Path $env:APPDATA "Code\User"
if (Test-Path $vscodeUser) {
    Copy-Item -Path $vscodeUser -Destination (Join-Path $dest "vscode\User") -Recurse -Force
} else {
    Write-Warning "VS Code user folder not found at $vscodeUser"
}

Write-Host "[4/8] Exporting Python packages (pip)..."
try {
    pip freeze | Out-File -FilePath (Join-Path $dest "python\pip_freeze.txt") -Encoding ascii
} catch {
    Write-Warning "pip freeze failed"
}

Write-Host "[5/8] Exporting conda environments (if available)..."
try {
    conda env list | Out-File -FilePath (Join-Path $dest "python\conda_env_list.txt") -Encoding ascii
    conda env export --name base | Out-File -FilePath (Join-Path $dest "python\conda_base_env.yml") -Encoding ascii
} catch {
    Write-Warning "Conda export skipped (conda not found or failed)."
}

Write-Host "[6/8] Backing up selected app config folders..."
$configPaths = @(
    @{ Name = "WireGuard"; Path = Join-Path $env:LOCALAPPDATA "WireGuard" },
    @{ Name = "PowerToys"; Path = Join-Path $env:LOCALAPPDATA "Microsoft\PowerToys" },
    @{ Name = "OBS"; Path = Join-Path $env:APPDATA "obs-studio" },
    @{ Name = "Telegram"; Path = Join-Path $env:APPDATA "Telegram Desktop" },
    @{ Name = "TickTick"; Path = Join-Path $env:APPDATA "TickTick" },
    @{ Name = "WinMerge"; Path = Join-Path $env:APPDATA "WinMerge" }
)

foreach ($item in $configPaths) {
    if (Test-Path $item.Path) {
        Copy-Item -Path $item.Path -Destination (Join-Path $dest "configs\$($item.Name)") -Recurse -Force
    }
}

Write-Host "[7/8] Exporting useful registry keys..."
$regDest = Join-Path $dest "configs"
reg export "HKCU\Software\Thingamahoochie\WinMerge" (Join-Path $regDest "winmerge.reg") /y | Out-Null
reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects" (Join-Path $regDest "visual_effects.reg") /y | Out-Null
reg export "HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize" (Join-Path $regDest "personalize.reg") /y | Out-Null

Write-Host "[8/8] Capturing quick system context..."
Get-ComputerInfo | Out-File -FilePath (Join-Path $dest "system_info.txt") -Encoding ascii

Write-Host "Backup complete: $dest"
Write-Host "Copy this folder to external/cloud before reset."
