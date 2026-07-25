from __future__ import annotations

import csv
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import requests
MYNTRA_BASE_URL = "https://www.myntra.com"
OUTPUT_FILE = "myntra_women_shirts_raw.csv"
DEFAULT_KEYWORD = "women shirts"
ROWS_PER_PAGE = 50

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

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def keyword_to_search_slug(keyword: str) -> str:
    return quote_plus(clean_text(keyword)).replace("+", "-").lower()


def build_search_page_url(keyword: str) -> str:
    return f"{MYNTRA_BASE_URL}/{keyword_to_search_slug(keyword)}"


def build_product_url(landing_page_url: str) -> str:
    path = landing_page_url.lstrip("/")
    return f"{MYNTRA_BASE_URL}/{path}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()



def extract_number(text: str | None) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"[\d,.]+", cleaned)
    return match.group(0).replace(",", "") if match else ""


def normalize_image_url(url: str | None) -> str:
    value = clean_text(url)
    if value.startswith("http://"):
        value = "https://" + value[len("http://") :]
    if "($height)" in value:
        value = value.replace("h_($height),q_($qualityPercentage),w_($width)", "h_720,q_70,w_540")
    return value


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


def infer_keywords(text: str) -> dict[str, str]:
    low = clean_text(text).lower()

    fit = ""
    for candidate in [
        "boxy fit",
        "regular fit",
        "slim fit",
        "relaxed fit",
        "oversized fit",
        "comfort fit",
        "loose fit",
    ]:
        if candidate in low:
            fit = candidate.title()
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


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    return clean_text(re.sub(r"<[^>]+>", " ", str(text)))


def normalize_fabric(value: str | None) -> str:
    if not value:
        return ""
    parts = [clean_text(part) for part in re.split(r"[,/|]", str(value))]
    return unique_join([part for part in parts if part])


def infer_sizes_from_product_name(product_name: str) -> str:
    """Only infer sizes from explicit SKU-style tokens, not lone S/M/L in titles."""
    name = clean_text(product_name)
    sku_sizes = re.findall(
        r"(?:^|[-_/(\s])(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)(?:[-_/)\s]|$)",
        name,
        flags=re.IGNORECASE,
    )
    if not sku_sizes:
        return ""
    return unique_join([match.upper() for match in sku_sizes])


def normalize_size_list(value: Any) -> str:
    if isinstance(value, list):
        labels = [clean_text(str(item)) for item in value if clean_text(str(item))]
        return unique_join(labels)
    text = clean_text(str(value)) if value else ""
    if not text:
        return ""
    return unique_join([clean_text(part) for part in re.split(r"[,/|]", text)])


def extract_description(style: dict[str, Any]) -> str:
    sections: list[str] = []

    for entry in style.get("descriptors", []):
        if not isinstance(entry, dict):
            continue
        text = strip_html(entry.get("description", ""))
        if text and len(text) > 10:
            sections.append(text)

    product_details = style.get("productDetails", [])
    if isinstance(product_details, list):
        for entry in product_details:
            if not isinstance(entry, dict):
                continue
            text = strip_html(entry.get("description", "") or entry.get("value", ""))
            if text and len(text) > 10:
                sections.append(text)

    article = style.get("articleAttributes", {})
    if isinstance(article, dict):
        care = strip_html(article.get("Wash Care", ""))
        if care:
            sections.append(f"Wash care: {care}")

    seen: set[str] = set()
    unique_sections: list[str] = []
    for section in sections:
        key = section.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        unique_sections.append(section)
    return " ".join(unique_sections)


def has_meaningful_product_details(details: dict[str, str]) -> bool:
    important_fields = [
        "price", "rating", "size_options", "fabric", "description", "seller",
    ]
    return sum(1 for field in important_fields if details.get(field)) >= 2


def infer_from_product_name(product_name: str) -> dict[str, str]:
    name = clean_text(product_name)
    low = name.lower()

    color = ""
    color_candidates = [
        "blue, white",
        "black & white",
        "light rose",
        "dark blue",
        "navy",
        "cream",
        "olive",
        "teal",
        "rust",
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
    ]
    for candidate in color_candidates:
        if candidate in low:
            color = candidate.title()
            break

    inferred = infer_keywords(name)
    size_options = infer_sizes_from_product_name(name)

    return {
        "color": color,
        "size_options": size_options,
        "fit_type": inferred["fit_type"],
        "fabric": inferred["fabric"],
        "sleeve_type": inferred["sleeve_type"],
        "pattern": inferred["pattern"],
    }


