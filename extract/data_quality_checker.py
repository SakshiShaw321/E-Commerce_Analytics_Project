"""Data Quality Checker - Validate scraper output data."""

import csv
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime


class DataQualityChecker:
    """Analyze CSV files from scrapers and report data quality."""

    def __init__(self, data_dir: str | Path = "raw_data"):
        """Initialize the checker."""
        self.data_dir = Path(data_dir)
        self.results = {}

    def analyze_file(self, filepath: str | Path) -> dict:
        """Analyze a single CSV file for data quality."""
        filepath = Path(filepath)
        if not filepath.exists():
            return {"error": f"File not found: {filepath}"}

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            if not rows:
                return {
                    "filename": filepath.name,
                    "status": "EMPTY",
                    "total_rows": 0,
                    "error": "File is empty",
                }

            # Analyze columns
            columns = reader.fieldnames or []
            column_stats = {}

            for col in columns:
                filled = sum(1 for row in rows if row.get(col, "").strip())
                empty = len(rows) - filled
                pct = (filled / len(rows) * 100) if rows else 0
                column_stats[col] = {
                    "filled": filled,
                    "empty": empty,
                    "fill_rate": f"{pct:.1f}%",
                }

            # Overall quality score
            avg_fill_rate = sum(
                (s["filled"] / len(rows)) * 100 for s in column_stats.values()
            ) / len(column_stats) if column_stats else 0

            return {
                "filename": filepath.name,
                "status": "OK",
                "total_rows": len(rows),
                "total_columns": len(columns),
                "average_fill_rate": f"{avg_fill_rate:.1f}%",
                "quality_score": self._quality_score(avg_fill_rate),
                "columns": column_stats,
                "critical_fields": self._check_critical_fields(column_stats, len(rows)),
            }

        except Exception as e:
            return {
                "filename": filepath.name,
                "status": "ERROR",
                "error": str(e),
            }

    def _quality_score(self, fill_rate: float) -> str:
        """Calculate quality score based on fill rate."""
        if fill_rate >= 95:
            return "EXCELLENT ⭐⭐⭐⭐⭐"
        elif fill_rate >= 85:
            return "GOOD ⭐⭐⭐⭐"
        elif fill_rate >= 75:
            return "FAIR ⭐⭐⭐"
        elif fill_rate >= 60:
            return "POOR ⭐⭐"
        else:
            return "CRITICAL ⭐"

    def _check_critical_fields(self, column_stats: dict, total_rows: int) -> dict:
        """Check critical fields that should always be filled."""
        critical_fields = {
            "website_name": 100,
            "product_name": 100,
            "price": 90,
            "availability": 90,
            "product_url": 100,
            "scrape_date": 100,
        }

        issues = {}
        for field, min_fill in critical_fields.items():
            if field in column_stats:
                fill_pct = (column_stats[field]["filled"] / total_rows) * 100
                if fill_pct < min_fill:
                    issues[field] = {
                        "expected": f"{min_fill}%",
                        "actual": f"{fill_pct:.1f}%",
                        "filled": column_stats[field]["filled"],
                        "missing": column_stats[field]["empty"],
                    }

        return issues if issues else {"status": "All critical fields OK"}

    def analyze_all(self) -> dict:
        """Analyze all CSV files in the data directory."""
        if not self.data_dir.exists():
            return {"error": f"Directory not found: {self.data_dir}"}

        csv_files = list(self.data_dir.glob("*.csv"))
        if not csv_files:
            return {"warning": f"No CSV files found in {self.data_dir}"}

        results = {}
        for filepath in sorted(csv_files):
            results[filepath.name] = self.analyze_file(filepath)

        return results

    def print_report(self, results: dict | None = None) -> None:
        """Print a formatted quality report."""
        if results is None:
            results = self.analyze_all()

        print("\n" + "=" * 100)
        print("DATA QUALITY ASSESSMENT REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 100)

        # Summary table
        print("\nFILE SUMMARY:")
        print("-" * 100)
        print(
            f"{'File':<35} {'Rows':<10} {'Columns':<10} {'Quality':<30} {'Status':<15}"
        )
        print("-" * 100)

        for filename, data in results.items():
            if "error" in data and isinstance(data.get("error"), str):
                print(
                    f"{filename:<35} {'N/A':<10} {'N/A':<10} {'ERROR':<30} {data['status']:<15}"
                )
            else:
                rows = data.get("total_rows", 0)
                cols = data.get("total_columns", 0)
                quality = data.get("quality_score", "N/A")
                status = data.get("status", "UNKNOWN")
                print(
                    f"{filename:<35} {rows:<10} {cols:<10} {quality:<30} {status:<15}"
                )

        # Detailed analysis
        print("\n" + "=" * 100)
        print("DETAILED COLUMN ANALYSIS:")
        print("=" * 100)

        for filename, data in results.items():
            if "error" in data:
                print(f"\n{filename}: {data['error']}")
                continue

            print(f"\n{filename}")
            print("-" * 100)
            avg_fill = data.get("average_fill_rate", "N/A")
            print(f"Average Fill Rate: {avg_fill}")

            critical = data.get("critical_fields", {})
            if isinstance(critical, dict) and critical.get("status"):
                print(f"Critical Fields: ✓ {critical['status']}")
            elif critical:
                print("Critical Field Issues:")
                for field, issue in critical.items():
                    print(
                        f"  ⚠ {field}: {issue['filled']}/{issue['filled'] + issue['missing']} "
                        f"filled (expected {issue['expected']}, got {issue['actual']})"
                    )

            columns = data.get("columns", {})
            print("\nColumn Status:")
            print(f"{'Column':<30} {'Filled':<12} {'Empty':<12} {'Rate':<10}")
            print("-" * 100)

            # Sort columns by fill rate
            sorted_cols = sorted(
                columns.items(),
                key=lambda x: float(x[1]["fill_rate"].rstrip("%")),
                reverse=True,
            )

            for col_name, stats in sorted_cols:
                filled = stats["filled"]
                empty = stats["empty"]
                rate = stats["fill_rate"]
                symbol = "✓" if float(rate.rstrip("%")) >= 80 else "⚠"
                print(f"{symbol} {col_name:<28} {filled:<12} {empty:<12} {rate:<10}")

        print("\n" + "=" * 100)
        print("RECOMMENDATIONS:")
        print("=" * 100)

        # Generate recommendations
        recommendations = self._generate_recommendations(results)
        for i, rec in enumerate(recommendations, 1):
            print(f"{i}. {rec}")

        print("\n" + "=" * 100 + "\n")

    def _generate_recommendations(self, results: dict) -> list:
        """Generate recommendations based on analysis."""
        recommendations = []

        for filename, data in results.items():
            if "error" in data:
                recommendations.append(
                    f"Fix {filename}: {data['error']}"
                )
                continue

            # Check for critical field issues
            critical = data.get("critical_fields", {})
            if critical and critical.get("status") != "All critical fields OK":
                for field, issue in critical.items():
                    recommendations.append(
                        f"In {filename}: {field} has low fill rate "
                        f"({issue['actual']} - expected {issue['expected']})"
                    )

            # Check for generally low fill rates
            avg_fill = float(data.get("average_fill_rate", "0").rstrip("%"))
            if avg_fill < 75:
                recommendations.append(
                    f"{filename} has overall low data quality ({data.get('average_fill_rate')}). "
                    f"Consider using --full mode to fetch complete product details."
                )

            # Check specific missing fields
            columns = data.get("columns", {})
            missing_fields = [
                col for col, stats in columns.items()
                if float(stats["fill_rate"].rstrip("%")) == 0
            ]
            if missing_fields:
                recommendations.append(
                    f"{filename}: Missing data in {', '.join(missing_fields[:3])}. "
                    f"These require fetching product detail pages."
                )

        if not recommendations:
            recommendations.append("All scrapers are performing well! ✓")

        return recommendations


def main():
    """Main CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Data Quality Checker for E-commerce Scrapers"
    )
    parser.add_argument(
        "--data-dir",
        default="raw_data",
        help="Path to data directory (default: raw_data)",
    )
    parser.add_argument(
        "--file",
        help="Analyze specific file only",
    )

    args = parser.parse_args()

    checker = DataQualityChecker(args.data_dir)

    if args.file:
        results = {Path(args.file).name: checker.analyze_file(args.file)}
    else:
        results = checker.analyze_all()

    checker.print_report(results)


if __name__ == "__main__":
    main()
