
# AI AutoTrade Guardian Service - NSSM Registration Script
# Run as Administrator: powershell -ExecutionPolicy Bypass -File register_service.ps1 [-Action install|remove|restart|status]

param(
    [ValidateSet("install", "remove", "restart", "status")]
    [string]$Action = "install"
)

$ServiceName = "AutoTrade_Guardian"
$PythonExe = "D:\ML\venv2\Scripts\python.exe"
$SchedulerScript = "D:\ML\src\main_scheduler.py"
$WorkDir = "D:\ML"
$LogDir = "D:\ML\log"
$NssmExe = (Get-ChildItem -Path "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter "nssm.exe" -ErrorAction SilentlyContinue | Where-Object { $_.DirectoryName -like "*win64*" } | Select-Object -First 1).FullName

Write-Host "--- AI AutoTrade Guardian Service (NSSM) ---" -ForegroundColor Cyan

# Check Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Administrator privileges required! Right-click PowerShell and 'Run as Administrator'."
    exit 1
}

# Check NSSM
if (-not $NssmExe -or -not (Test-Path $NssmExe)) {
    Write-Error "NSSM not found. Install via: winget install NSSM.NSSM"
    exit 1
}
Write-Host "NSSM: $NssmExe"

# --- Status ---
if ($Action -eq "status") {
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    if ($svc) {
        Write-Host "Service: $($svc.Status)" -ForegroundColor $(if ($svc.Status -eq "Running") { "Green" } else { "Yellow" })
    } else {
        Write-Host "Service not installed." -ForegroundColor Red
    }
    exit 0
}

# --- Remove ---
if ($Action -eq "remove") {
    & $NssmExe stop $ServiceName 2>$null
    & $NssmExe remove $ServiceName confirm
    Write-Host "Service removed." -ForegroundColor Green
    exit 0
}

# --- Restart ---
if ($Action -eq "restart") {
    & $NssmExe restart $ServiceName
    Start-Sleep 3
    $svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    Write-Host "Service: $($svc.Status)" -ForegroundColor $(if ($svc.Status -eq "Running") { "Green" } else { "Red" })
    exit 0
}

# --- Install ---
Write-Host "`n[1/4] Cleaning up old services & tasks..."

# Remove old services
foreach ($old in @("AI_AutoTrade_Service", "AI_AutoTrade_Bot", $ServiceName)) {
    $existing = Get-Service -Name $old -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "  Removing: $old"
        & $NssmExe stop $old 2>$null
        & $NssmExe remove $old confirm 2>$null
        & sc.exe delete $old 2>$null
    }
}

# Remove old scheduled tasks
foreach ($task in @("AutoTrade_EarlyAnalysis", "AutoTrade_MorningTrade", "AutoTrade_AfternoonSell", "AutoTrade_WatchDog", "AutoTrade_NightCrawler", "AutoTrade_Guardian")) {
    schtasks /delete /tn $task /f 2>$null | Out-Null
}

Write-Host "[2/4] Installing service..."
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir | Out-Null }

& $NssmExe install $ServiceName $PythonExe "-u $SchedulerScript"
& $NssmExe set $ServiceName AppDirectory $WorkDir
& $NssmExe set $ServiceName DisplayName "AI AutoTrade Guardian Service"
& $NssmExe set $ServiceName Description "AI 자동매매 통합 스케줄러 - 매매, 감시, 뉴스수집, 대시보드 관리"
& $NssmExe set $ServiceName Start SERVICE_AUTO_START

Write-Host "[3/4] Configuring logs..."
& $NssmExe set $ServiceName AppStdout "$LogDir\guardian_service.log"
& $NssmExe set $ServiceName AppStderr "$LogDir\guardian_service_err.log"
& $NssmExe set $ServiceName AppStdoutCreationDisposition 4
& $NssmExe set $ServiceName AppStderrCreationDisposition 4

Write-Host "[4/4] Starting service..."
& $NssmExe start $ServiceName
Start-Sleep 3

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "`nService is RUNNING." -ForegroundColor Green
} else {
    Write-Warning "Service installed but not running. Check: $LogDir\guardian_service_err.log"
}

Write-Host "`n--- Schedule ---"
Write-Host "  08:45  Early Pre-Analysis (morning_screener.py --pre)"
Write-Host "  09:15  Morning Trade (auto_trade_main.py)"
Write-Host "  09:15~ WatchDog daemon (market hours)"
Write-Host "  15:10  Afternoon Sell + Analysis"
Write-Host "  18:00  Night Crawler"
Write-Host "  Always Dashboard (port 8501)"
Write-Host "`nLogs: $LogDir\guardian_service.log"