def is_womens_shirt(product_name: str, gender: str = "") -> bool:
    if clean_text(gender).lower() not in {"", "women", "woman", "girls", "girl"}:
        if clean_text(gender).lower() in {"men", "man", "boys", "boy"}:
            return False

    name = clean_text(product_name).lower()
    if not name:
        return False

    if re.search(r"\bmen'?s?\b", name) or re.search(r"\bman\b", name):
        return False
    if re.search(r"\bboys?\b", name) or re.search(r"\bmale\b", name) or "gentleman" in name:
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


def nested_type_name(value: Any, default: str = "") -> str:
    if isinstance(value, dict):
        return clean_text(str(value.get("typeName", default)))
    return clean_text(str(value)) if value else default


def parse_search_product(item: dict[str, Any]) -> dict[str, Any]:
    product_name = clean_text(item.get("productName") or item.get("product", ""))
    brand = clean_text(item.get("brand", ""))
    price = extract_number(str(item.get("price", "")))
    original_price = extract_number(str(item.get("mrp", "")))
    discount_percent = extract_number(str(item.get("discountDisplayLabel", "")))
    if not discount_percent and price and original_price:
        try:
            p_val = float(price)
            op_val = float(original_price)
            if op_val > p_val and op_val > 0:
                discount_percent = f"{((op_val - p_val) / op_val) * 100:.2f}"
        except ValueError:
            pass
    try:
        if price and original_price and not discount_percent:
            p_val = float(price)
            op_val = float(original_price)
            if op_val > p_val > 0:
                discount_percent = f"{((op_val - p_val) / op_val) * 100:.2f}"
    except ValueError:
        pass

    image_url = normalize_image_url(item.get("searchImage", ""))
    if not image_url:
        images = item.get("images", [])
        if isinstance(images, list) and images:
            image_url = normalize_image_url(images[0].get("src", ""))

    inventory = item.get("inventoryInfo", [])
    availability = ""
    if isinstance(inventory, list):
        if any(entry.get("available") for entry in inventory if isinstance(entry, dict)):
            availability = "InStock"
        elif inventory:
            availability = "OutOfStock"

    title_fallback = infer_from_product_name(product_name)
    size_options = normalize_size_list(item.get("sizes", ""))

    return {
        "product_id": str(item.get("productId", "")),
        "product_name": product_name,
        "product_url": build_product_url(clean_text(item.get("landingPageUrl", ""))),
        "product_image": image_url,
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "brand": brand,
        "category": nested_type_name(item.get("masterCategory"), "Women Fashion"),
        "subcategory": nested_type_name(item.get("articleType"), "Shirts"),
        "rating": format_rating(item.get("rating", "")),
        "review_count": extract_number(str(item.get("ratingCount", ""))),
        "size_options": size_options,
        "color": clean_text(item.get("primaryColour", "")) or title_fallback.get("color", ""),
        "fit_type": title_fallback.get("fit_type", ""),
        "fabric": title_fallback.get("fabric", ""),
        "sleeve_type": title_fallback.get("sleeve_type", ""),
        "pattern": title_fallback.get("pattern", ""),
        "description": "",
        "availability": availability,
        "gender": clean_text(item.get("gender", "")),
    }


