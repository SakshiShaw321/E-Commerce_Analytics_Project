from __future__ import annotations

import csv
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

SNAPDEAL_BASE_URL = "https://www.snapdeal.com"
OUTPUT_FILE = "snapdeal_women_shirts_raw.csv"
DEFAULT_KEYWORD = "women shirts"
PAGE_SIZE = 20
NAVIGATION_TIMEOUT_MS = 60_000
DETAIL_SLEEP_S = 0.8

HEADERS = [
    "website_name",
    "product_name",
    "product_image",
    "brand",
    "category",
    "subcategory",
    "price",
    "original_price",
    "discount_percent",
    "rating",
    "review_count",
    "size_options",
    "color",
    "fit_type",
    "fabric",
    "sleeve_type",
    "pattern",
    "description",
    "availability",
    "seller",
    "product_url",
    "scrape_date",
]

COLOR_CANDIDATES = [
    "blue, white",
    "black & white",
    "off white",
    "off-white",
    "light blue",
    "dark blue",
    "navy blue",
    "light rose",
    "coffee",
    "mustard",
    "olive",
    "teal",
    "wine",
    "cream",
    "lavender",
    "lilac",
    "mint",
    "peach",
    "multi",
    "black",
    "blue",
    "pink",
    "green",
    "brown",
    "yellow",
    "red",
    "white",
    "grey",
    "gray",
    "maroon",
    "purple",
    "beige",
    "orange",
    "navy",
]

SIZE_TOKENS = {"XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL"}


def build_search_page_url(keyword: str) -> str:
    return f"{SNAPDEAL_BASE_URL}/search?keyword={quote_plus(keyword)}&sort=plrty"


def build_search_fragment_url(keyword: str, start: int) -> str:
    return (
        f"{SNAPDEAL_BASE_URL}/acors/json/product/get/search/0/{start}/{PAGE_SIZE}"
        f"?keyword={quote_plus(keyword)}&sort=plrty"
    )


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def extract_number(text: str | None) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"\d[\d,.]*", cleaned)
    return match.group(0).replace(",", "") if match else ""


def format_rating(value: str | float | int | None) -> str:
    number = extract_number(str(value))
    if not number:
        return ""
    try:
        return f"{float(number):.1f}".rstrip("0").rstrip(".")
    except ValueError:
        return number


def unique_join(items: list[str]) -> str:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = clean_text(item)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(cleaned)
    return ", ".join(ordered)


def normalize_product_url(url: str | None) -> str:
    value = clean_text(url)
    if not value:
        return ""
    if value.startswith("//"):
        value = "https:" + value
    value = urljoin(SNAPDEAL_BASE_URL, value)
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def infer_keywords(text: str) -> dict[str, str]:
    low = clean_text(text).lower()

    fit = ""
    for candidate in [
        "boxy fit",
        "regular fit",
        "slim fit",
        "relaxed fit",
        "oversized fit",
        "oversized-fit",
        "comfort fit",
        "loose fit",
    ]:
        if candidate in low:
            fit = candidate.replace("-", " ").title()
            break

    fabric = ""
    for candidate in [
        "cotton blend",
        "pure cotton",
        "cotton",
        "rayon",
        "polyester",
        "viscose",
        "linen",
        "georgette",
        "satin",
        "denim",
        "crepe",
    ]:
        if candidate in low:
            fabric = candidate.title()
            break

    sleeve = ""
    for candidate in [
        "full sleeve",
        "full sleeves",
        "half sleeve",
        "short sleeve",
        "long sleeve",
        "3/4 sleeve",
        "sleeveless",
        "roll-up sleeve",
    ]:
        if candidate in low:
            sleeve = candidate.title()
            break

    pattern = ""
    for candidate in [
        "solid",
        "striped",
        "printed",
        "checkered",
        "floral",
        "graphic print",
        "self design",
        "dyed/ombre",
        "ombre",
    ]:
        if candidate in low:
            pattern = candidate.title()
            break

    return {
        "fit_type": fit,
        "fabric": fabric,
        "sleeve_type": sleeve,
        "pattern": pattern,
    }


def infer_color(text: str) -> str:
    low = clean_text(text).lower()
    for candidate in COLOR_CANDIDATES:
        pattern = r"\b" + re.escape(candidate).replace(r"\ ", r"[\s-]+") + r"\b"
        if re.search(pattern, low):
            return candidate.replace("-", " ").title()
    return ""


def infer_from_text(text: str) -> dict[str, str]:
    inferred = infer_keywords(text)
    return {
        "color": infer_color(text),
        "fit_type": inferred["fit_type"],
        "fabric": inferred["fabric"],
        "sleeve_type": inferred["sleeve_type"],
        "pattern": inferred["pattern"],
    }


