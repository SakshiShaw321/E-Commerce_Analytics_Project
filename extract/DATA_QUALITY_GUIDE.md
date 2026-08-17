# Data Quality Checker - Quick Guide

Monitor your scraper data quality with automated checks.

## Quick Start

### Run Quality Check on All Files
```bash
python data_quality_checker.py
```

### Check Specific File
```bash
python data_quality_checker.py --file raw_data/ecommerce_myntra_data.csv
```

### Check Specific Directory
```bash
python data_quality_checker.py --data-dir ./raw_data
```

## Understanding the Report

### File Summary Table

Shows overview of all CSV files:

```
File                  Rows    Columns    Quality           Status
myntra_data.csv       500     22         FAIR ⭐⭐⭐       OK
ajio_data.csv         450     22         FAIR ⭐⭐⭐       OK
```

### Quality Scores

- **EXCELLENT** ⭐⭐⭐⭐⭐ (95%+) - All data present
- **GOOD** ⭐⭐⭐⭐ (85-94%) - Minor gaps
- **FAIR** ⭐⭐⭐ (75-84%) - Expected gaps in search-only mode
- **POOR** ⭐⭐ (60-74%) - Use --full mode to improve
- **CRITICAL** ⭐ (<60%) - Needs investigation

### Column Status Legend

- **✓** Column is well-populated (80%+)
- **⚠** Column has gaps (0-79%)

### Critical Fields Check

Lists any important fields that are below expected fill rates:

```
Critical Field Issues:
  ⚠ seller: 0/500 filled (expected 50%, got 0%)
```

If no issues shown:
```
Critical Fields: ✓ All critical fields OK
```

## Interpreting Results

### High Null Count (0% fill rate)

**Cause 1: Search-Only Mode**
```
⚠ seller    0/500 (0%)     ← Seller not in search results
⚠ description 0/500 (0%)   ← Description requires product page
```
**Solution:** Add `--full` flag when running scraper
```bash
python myntra_scraper.py --full
```

**Cause 2: Data Not Available**
```
⚠ seller    0/500 (0%)     ← Ajio doesn't provide seller info in API
```
**Solution:** Use different attribute or scraper

### Partially Filled (20-80% fill rate)

**Cause 1: Data Inferred from Product Name**
```
✓ fabric    300/500 (60%)  ← Inferred from title (e.g., "Cotton Shirt")
✓ fit_type  325/500 (65%)  ← Inferred from title (e.g., "Slim Fit")
```
**Solution:** Expected behavior, fill rate acceptable

**Cause 2: Inconsistent Availability**
```
⚠ rating    400/500 (80%)  ← Some products missing ratings
```
**Solution:** Investigate individual products with missing data

### Complete Data (100% fill rate)

```
✓ product_name   500/500 (100%)  ← Perfect
✓ price          500/500 (100%)  ← Perfect
✓ availability   500/500 (100%)  ← Perfect
```

This is expected and good!

## Recommendations Interpretation

### Example 1: Missing Attributes in Search-Only Mode

```
1. Myntra: Missing data in sleeve_type, description, seller.
   These require fetching product detail pages.
```

**Action:** Run with `--full` flag if you need those fields
```bash
python myntra_scraper.py --full --output detailed_myntra_data.csv
```

### Example 2: Low Overall Quality

```
3. Flipkart has overall low data quality (60.0%).
   Consider using --full mode to fetch complete product details.
```

**Action:** Enable full mode in `config.py` or run:
```bash
python flipkart_scraper.py --full
```

### Example 3: All Good!

```
All scrapers are performing well! ✓
```

**Action:** No changes needed, continue monitoring

## Common Scenarios

### Scenario 1: Daily Pricing Tracking

**Need:** Price, discount, availability, ratings

**Check Output Should Show:**
- ✓ price: 100%
- ✓ availability: 90%+
- ✓ discount_percent: 100%
- ✓ rating: 80%+

**If Missing:** Adjust scraper configuration or add `--full` mode

### Scenario 2: Product Catalog

**Need:** All attributes (size, fit, fabric, color, etc.)

**Check Output Should Show:**
- ✓ size_options: 90%+
- ✓ fit_type: 90%+
- ✓ fabric: 90%+
- ✓ sleeve_type: 80%+