def parse_product_style(style: dict[str, Any]) -> dict[str, str]:
    article = style.get("articleAttributes", {}) if isinstance(style.get("articleAttributes"), dict) else {}
    ratings = style.get("ratings", {}) if isinstance(style.get("ratings"), dict) else {}
    sellers = style.get("sellers", []) if isinstance(style.get("sellers"), list) else []
    sizes = style.get("sizes", []) if isinstance(style.get("sizes"), list) else []

    size_labels = [
        clean_text(size.get("label", ""))
        for size in sizes
        if isinstance(size, dict) and size.get("available") and clean_text(size.get("label", ""))
    ]

    price = ""
    original_price = extract_number(str(style.get("mrp", "")))
    for size in sizes:
        if not isinstance(size, dict):
            continue
        seller_rows = size.get("sizeSellerData", [])
        if not isinstance(seller_rows, list):
            continue
        for seller_row in seller_rows:
            if not isinstance(seller_row, dict):
                continue
            if seller_row.get("discountedPrice") is not None:
                price = extract_number(str(seller_row.get("discountedPrice", "")))
                original_price = extract_number(str(seller_row.get("mrp", original_price)))
                break
        if price:
            break

    seller_name = ""
    if sellers and isinstance(sellers[0], dict):
        seller_name = clean_text(sellers[0].get("displayName") or sellers[0].get("sellerName", ""))

    availability = "InStock" if size_labels else "OutOfStock"
    keyword_text = " ".join(
        [
            clean_text(style.get("name", "")),
            " ".join(f"{k} {v}" for k, v in article.items()),
        ]
    )
    inferred = infer_keywords(keyword_text)

    image_url = ""
    media = style.get("media", {})
    if isinstance(media, dict):
        albums = media.get("albums", [])
        if isinstance(albums, list) and albums:
            images = albums[0].get("images", []) if isinstance(albums[0], dict) else []
            if isinstance(images, list) and images:
                image_url = normalize_image_url(images[0].get("src", ""))

    brand = ""
    brand_data = style.get("brand", {})
    if isinstance(brand_data, dict):
        brand = clean_text(brand_data.get("name", ""))

    fabric_value = normalize_fabric(article.get("Fabrics", "")) or inferred.get("fabric", "")

    return {
        "product_name": clean_text(style.get("name", "")),
        "product_image": image_url,
        "brand": brand,
        "price": price,
        "original_price": original_price,
        "rating": format_rating(ratings.get("averageRating", "")),
        "review_count": extract_number(str(ratings.get("totalCount", "") or ratings.get("reviewsCount", ""))),
        "size_options": unique_join(size_labels),
        "color": clean_text(style.get("baseColour", "")),
        "fit_type": clean_text(article.get("Fit", "")) or inferred.get("fit_type", ""),
        "fabric": fabric_value,
        "sleeve_type": clean_text(article.get("Sleeve Length", "")) or inferred.get("sleeve_type", ""),
        "pattern": clean_text(article.get("Patterns", "") or article.get("Print or Pattern Types", ""))
        or inferred.get("pattern", ""),
        "description": extract_description(style),
        "availability": availability,
        "seller": seller_name,
    }


def build_product_row(
    product: dict[str, Any],
    product_details: dict[str, str],
    scrape_time: str,
) -> dict[str, str]:
    title_fallback = infer_from_product_name(product.get("product_name", ""))
    price = product.get("price", "") or product_details.get("price", "")
    original_price = product.get("original_price", "") or product_details.get("original_price", "")
    discount_percent = product.get("discount_percent", "") or product_details.get("discount_percent", "")
    try:
        if price and original_price and not discount_percent:
            p_val = float(price)
            op_val = float(original_price)
            if op_val > p_val > 0:
                discount_percent = f"{((op_val - p_val) / op_val) * 100:.2f}"
    except ValueError:
        pass

    detail_image = product_details.get("product_image", "")
    search_image = product.get("product_image", "")
    if "($height)" in detail_image and search_image:
        product_image = search_image
    else:
        product_image = detail_image or search_image

    return {
        "website_name": "Myntra",
        "product_name": product_details.get("product_name", "") or product.get("product_name", ""),
        "product_image": product_image,
        "brand": product_details.get("brand", "") or product.get("brand", ""),
        "category": product.get("category", "Women Fashion"),
        "subcategory": product.get("subcategory", "Shirts"),
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "rating": product.get("rating", "") or product_details.get("rating", ""),
        "review_count": product.get("review_count", "") or product_details.get("review_count", ""),
        "size_options": product_details.get("size_options", "") or product.get("size_options", "") or title_fallback.get("size_options", ""),
        "color": product_details.get("color", "") or product.get("color", "") or title_fallback.get("color", ""),
        "fit_type": product_details.get("fit_type", "") or product.get("fit_type", "") or title_fallback.get("fit_type", ""),
        "fabric": (
            product_details.get("fabric", "")
            or product.get("fabric", "")
            or title_fallback.get("fabric", "")
        ),
        "sleeve_type": (
            product_details.get("sleeve_type", "")
            or product.get("sleeve_type", "")
            or title_fallback.get("sleeve_type", "")
        ),
        "pattern": product_details.get("pattern", "") or product.get("pattern", "") or title_fallback.get("pattern", ""),
        "description": product_details.get("description", "") or product.get("description", ""),
        "availability": product_details.get("availability", "") or product.get("availability", ""),
        "seller": product_details.get("seller", ""),
        "product_url": product.get("product_url", ""),
        "scrape_date": scrape_time,
    }


def create_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(REQUEST_HEADERS)
    return session


def initialize_session(session: requests.Session, keyword: str) -> None:
    session.get(build_search_page_url(keyword), timeout=30)
    session.headers["Accept"] = "application/json"


