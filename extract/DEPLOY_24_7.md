# 🚀 24/7 Automated Scraper Deployment Guide

**Automatic scraping every 24 hours with zero manual intervention**

---

## ⚡ Quick Setup (2 Minutes)

### Step 1: Install Dependencies
```bash
cd D:\E-Commerce_Analytics_Project
pip install -r scheduler_requirements.txt
python -m playwright install
```

### Step 2: Start Scheduler
```bash
cd extract
START_SCHEDULER.bat
```

**That's it!** The scheduler will now run automatically every 24 hours.

---

## 📋 What Happens Automatically

### Every Day
```
00:00 → Myntra scraper starts   (5-15 min)
        ↓ Saves to: ecommerce_myntra_data.csv

02:00 → Ajio scraper starts     (10-20 min)
        ↓ Saves to: ecommerce_ajio_data.csv

04:00 → Snapdeal scraper starts (10-20 min)
        ↓ Saves to: ecommerce_snapdeal_data.csv

06:00 → Flipkart scraper starts (5-15 min)
        ↓ Saves to: ecommerce_flipkart_data.csv

08:00 → Amazon scraper starts   (5-15 min)
        ↓ Saves to: ecommerce_amazon_data.csv
```

**Total Time:** ~60-90 minutes per day  
**Output:** All files in `raw_data/` folder

---

## 📁 Data Storage

### CSV Files Location
```
extract/raw_data/
├── ecommerce_myntra_data.csv      (Updated daily at 00:00)
├── ecommerce_ajio_data.csv        (Updated daily at 02:00)
├── ecommerce_snapdeal_data.csv    (Updated daily at 04:00)
├── ecommerce_flipkart_data.csv    (Updated daily at 06:00)
└── ecommerce_amazon_data.csv      (Updated daily at 08:00)
```

### Log Files Location
```
extract/logs/
├── scheduler.log     (Scheduler events)
├── scraper.log      (Scraper details)
└── errors.log       (Any errors)
```

### Database Location
```
extract/metadata/
└── execution_history.db   (Track all runs)
```

---

## 🎯 Option 1: Simple (Recommended for Development)

### Keep Terminal Running
```bash
cd extract
python cli.py start
```

**Pros:**
- ✅ Simple setup
- ✅ Easy to monitor
- ✅ Can see output in real-time

**Cons:**
- ✗ Terminal must stay open
- ✗ Stops if you close terminal

**When to use:** Development, testing, manual monitoring

---

## 🔧 Option 2: Windows Service (Recommended for Production)

Run 24/7 automatically, even after computer restarts.

### Install as Windows Service

#### Method A: Using NSSM (Recommended)

1. **Download NSSM** from https://nssm.cc/download
2. Extract to `C:\nssm` (or any location)
3. Open Command Prompt as Administrator:

```bash
cd C:\nssm\win64

nssm install EcommerceScraper python.exe cli.py start

nssm set EcommerceScraper AppDirectory "D:\E-Commerce_Analytics_Project\extract"

nssm set EcommerceScraper AppStdout "D:\E-Commerce_Analytics_Project\extract\logs\service.log"

nssm set EcommerceScraper AppStderr "D:\E-Commerce_Analytics_Project\extract\logs\service_error.log"

nssm start EcommerceScraper
```

4. **Verify service is running:**
```bash
nssm query EcommerceScraper
```

5. **Check status in Services:**
   - Open Services (services.msc)
   - Look for "EcommerceScraper"
   - Should show "Running"

**Benefits:**
- ✅ Runs 24/7
- ✅ Auto-restart on crash
- ✅ Auto-start on boot
- ✅ Runs in background
- ✅ View logs anytime

**To Stop Service:**
```bash
nssm stop EcommerceScraper
```

**To Uninstall Service:**
```bash
nssm remove EcommerceScraper confirm
```

---

#### Method B: Windows Task Scheduler

For simpler setup (no NSSM needed):

1. **Open Task Scheduler** (search "Task Scheduler")
2. **Create Basic Task:**
   - Name: "E-Commerce Scraper Scheduler"
   - Description: "Automated 24/7 web scraper"

3. **Set Trigger:**
   - Begin the task: "At startup"
   - Delay: 2 minutes (let system stabilize)