**If Missing:** Run with `--full` flag

### Scenario 3: Seller Analytics

**Need:** Seller information

**Check Output Should Show:**
- ✓ seller: 50%+ (varies by scraper)

**If Missing:** Seller info not available in search-only mode
- Use `--full` mode (may still not be available)
- Consider using multiple scraper runs

## Running Regular Quality Checks

### Automated Weekly Check

Create a script `check_quality.py`:

```python
from data_quality_checker import DataQualityChecker
from datetime import datetime

checker = DataQualityChecker('raw_data')
results = checker.analyze_all()

# Save report with timestamp
timestamp = datetime.now().strftime('%Y-%m-%d')
with open(f'quality_reports/report_{timestamp}.txt', 'w') as f:
    # Redirect print to file
    import sys
    sys.stdout = f
    checker.print_report(results)
    sys.stdout = sys.__stdout__

print("Quality report saved!")
```

Run weekly:
```bash
python check_quality.py
```

### Email Alert on Poor Quality

```python
from data_quality_checker import DataQualityChecker
import smtplib

checker = DataQualityChecker('raw_data')
results = checker.analyze_all()

# Check for poor quality
for filename, data in results.items():
    if data.get('status') == 'OK':
        quality = data.get('quality_score', '')
        if 'POOR' in quality or 'CRITICAL' in quality:
            # Send alert email
            send_alert_email(filename, data)
```

## Troubleshooting

### Error: "No CSV files found"

**Problem:** The data directory doesn't exist or is empty

**Solution:**
```bash
# First, run a scraper to generate data
python myntra_scraper.py --output raw_data/ecommerce_myntra_data.csv

# Then run quality check
python data_quality_checker.py --data-dir raw_data
```

### Error: "File not found: raw_data/file.csv"

**Problem:** Specified file doesn't exist

**Solution:**
```bash
# Check what files exist
dir raw_data

# Use correct filename
python data_quality_checker.py --file raw_data/ecommerce_myntra_data.csv
```

### All Fields Show 0% Fill

**Problem:** Data might be corrupted or format wrong

**Solution:**
1. Check the CSV file directly:
   ```bash
   type raw_data/ecommerce_myntra_data.csv | head -3
   ```

2. Re-run the scraper to regenerate data:
   ```bash
   python myntra_scraper.py
   ```

3. Check scraper logs for errors:
   ```bash
   type logs/errors.log
   ```

## Metrics to Monitor

### Weekly Targets

| Metric | Target | Alert If |
|--------|--------|----------|
| Overall Fill Rate | 75%+ | <70% |
| Critical Fields | 100% | <95% |
| No. of Errors | 0 | >3 |
| Execution Time | <30min | >60min |
| Products Scraped | 500+ | <100 |

### Monthly Review

1. **Trend Analysis**
   - Are fill rates improving or declining?
   - Do certain fields consistently have gaps?
   - Are specific scrapers underperforming?

2. **Recommendations**
   - Identify scraper configuration improvements
   - Plan for full-mode execution if needed
   - Investigate persistent null values

3. **Action Items**
   - Update scraper parameters
   - Adjust retry thresholds
   - Modify scheduling if needed

## API Usage

Use the data quality checker in your Python scripts:

```python
from data_quality_checker import DataQualityChecker

# Create checker
checker = DataQualityChecker('raw_data')

# Analyze specific file
result = checker.analyze_file('raw_data/ecommerce_myntra_data.csv')
print(f"Fill rate: {result['average_fill_rate']}")

# Get quality score
print(f"Quality: {result['quality_score']}")

# Check critical fields
critical = result['critical_fields']
if 'status' in critical:
    print("All critical fields OK!")
else:
    for field, issue in critical.items():
        print(f"Issue: {field} - {issue}")

# Analyze all files
all_results = checker.analyze_all()
for filename, data in all_results.items():
    print(f"{filename}: {data['quality_score']}")
```

## Summary

The Data Quality Checker helps you:

- ✅ Identify data gaps automatically
- ✅ Monitor fill rates over time
- ✅ Get actionable recommendations
- ✅ Spot problematic scrapers early
- ✅ Validate data before analysis

**Run it regularly** (daily/weekly) as part of your data pipeline!

---

**For complete analysis, see:** `../DATA_QUALITY_REPORT.md`