def extract_color_from_title(title: str) -> str:
    match = re.search(r"\(\s*([^)]+)\s*\)\s*$", clean_text(title))
    if match:
        return clean_text(match.group(1)).title()
    return ""


def extract_brand_from_title(title: str) -> str:
    name = clean_text(title)
    if not name:
        return ""
    for marker in (" Women ", " women ", " Men ", " men ", " Girls ", " Boys "):
        if marker in name:
            return clean_text(name.split(marker, 1)[0])
    return ""


def rating_from_star_width(style_value: str | None) -> str:
    if not style_value:
        return ""
    match = re.search(r"width:\s*([\d.]+)%", style_value)
    if not match:
        return ""
    try:
        return format_rating(float(match.group(1)) / 20.0)
    except ValueError:
        return ""


def compute_discount_percent(price: str, original_price: str, discount_label: str) -> str:
    label = extract_number(discount_label)
    if label:
        return label
    try:
        p_val = float(price)
        op_val = float(original_price)
        if op_val > p_val > 0:
            return f"{((op_val - p_val) / op_val) * 100:.2f}"
    except ValueError:
        pass
    return ""


def is_womens_shirt(product_name: str) -> bool:
    name = clean_text(product_name).lower()
    if not name:
        return False

    if re.search(r"\bmen'?s?\b", name) or re.search(r"\bman\b", name):
        return False
    if re.search(r"\bboys?\b", name) or re.search(r"\bmale\b", name):
        return False

    unrelated = (
        "jeans", "trouser", "pant", "skirt", "shoe", "sandal", "sneaker",
        "saree", "sari", "dupatta", "wallet", "handbag", "watch",
        "jewellery", "jewelry", "legging", "shorts", "jacket", "coat",
        "sweater", "hoodie", "dress", "gown", "kurta set", "suit set",
    )
    if any(term in name for term in unrelated):
        return False

    if re.search(r"\bt[\s-]?shirts?\b", name) or re.search(r"\btees?\b", name):
        return False

    return bool(re.search(r"\bshirts?\b", name) or re.search(r"\bblouses?\b", name))


def parse_search_card(card: BeautifulSoup) -> dict[str, Any]:
    product_id = clean_text(str(card.get("id", "")))
    title_node = card.select_one(".product-title")
    title = clean_text(title_node.get_text() if title_node else "")
    if not title:
        image = card.select_one("img.product-image, img")
        title = clean_text(str(image.get("title", "")) if image else "")

    mrp_node = card.select_one(".product-desc-price.strike")
    mrp = extract_number(mrp_node.get_text() if mrp_node else "")
    price_node = card.select_one(".product-price")
    price = ""
    if price_node:
        price = extract_number(str(price_node.get("data-price", "")) or price_node.get_text())

    discount_node = card.select_one(".product-discount span")
    discount_label = clean_text(discount_node.get_text() if discount_node else "")
    discount_percent = compute_discount_percent(price, mrp, discount_label)

    stars = card.select_one(".filled-stars")
    rating = rating_from_star_width(stars.get("style") if stars else "")
    review_node = card.select_one(".product-rating-count")
    review_count = extract_number(review_node.get_text() if review_node else "")

    image_node = card.select_one("img.product-image, picture img")
    image_url = ""
    if image_node:
        image_url = clean_text(str(image_node.get("src") or image_node.get("data-src") or ""))

    link_node = card.select_one("a.dp-widget-link[href*='/product/']")
    product_url = normalize_product_url(link_node.get("href") if link_node else "")

    brand = extract_brand_from_title(title)
    color = extract_color_from_title(title) or infer_color(title)
    inferred = infer_from_text(title)
    is_live = clean_text(str(card.get("data-islive", ""))).lower() == "true"

    return {
        "product_id": product_id,
        "product_name": title,
        "product_url": product_url,
        "product_image": image_url,
        "price": price,
        "original_price": mrp,
        "discount_percent": discount_percent,
        "brand": brand,
        "category": "Women",
        "subcategory": "Shirts",
        "rating": rating,
        "review_count": review_count,
        "size_options": "",
        "color": color,
        "fit_type": inferred["fit_type"],
        "fabric": inferred["fabric"],
        "sleeve_type": inferred["sleeve_type"],
        "pattern": inferred["pattern"],
        "description": "",
        "availability": "InStock" if is_live else "",
        "seller": "",
    }


