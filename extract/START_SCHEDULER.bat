@echo off
REM ============================================================================
REM E-Commerce Scraper Scheduler - Start Script
REM Runs all 5 scrapers automatically every 24 hours
REM Output: extract/raw_data/*.csv
REM ============================================================================

echo.
echo ============================================================================
echo STARTING AUTOMATED E-COMMERCE SCRAPER SCHEDULER
echo ============================================================================
echo.
echo This script will:
echo   1. Run Myntra scraper at 00:00 (midnight)
echo   2. Run Ajio scraper at 02:00
echo   3. Run Snapdeal scraper at 04:00
echo   4. Run Flipkart scraper at 06:00
echo   5. Run Amazon scraper at 08:00
echo.
echo All data will be saved to: extract/raw_data/
echo.
echo To stop: Press Ctrl+C
echo.
echo ============================================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

REM Check if dependencies are installed
python -c "import apscheduler" >nul 2>&1
if errorlevel 1 (
    echo.
    echo Installing required dependencies...
    pip install -r "../scheduler_requirements.txt"
    if errorlevel 1 (
        echo ERROR: Failed to install dependencies
        pause
        exit /b 1
    )
)

REM Start the scheduler
echo Starting scheduler...
echo.
python cli.py start

pause
