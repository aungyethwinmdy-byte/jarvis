# Jarvis Android — Flutter SDK Setup Script
# Run this ONCE after E:\flutter_sdk.zip is fully downloaded.
# Usage: powershell -ExecutionPolicy Bypass -File E:\Mark-LIV-main\jarvis_android\setup_flutter.ps1

$ErrorActionPreference = "Stop"

$zipPath  = "E:\flutter_sdk.zip"
$destDir  = "E:\flutter"
$flutterBin = "$destDir\bin"
$projectDir = "E:\Mark-LIV-main\jarvis_android"

Write-Host "=== Step 1: Check zip ===" -ForegroundColor Cyan
if (-not (Test-Path $zipPath)) {
    Write-Host "ERROR: $zipPath not found. Wait for download to complete." -ForegroundColor Red
    exit 1
}
$sizeMB = [Math]::Round((Get-Item $zipPath).Length / 1MB, 0)
Write-Host "Zip size: $sizeMB MB"
if ($sizeMB -lt 900) {
    Write-Host "WARNING: Zip looks too small ($sizeMB MB). Download may be incomplete." -ForegroundColor Yellow
}

Write-Host "`n=== Step 2: Extract Flutter SDK ===" -ForegroundColor Cyan
if (Test-Path $destDir) {
    Write-Host "Removing old $destDir ..."
    Remove-Item $destDir -Recurse -Force
}
Write-Host "Extracting to $destDir (this takes 2-5 min)..."
Expand-Archive -Path $zipPath -DestinationPath "E:\" -Force
Write-Host "Extracted."

Write-Host "`n=== Step 3: Add Flutter to PATH ===" -ForegroundColor Cyan
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if ($userPath -notlike "*$flutterBin*") {
    [Environment]::SetEnvironmentVariable("PATH", "$userPath;$flutterBin", "User")
    Write-Host "Added $flutterBin to user PATH"
} else {
    Write-Host "Already in PATH"
}
$env:PATH = "$env:PATH;$flutterBin"

Write-Host "`n=== Step 4: flutter doctor ===" -ForegroundColor Cyan
& "$flutterBin\flutter.bat" doctor --no-version-check 2>&1

Write-Host "`n=== Step 5: Accept Android licenses ===" -ForegroundColor Cyan
Write-Host "(Type 'y' for each prompt)"
& "$flutterBin\flutter.bat" doctor --android-licenses 2>&1

Write-Host "`n=== Step 6: flutter pub get ===" -ForegroundColor Cyan
Set-Location $projectDir
& "$flutterBin\flutter.bat" pub get 2>&1

Write-Host "`n=== Step 7: flutter analyze ===" -ForegroundColor Cyan
& "$flutterBin\flutter.bat" analyze 2>&1

Write-Host "`n=== Step 8: adb devices ===" -ForegroundColor Cyan
$adbExe = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter "adb.exe" -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty FullName
if ($adbExe) {
    & $adbExe devices
} else {
    Write-Host "adb not found in WinGet packages"
}

Write-Host "`n=== Setup complete! ===" -ForegroundColor Green
Write-Host "Next: Connect phone via USB (USB debugging on), then run:"
Write-Host "  cd E:\Mark-LIV-main\jarvis_android"
Write-Host "  flutter run"
Write-Host ""
Write-Host "Make sure VPN is active on the phone before testing Live API connection."