def parse_search_fragment(html: str) -> tuple[list[dict[str, Any]], int | None]:
    soup = BeautifulSoup(html, "html.parser")
    total_count: int | None = None
    count_node = soup.select_one("#catProductCount")
    if count_node and count_node.get("value"):
        try:
            total_count = int(str(count_node.get("value")))
        except ValueError:
            total_count = None

    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in soup.select(".product-tuple-listing"):
        product_id = clean_text(str(card.get("id", "")))
        if not product_id or product_id in seen_ids:
            continue
        seen_ids.add(product_id)
        products.append(parse_search_card(card))
    return products, total_count


def parse_spec_lines(soup: BeautifulSoup) -> dict[str, str]:
    specs: dict[str, str] = {}
    skip_labels = {
        "item details",
        "ratings & reviews",
        "questions & answers",
        "highlights",
        "other specifications",
        "other details",
        "terms & conditions",
    }
    for node in soup.select("#productSpecs li, .product-specs li"):
        text = clean_text(node.get_text(" ", strip=True))
        if not text or ":" not in text:
            continue
        key, value = text.split(":", 1)
        key_low = clean_text(key).lower()
        value = clean_text(value)
        if not value or key_low in skip_labels:
            continue
        if len(key_low) > 40:
            continue
        specs[key_low] = value
    return specs


def extract_sizes_from_pdp(soup: BeautifulSoup) -> str:
    sizes: list[str] = []
    for node in soup.select(".size-list li, .size-list a"):
        text = clean_text(node.get_text()).upper()
        if text in SIZE_TOKENS:
            sizes.append(text)
    if sizes:
        return unique_join(sizes)

    for node in soup.select("[class*='size-list'] [class*='size'], .sd-size-list li"):
        text = clean_text(node.get_text()).upper()
        if text in SIZE_TOKENS:
            sizes.append(text)
    return unique_join(sizes)


def extract_seller_from_pdp(soup: BeautifulSoup, body_text: str) -> str:
    for pattern in (
        r"View Store\s+([^(|\n]{2,80})",
        r"Sold by\s+([^(|\n]{2,80})",
        r"Seller\s*[:\n]\s*([^(|\n]{2,80})",
    ):
        match = re.search(pattern, body_text, flags=re.IGNORECASE)
        if match:
            seller = clean_text(match.group(1))
            if seller.lower() not in {"snapdeal", "seller", "details"}:
                return seller
    return ""


def extract_review_count_from_pdp(body_text: str) -> str:
    match = re.search(r"(\d[\d,]*)\s+Ratings?", body_text, flags=re.IGNORECASE)
    return extract_number(match.group(1)) if match else ""


def build_description_from_specs(specs: dict[str, str], product_name: str) -> str:
    parts: list[str] = []
    for key in ("fabric", "fit", "sleeves length", "color", "neck shape", "product length"):
        value = specs.get(key, "")
        if value:
            parts.append(f"{key.title()}: {value}")
    if parts:
        return ". ".join(parts)
    return clean_text(product_name)


def parse_product_page(html: str) -> dict[str, str]:
    if "access denied" in html.lower():
        return {}

    soup = BeautifulSoup(html, "html.parser")
    body_text = clean_text(soup.get_text(" ", strip=True))
    specs = parse_spec_lines(soup)

    stars = soup.select_one(".filled-stars")
    rating = rating_from_star_width(stars.get("style") if stars else "")
    review_count = extract_review_count_from_pdp(body_text)
    if not review_count:
        review_count = extract_number(
            clean_text(soup.select_one(".product-rating-count").get_text())
            if soup.select_one(".product-rating-count")
            else ""
        )

    keyword_text = " ".join([body_text[:500], " ".join(f"{k} {v}" for k, v in specs.items())])
    inferred = infer_from_text(keyword_text)

    fabric = clean_text(specs.get("fabric", "")) or inferred["fabric"]
    fit_type = clean_text(specs.get("fit", "")) or inferred["fit_type"]
    sleeve = clean_text(specs.get("sleeves length", "") or specs.get("sleeve length", "")) or inferred["sleeve_type"]
    color = clean_text(specs.get("color", "")) or inferred["color"]
    pattern = inferred["pattern"]

    title_node = soup.select_one("h1[itemprop='name'], .pdp-e-i-head, .product-title")
    product_name = clean_text(title_node.get_text() if title_node else "")

    return {
        "product_name": product_name,
        "rating": rating,
        "review_count": review_count,
        "size_options": extract_sizes_from_pdp(soup),
        "color": color,
        "fit_type": fit_type,
        "fabric": fabric,
        "sleeve_type": sleeve,
        "pattern": pattern,
        "description": build_description_from_specs(specs, product_name),
        "seller": extract_seller_from_pdp(soup, body_text),
        "availability": "InStock",
    }