4. **Set Action:**
   - Program/script: `C:\Windows\System32\cmd.exe`
   - Add arguments: `/c "D:\E-Commerce_Analytics_Project\extract\START_SCHEDULER.bat"`
   - Start in: `D:\E-Commerce_Analytics_Project\extract`

5. **Set Conditions:**
   - ✅ Run only if user is logged in
   - ✅ Run with highest privileges

6. **Click OK** to create task

7. **Run immediately to test:**
   - Right-click task → Run

**To Verify:**
- Check `logs/scheduler.log` for activity

---

## 🐧 Option 3: Linux/Mac Deployment

### Using systemd (Linux)

Create `/etc/systemd/system/ecommerce-scraper.service`:

```ini
[Unit]
Description=E-Commerce Scraper Scheduler
After=network.target

[Service]
Type=simple
User=youruser
WorkingDirectory=/home/youruser/E-Commerce_Analytics_Project/extract
ExecStart=/usr/bin/python3 cli.py start
Restart=always
RestartSec=10
StandardOutput=append:/home/youruser/E-Commerce_Analytics_Project/extract/logs/service.log
StandardError=append:/home/youruser/E-Commerce_Analytics_Project/extract/logs/service_error.log

[Install]
WantedBy=multi-user.target
```

**Enable and start:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable ecommerce-scraper.service
sudo systemctl start ecommerce-scraper.service

# Check status
sudo systemctl status ecommerce-scraper.service

# View logs
sudo journalctl -u ecommerce-scraper.service -f
```

---

### Using cron (Linux/Mac)

```bash
crontab -e
```

Add these lines:

```cron
# Run scheduler at system startup
@reboot sleep 30 && cd /home/youruser/E-Commerce_Analytics_Project/extract && python cli.py start >> logs/scheduler.log 2>&1
```

---

## 📊 Monitoring Automated Runs

### Check Status Anytime
```bash
python cli.py status
```

### View Statistics
```bash
python cli.py stats
```

### Check Quality
```bash
python data_quality_checker.py
```

### View Recent Runs
```bash
python cli.py history myntra 20
python cli.py history ajio 10
```

### View Logs
```bash
# Real-time log viewing
tail -f logs/scheduler.log
tail -f logs/errors.log

# Or open files directly
type logs/scheduler.log
type logs/scraper.log
type logs/errors.log
```

---

## 🔍 Troubleshooting

### Check if Scheduler is Running

**Windows:**
```bash
tasklist | findstr python
```

**Linux/Mac:**
```bash
ps aux | grep cli.py
```

### View Recent Errors
```bash
type logs/errors.log
```

### Check Database
```bash
# View last 10 executions for each scraper
python cli.py history myntra 10
python cli.py history ajio 10
```

### Restart Scheduler

**If running in terminal:**
- Press Ctrl+C to stop
- Run `python cli.py start` again

**If running as Windows service:**
```bash
nssm stop EcommerceScraper
nssm start EcommerceScraper
```

---

## 📈 Daily Output

### Files Automatically Generated

Each day at their scheduled times:

```
✅ ecommerce_myntra_data.csv
   - 500-1000 products
   - Updated: 00:00 - 00:15 daily

✅ ecommerce_ajio_data.csv
   - 400-800 products
   - Updated: 02:00 - 02:20 daily

✅ ecommerce_snapdeal_data.csv
   - 400-800 products
   - Updated: 04:00 - 04:20 daily

✅ ecommerce_flipkart_data.csv
   - 400-800 products
   - Updated: 06:00 - 06:15 daily

✅ ecommerce_amazon_data.csv
   - 400-800 products
   - Updated: 08:00 - 08:15 daily
```

### Total Data Generated
- **500,000+ rows per month**
- **~2.5 GB per month** (all data preserved)
- **Complete history in database**

---

## ⚙️ Customization

### Change Schedule Times

Edit `config.py`:

```python
SCRAPER_CONFIG = {
    "myntra": {
        "schedule_hour": 1,       # Change from 0 to 1 (01:00)
        "schedule_minute": 30,    # Change from 0 to 30 (01:30)
    },
}
```

Then restart scheduler.

### Disable a Scraper

```python
SCRAPER_CONFIG = {
    "flipkart": {
        "enabled": False,  # Skip this scraper
    },
}
```

### Change Data Folder

```python
# In config.py, line 8:
DATA_DIR = Path("D:/my_data")  # Custom location
```

---

## 🛡️ Backup Your Data

### Automatic Weekly Backup
```bash
cd raw_data
# Compress all CSVs
tar -czf backup_$(date +%Y%m%d).tar.gz *.csv

