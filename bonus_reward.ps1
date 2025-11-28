# Force UTF-8 encoding without BOM for both input and output
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[System.Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# Set encoding for PowerShell and Python
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"


# Define paths
$packagePath = "D:\bonus_reward"
$scriptPath = ".\bonus_reward.py"
$logPath = ".\logs\bonus_reward.log"
$scriptOptions = "--force-restart --stop-chrome-on-exit"

try {
    # Navigate to package directory
    Push-Location $packagePath

    # Creates log directory if it did not exist
    if (-not (Test-Path ".\logs")) {
        New-Item -ItemType Directory ".\logs" | Out-Null
    }
    
    # Activate virtual environment
    & "./venv/Scripts/Activate.ps1"

    # Execute Python script and redirect output only to log file
    cmd /c  "python -u $scriptPath $scriptOptions >> $logPath 2>&1"
    
    # Add completion message with timestamp
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "$timestamp [INFO] bonus_reward.ps1 - Script completed successfully"
    
} catch {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "$timestamp [ERROR] bonus_reward.ps1 - $_"
} finally {
    Pop-Location
}