def build_product_row(
    product: dict[str, Any],
    product_details: dict[str, str],
    scrape_time: str,
) -> dict[str, str]:
    title_fallback = infer_from_text(product.get("product_name", ""))
    price = product.get("price", "") or product_details.get("price", "")
    original_price = product.get("original_price", "") or product_details.get("original_price", "")
    discount_percent = product.get("discount_percent", "") or product_details.get("discount_percent", "")
    if not discount_percent:
        discount_percent = compute_discount_percent(price, original_price, "")

    return {
        "website_name": "Snapdeal",
        "product_name": product_details.get("product_name", "") or product.get("product_name", ""),
        "product_image": product.get("product_image", ""),
        "brand": product.get("brand", ""),
        "category": product.get("category", "Women"),
        "subcategory": product.get("subcategory", "Shirts"),
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "rating": product.get("rating", "") or product_details.get("rating", ""),
        "review_count": product.get("review_count", "") or product_details.get("review_count", ""),
        "size_options": product_details.get("size_options", "") or product.get("size_options", ""),
        "color": product_details.get("color", "") or product.get("color", "") or title_fallback.get("color", ""),
        "fit_type": product_details.get("fit_type", "") or product.get("fit_type", "") or title_fallback.get("fit_type", ""),
        "fabric": product_details.get("fabric", "") or product.get("fabric", "") or title_fallback.get("fabric", ""),
        "sleeve_type": product_details.get("sleeve_type", "") or product.get("sleeve_type", "") or title_fallback.get("sleeve_type", ""),
        "pattern": product_details.get("pattern", "") or product.get("pattern", "") or title_fallback.get("pattern", ""),
        "description": product_details.get("description", "") or product.get("description", ""),
        "availability": product_details.get("availability", "") or product.get("availability", "InStock"),
        "seller": product_details.get("seller", "") or product.get("seller", ""),
        "product_url": product.get("product_url", ""),
        "scrape_date": scrape_time,
    }


def fetch_search_fragment(context: BrowserContext, keyword: str, start: int) -> str:
    url = build_search_fragment_url(keyword, start)
    response = context.request.get(
        url,
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "referer": build_search_page_url(keyword),
            "x-requested-with": "XMLHttpRequest",
        },
    )
    if not response.ok:
        raise RuntimeError(f"search fragment HTTP {response.status} at start={start}")
    return response.text()


def fetch_product_details(page: Page, product_url: str) -> dict[str, str]:
    if not product_url:
        return {}
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        page.wait_for_timeout(4000)
        return parse_product_page(page.content())
    except Exception as exc:
        print(f"[WARN] PDP failed for {product_url}: {exc}")
        return {}


def launch_browser(playwright) -> Any:
    try:
        return playwright.chromium.launch(
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
    except Exception:
        return playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )


