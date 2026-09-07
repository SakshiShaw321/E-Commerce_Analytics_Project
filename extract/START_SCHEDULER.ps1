# ============================================================================
# E-Commerce Scraper Scheduler - PowerShell Startup Script
# Runs all 5 scrapers automatically every 24 hours
# Output: extract/raw_data/*.csv
# ============================================================================

Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host "STARTING AUTOMATED E-COMMERCE SCRAPER SCHEDULER" -ForegroundColor Cyan
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Run Myntra scraper at 10:00" -ForegroundColor White
Write-Host "  2. Run Ajio scraper at 11:00" -ForegroundColor White
Write-Host "  3. Run Snapdeal scraper at 12:00" -ForegroundColor White
Write-Host "  4. Run Flipkart scraper at 13:00" -ForegroundColor White
Write-Host "  5. Run Amazon scraper at 14:00" -ForegroundColor White
Write-Host ""
Write-Host "All data will be saved to: extract/raw_data/" -ForegroundColor Green
Write-Host ""
Write-Host "To stop: Press Ctrl+C" -ForegroundColor Yellow
Write-Host ""
Write-Host "================================================================================" -ForegroundColor Cyan
Write-Host ""

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Python found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Python is not installed or not in PATH" -ForegroundColor Red
    Write-Host "Please install Python 3.10+ from python.org" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# Check if dependencies are installed
Write-Host "Checking dependencies..." -ForegroundColor Cyan
python -c "import apscheduler" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing required dependencies..." -ForegroundColor Yellow
    pip install -r ..\scheduler_requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install dependencies" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}

Write-Host "Starting scheduler..." -ForegroundColor Green
Write-Host ""

# Start the scheduler
python cli.py start

# Pause if script ends unexpectedly
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Scheduler stopped unexpectedly" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