# Or on Windows:
# 7-Zip: Right-click → Add to archive
```

### External Backup
- Copy `raw_data/*.csv` to cloud storage weekly
- Copy `metadata/execution_history.db` for tracking

---

## 📊 Data Management

### Archive Old Data
```bash
# Keep last 30 days, archive older data
python cli.py cleanup 30
```

### View Database Stats
```python
from execution_tracker import ExecutionTracker

tracker = ExecutionTracker()
stats = tracker.get_all_stats()

for stat in stats:
    print(f"{stat['scraper_name']}: {stat['total_runs']} runs")
```

---

## 🎯 Performance Metrics

### Expected Daily Performance

| Scraper | Time | Size | Status |
|---------|------|------|--------|
| Myntra | 15 min | ~2-5 MB | ✅ |
| Ajio | 20 min | ~2-5 MB | ✅ |
| Snapdeal | 20 min | ~2-5 MB | ✅ |
| Flipkart | 15 min | ~2-5 MB | ✅ |
| Amazon | 15 min | ~2-5 MB | ✅ |
| **TOTAL** | **~90 min** | **~10-25 MB** | **✅** |

### Monthly Metrics
- **Files Generated:** 5 per day × 30 days = 150 files
- **Data Size:** ~100-300 MB per month
- **Database Size:** ~50-100 MB per month
- **Total:** ~150-400 MB per month

---

## 🚨 Error Handling

### Automatic Recovery

If a scraper fails:
1. **First attempt fails** → Wait 5 minutes → Retry
2. **Second attempt fails** → Wait 10 minutes → Retry
3. **Third attempt fails** → Wait 20 minutes → Retry
4. **All attempts fail** → Log error, continue next scheduled run

### Manual Recovery
```bash
# Run a failed scraper immediately
python cli.py run myntra

# Check what went wrong
type logs/errors.log
```

---

## 📞 Support

### Quick Checks
```bash
# Is scheduler running?
python cli.py status

# Were all scrapers successful?
python cli.py stats

# Any errors?
type logs/errors.log

# Data quality OK?
python data_quality_checker.py
```

### Common Issues

**No CSV files generated:**
- Check `logs/scraper.log` for errors
- Verify internet connection
- Check if scraper websites are accessible

**Scheduler stops unexpectedly:**
- Check `logs/errors.log` for Python errors
- Verify dependencies: `pip install -r ../scheduler_requirements.txt`
- Restart service/terminal

**Old data accumulating:**
- Run cleanup: `python cli.py cleanup 30`
- Archive old files to external storage

---

## 🎉 Summary

### 3 Ways to Deploy

| Method | Setup Time | Effort | Reliability | Best For |
|--------|------------|--------|------------|----------|
| **Terminal** | 1 min | Low | Low | Development |
| **Service (NSSM)** | 10 min | Medium | High | Production |
| **Task Scheduler** | 5 min | Low | Medium | Small deployment |

### Recommended
- **Development:** Keep terminal open, monitor daily
- **Production:** Use NSSM service for 24/7 operation
- **Enterprise:** Use both + backup system + alerts

---

## 🚀 You're Ready!

Choose your deployment method above and start scraping!

### Quick Start
```bash
cd D:\E-Commerce_Analytics_Project\extract
START_SCHEDULER.bat
```

### Verification
- Check `raw_data/` folder for CSV files
- Check `logs/scheduler.log` for activity
- Check `metadata/execution_history.db` for history

**Automated scraping is now running 24/7!** ✅

---

**Need Help?**
- View logs: `type logs/scheduler.log`
- Check status: `python cli.py status`
- Run quality check: `python data_quality_checker.py`

**Documentation:**
- Full guide: `SCHEDULER_README.md`
- Quick start: `QUICK_START.md`
- Quality checker: `DATA_QUALITY_GUIDE.md`