def fetch_search_page(
    session: requests.Session,
    keyword: str,
    offset: int,
    rows: int = ROWS_PER_PAGE,
) -> dict[str, Any]:
    slug = keyword_to_search_slug(keyword)
    response = session.get(
        f"{MYNTRA_BASE_URL}/gateway/v2/search/{slug}",
        params={"rows": rows, "o": offset},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def fetch_product_details(session: requests.Session, product_id: str) -> dict[str, str]:
    if not product_id:
        return {}

    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(
                f"{MYNTRA_BASE_URL}/gateway/v2/product/{product_id}",
                timeout=30,
            )
            if response.status_code in {429, 503}:
                time.sleep(1.5 + attempt)
                continue
            response.raise_for_status()
            payload = response.json()
            style = payload.get("style", {})
            if isinstance(style, dict) and style:
                details = parse_product_style(style)
                if has_meaningful_product_details(details):
                    return details
                if details.get("product_name") or details.get("price"):
                    return details
            last_error = ValueError("empty style payload")
        except Exception as exc:
            last_error = exc
            time.sleep(0.8 + attempt)
            continue

    print(f"[WARN] Product API failed for id={product_id}: {last_error}")
    return {}


def scrape_myntra_women_shirts(
    keyword: str = DEFAULT_KEYWORD,
    max_pages: int | None = None,
    max_products: int | None = None,
    search_only: bool = True,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scrape_time = datetime.now(timezone.utc).isoformat()
    session = create_session()
    initialize_session(session, keyword)

    products: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    offset = 0
    page_count = 0

    while True:
        page_count += 1
        if max_pages is not None and page_count > max_pages:
            break

        try:
            payload = fetch_search_page(session, keyword, offset=offset)
        except Exception as exc:
            print(f"[WARN] Failed to fetch search page {page_count}: {exc}")
            break

        items = payload.get("products", [])
        if not isinstance(items, list) or not items:
            break

        page_matches = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            product = parse_search_product(item)
            product_name = product.get("product_name", "")
            if not is_womens_shirt(product_name, product.get("gender", "")):
                continue

            product_id = product.get("product_id", "")
            if not product_id or product_id in seen_ids:
                continue
            seen_ids.add(product_id)
            products.append(product)
            page_matches += 1

            if max_products is not None and len(products) >= max_products:
                break

        print(
            f"[INFO] Page {page_count}: {page_matches} women's shirts "
            f"({len(products)} total so far)"
        )

        if max_products is not None and len(products) >= max_products:
            break
        if not payload.get("hasNextPage"):
            break

        offset += ROWS_PER_PAGE
        time.sleep(0.25)

    product_details_by_id: dict[str, dict[str, str]] = {}
    if not search_only:
        for index, product in enumerate(products, start=1):
            product_id = product.get("product_id", "")
            if not product_id:
                continue
            print(f"[INFO] Fetching details {index}/{len(products)}")
            product_details_by_id[product_id] = fetch_product_details(session, product_id)
            time.sleep(0.5)
        print(f"[INFO] Full mode: search + product API for {len(products)} women's shirts")
    else:
        print(
            f"[INFO] Fast mode (search only): {len(products)} women's shirts "
            "(use --full for fabric, seller, description)"
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

    return rows


def save_to_csv(rows: list[dict[str, str]], output_file: str = OUTPUT_FILE) -> str:
    with open(output_file, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=HEADERS)
        writer.writeheader()
        writer.writerows(rows)
    return output_file


def _parse_limit_arg(value: str | None) -> int | None:
    if value is None:
        return None
    if value.lower() in {"all", "none", "0"}:
        return None
    return int(value)


# ── CLI: [keyword] [max_products] [max_pages]
#   --full          fetch product API for fabric, seller, description, specs
#   --output FILE   CSV output path (default: myntra_women_shirts_raw.csv)
if __name__ == "__main__":
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    output_file = OUTPUT_FILE
    if "--output" in flags:
        out_idx = sys.argv.index("--output")
        if out_idx + 1 < len(sys.argv):
            output_file = sys.argv[out_idx + 1]
    search_only = "--full" not in flags

    keyword = args[0] if args else DEFAULT_KEYWORD
    max_products = _parse_limit_arg(args[1] if len(args) > 1 else None)
    max_pages = _parse_limit_arg(args[2] if len(args) > 2 else None)

    products_label = max_products if max_products is not None else "all"
    pages_label = max_pages if max_pages is not None else "all"
    mode_label = "search only (no product API)" if search_only else "full (product API)"
    print(
        f"[INFO] Scraping Myntra women's shirts: '{keyword}' | "
        f"mode={mode_label} | max_products={products_label} | max_pages={pages_label}"
    )
    data = scrape_myntra_women_shirts(
        keyword=keyword,
        max_pages=max_pages,
        max_products=max_products,
        search_only=search_only,
    )
    path = save_to_csv(data, output_file)
    print(f"[INFO] Scraped {len(data)} products -> saved to {path}")