def scrape_snapdeal_women_shirts(
    keyword: str = DEFAULT_KEYWORD,
    max_pages: int | None = None,
    max_products: int | None = None,
    search_only: bool = True,
    detail_from: int = 1,
    detail_to: int | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scrape_time = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        context = browser.new_context(
            locale="en-IN",
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(build_search_page_url(keyword), wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        page.wait_for_timeout(4000)

        products: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        start = 0
        page_count = 0
        total_count: int | None = None

        while True:
            page_count += 1
            if max_pages is not None and page_count > max_pages:
                break

            try:
                html = fetch_search_fragment(context, keyword, start)
            except Exception as exc:
                print(f"[WARN] Failed to fetch search page {page_count}: {exc}")
                break

            page_products, fragment_total = parse_search_fragment(html)
            if fragment_total is not None:
                total_count = fragment_total
            if not page_products:
                break

            page_matches = 0
            for product in page_products:
                product_name = product.get("product_name", "")
                if not is_womens_shirt(product_name):
                    continue

                product_id = product.get("product_id", "")
                if not product_id or product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                products.append(product)
                page_matches += 1

                if max_products is not None and len(products) >= max_products:
                    break

            total_label = f"/{(total_count + PAGE_SIZE - 1) // PAGE_SIZE}" if total_count else ""
            print(
                f"[INFO] Page {page_count}{total_label}: "
                f"{page_matches} women's shirts ({len(products)} total so far)"
            )

            if max_products is not None and len(products) >= max_products:
                break
            if total_count is not None and start + PAGE_SIZE >= total_count:
                break
            if len(page_products) < PAGE_SIZE:
                break

            start += PAGE_SIZE
            time.sleep(0.35)

        product_details_by_id: dict[str, dict[str, str]] = {}
        if not search_only:
            detail_page = context.new_page()
            for index, product in enumerate(products, start=1):
                if index < detail_from:
                    continue
                if detail_to is not None and index > detail_to:
                    continue
                product_url = product.get("product_url", "")
                product_id = product.get("product_id", "")
                if not product_url:
                    continue
                print(f"[INFO] Fetching details {index}/{len(products)}", flush=True)
                product_details_by_id[product_id] = fetch_product_details(detail_page, product_url)
                time.sleep(DETAIL_SLEEP_S)
            detail_page.close()
            print(f"[INFO] Full mode: search + PDP for {len(products)} women's shirts")
        else:
            print(
                f"[INFO] Fast mode (search fragments): {len(products)} women's shirts "
                "(use --full for sizes, fabric, seller, description)"
            )

        for product in products:
            product_id = product.get("product_id", "")
            rows.append(
                build_product_row(
                    product,
                    product_details_by_id.get(product_id, {}),
                    scrape_time,
                )
            )
            if max_products is not None and len(rows) >= max_products:
                break

        browser.close()

    return rows


def save_to_csv(rows: list[dict[str, str]], output_file: str = OUTPUT_FILE) -> str:
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        return output_file
    except PermissionError:
        backup = output_file.rsplit(".", 1)
        backup_file = f"{backup[0]}_backup.csv" if len(backup) == 2 else f"{output_file}_backup.csv"
        with open(backup_file, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        print(f"[WARN] Could not write {output_file} (file locked). Saved to {backup_file}")
        return backup_file


def _parse_limit_arg(value: str | None) -> int | None:
    if value is None:
        return None
    if value.lower() in {"all", "none", "0"}:
        return None
    return int(value)


def _field_fill_stats(rows: list[dict[str, str]]) -> dict[str, float]:
    if not rows:
        return {}
    stats: dict[str, float] = {}
    for field in HEADERS:
        if field in {"website_name", "scrape_date"}:
            continue
        filled = sum(1 for row in rows if clean_text(row.get(field, "")))
        stats[field] = (filled / len(rows)) * 100
    return stats


# ── CLI: [keyword] [max_products] [max_pages]
#   --full          visit product pages for sizes, fabric, seller, description
#   --output FILE   CSV output path (default: snapdeal_women_shirts_raw.csv)
#   --detail-from N start detail fetching at product N (1-based)
#   --detail-to N   stop detail fetching at product N (inclusive)
if __name__ == "__main__":
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    output_file = OUTPUT_FILE
    detail_from = 1
    detail_to: int | None = None

    if "--output" in flags:
        out_idx = sys.argv.index("--output")
        if out_idx + 1 < len(sys.argv):
            output_file = sys.argv[out_idx + 1]
    if "--detail-from" in flags:
        from_idx = sys.argv.index("--detail-from")
        if from_idx + 1 < len(sys.argv):
            detail_from = max(1, int(sys.argv[from_idx + 1]))
        if (
            from_idx + 3 < len(sys.argv)
            and sys.argv[from_idx + 2].lower() == "to"
            and sys.argv[from_idx + 3].isdigit()
        ):
            detail_to = int(sys.argv[from_idx + 3])
    if "--detail-to" in flags:
        to_idx = sys.argv.index("--detail-to")
        if to_idx + 1 < len(sys.argv):
            detail_to = int(sys.argv[to_idx + 1])

    search_only = "--full" not in flags
    keyword = args[0] if args else DEFAULT_KEYWORD
    max_products = _parse_limit_arg(args[1] if len(args) > 1 else None)
    max_pages = _parse_limit_arg(args[2] if len(args) > 2 else None)

    products_label = max_products if max_products is not None else "all"
    pages_label = max_pages if max_pages is not None else "all"
    mode_label = "search fragments only" if search_only else "full (search + PDP)"
    print(
        f"[INFO] Scraping Snapdeal women's shirts: '{keyword}' | "
        f"mode={mode_label} | max_products={products_label} | max_pages={pages_label}"
    )

    data = scrape_snapdeal_women_shirts(
        keyword=keyword,
        max_pages=max_pages,
        max_products=max_products,
        search_only=search_only,
        detail_from=detail_from,
        detail_to=detail_to,
    )
    path = save_to_csv(data, output_file)
    print(f"[INFO] Scraped {len(data)} products -> saved to {path}")

    if data:
        stats = _field_fill_stats(data)
        sparse = [field for field, pct in stats.items() if pct < 25]
        if sparse:
            print(f"[INFO] Sparse fields (<25% filled): {', '.join(sparse)}")
