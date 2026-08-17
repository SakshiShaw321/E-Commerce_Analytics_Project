from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import BrowserContext, Page, sync_playwright

AJIO_BASE_URL = "https://www.ajio.com"
OUTPUT_FILE = "ajio_women_shirts_raw.csv"
DEFAULT_KEYWORD = "women shirts"
PAGE_SIZE = 45
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
    "indigo",
    "khaki",
    "mustard",
    "wine",
    "multicolor",
]


def build_search_page_url(keyword: str) -> str:
    return f"{AJIO_BASE_URL}/search/?text={quote_plus(keyword)}"


def build_search_api_url(keyword: str, page: int, page_size: int = PAGE_SIZE) -> str:
    return (
        f"{AJIO_BASE_URL}/api/search/{quote_plus(keyword)}"
        f"?currentPage={page}&pageSize={page_size}&format=json"
    )


def build_product_url(path: str) -> str:
    return urljoin(AJIO_BASE_URL, path)


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


def pick_primary_image(item: dict[str, Any]) -> str:
    images = item.get("images", [])
    if not isinstance(images, list):
        return ""
    for image in images:
        if not isinstance(image, dict):
            continue
        if image.get("format") == "product" and image.get("imageType") == "PRIMARY":
            return clean_text(str(image.get("url", "")))
    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return clean_text(str(image["url"]))
    variant = item.get("fnlColorVariantData", {})
    if isinstance(variant, dict):
        return clean_text(str(variant.get("outfitPictureURL", "")))
    return ""


def pick_alt_text(item: dict[str, Any]) -> str:
    images = item.get("images", [])
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict) and image.get("altText"):
                return clean_text(str(image["altText"]))
    return ""


def compute_discount_percent(
    price: str,
    original_price: str,
    discount_label: str,
) -> str:
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


def extract_color_from_color_group(color_group: str) -> str:
    value = clean_text(color_group)
    if not value or "_" not in value:
        return ""
    suffix = value.rsplit("_", 1)[-1]
    suffix = suffix.replace("-", " ")
    if not suffix or suffix.isdigit():
        return ""
    if suffix.lower() == "offwhite":
        return "Off White"
    return suffix.title()


def collect_search_text_blob(item: dict[str, Any]) -> str:
    parts: list[str] = []
    alt_text = pick_alt_text(item)
    name = clean_text(str(item.get("name", "")))
    url_path = clean_text(str(item.get("url", "")))
    brand_data = item.get("fnlColorVariantData", {})
    brand = ""
    color_group = ""
    if isinstance(brand_data, dict):
        brand = clean_text(str(brand_data.get("brandName", "")))
        color_group = clean_text(str(brand_data.get("colorGroup", "")))

    parts.extend([alt_text, name, brand, color_group.replace("_", " ")])
    if url_path:
        slug = url_path.split("/p/")[0].strip("/").split("/")[-1]
        parts.append(slug.replace("-", " "))

    image_url = pick_primary_image(item)
    if image_url:
        filename = image_url.rsplit("/", 1)[-1]
        parts.append(filename.replace("-", " ").replace("_", " "))

    return clean_text(" ".join(part for part in parts if part))


def parse_wishlist_tag(item: dict[str, Any]) -> str:
    tags = item.get("tags", {})
    if not isinstance(tags, dict):
        return ""
    category_tags = tags.get("categoryTags", [])
    if not isinstance(category_tags, list):
        return ""
    for entry in category_tags:
        if not isinstance(entry, dict):
            continue
        if clean_text(str(entry.get("category", ""))).upper() != "SOCIAL_PROOFING":
            continue
        primary = entry.get("primary", {})
        if not isinstance(primary, dict):
            continue
        if clean_text(str(primary.get("name", ""))).upper() != "WISHLISTCOUNT":
            continue
        raw = clean_text(str(primary.get("value", "")))
        if not raw:
            return ""
        try:
            payload = json.loads(raw)
            return clean_text(str(payload.get("longText") or payload.get("shortText") or ""))
        except json.JSONDecodeError:
            return raw
    return ""


def infer_fabric_from_text(text: str) -> str:
    low = clean_text(text).lower()
    for candidate in [
        "cotton blend",
        "linen blend",
        "pure cotton",
        "cotton",
        "rayon",
        "polyester",
        "viscose",
        "georgette",
        "chiffon",
        "linen",
        "satin",
        "crepe",
        "denim",
        "knit",
        "wool",
        "silk",
    ]:
        pattern = r"\b" + re.escape(candidate).replace(r"\ ", r"[\s-]+") + r"\b"
        if re.search(pattern, low):
            return candidate.title()
    return ""


def infer_pattern_from_text(text: str) -> str:
    low = clean_text(text).lower()
    for candidate, label in [
        ("graphic print", "Graphic Print"),
        ("floral print", "Floral"),
        ("self design", "Self Design"),
        ("embroidered", "Embroidered"),
        ("checkered", "Checkered"),
        ("checked", "Checkered"),
        ("striped", "Striped"),
        ("stripes", "Striped"),
        ("printed", "Printed"),
        ("graphic", "Graphic"),
        ("floral", "Floral"),
        ("ombre-dyed", "Ombre"),
        ("ombre", "Ombre"),
        ("polka", "Polka"),
        ("solid", "Solid"),
    ]:
        if candidate in low:
            return label
    return ""


def infer_sleeve_from_text(text: str) -> str:
    low = clean_text(text).lower()
    for candidate, label in [
        ("3/4th sleeves", "3/4 Sleeve"),
        ("3/4 sleeves", "3/4 Sleeve"),
        ("full sleeves", "Full Sleeve"),
        ("half sleeves", "Half Sleeve"),
        ("short sleeves", "Short Sleeve"),
        ("roll-up sleeves", "Roll-Up Sleeve"),
        ("sleeveless", "Sleeveless"),
        ("full sleeve", "Full Sleeve"),
        ("half sleeve", "Half Sleeve"),
        ("short sleeve", "Short Sleeve"),
        ("long sleeve", "Long Sleeve"),
    ]:
        if candidate in low:
            return label
    return ""


def build_search_description(product: dict[str, Any], wishlist_text: str = "") -> str:
    sections: list[str] = []
    product_name = clean_text(str(product.get("product_name", "")))
    if product_name:
        sections.append(product_name)

    attrs: list[str] = []
    for label, key in (
        ("Brand", "brand"),
        ("Color", "color"),
        ("Fit", "fit_type"),
        ("Fabric", "fabric"),
        ("Sleeve", "sleeve_type"),
        ("Pattern", "pattern"),
        ("Size", "size_options"),
    ):
        value = clean_text(str(product.get(key, "")))
        if value:
            attrs.append(f"{label}: {value}")

    category = clean_text(str(product.get("category", "")))
    subcategory = clean_text(str(product.get("subcategory", "")))
    if category or subcategory:
        attrs.append(f"Category: {unique_join([category, subcategory])}")

    if attrs:
        sections.append(". ".join(attrs))

    if wishlist_text:
        sections.append(wishlist_text)

    return ". ".join(sections)


def enrich_search_product_fields(product: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    text_blob = collect_search_text_blob(item)
    inferred = infer_from_text(text_blob)
    brand_data = item.get("fnlColorVariantData", {})
    color_group = ""
    if isinstance(brand_data, dict):
        color_group = clean_text(str(brand_data.get("colorGroup", "")))

    color = (
        extract_color_from_color_group(color_group)
        or inferred["color"]
        or infer_color(text_blob)
    )
    fabric = infer_fabric_from_text(text_blob) or inferred["fabric"]
    pattern = infer_pattern_from_text(text_blob) or inferred["pattern"]
    sleeve = infer_sleeve_from_text(text_blob) or inferred["sleeve_type"]
    fit_type = inferred["fit_type"]
    wishlist_text = parse_wishlist_tag(item)

    product.update(
        {
            "color": color,
            "fit_type": fit_type,
            "fabric": fabric,
            "sleeve_type": sleeve,
            "pattern": pattern,
            "description": build_search_description(
                {
                    **product,
                    "color": color,
                    "fit_type": fit_type,
                    "fabric": fabric,
                    "sleeve_type": sleeve,
                    "pattern": pattern,
                },
                wishlist_text,
            ),
        }
    )
    return product


def extract_size_from_sku(seller_sku: str) -> str:
    sku = clean_text(seller_sku)
    if not sku:
        return ""
    paren_match = re.search(
        r"\(\s*(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)\s*\)",
        sku,
        flags=re.IGNORECASE,
    )
    if paren_match:
        return paren_match.group(1).upper()
    match = re.search(
        r"(?:^|[-_/(\s])(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)(?:[-_/)\s]|$)",
        sku,
        flags=re.IGNORECASE,
    )
    return match.group(1).upper() if match else ""


def is_womens_shirt(
    product_name: str,
    segment: str = "",
    brick: str = "",
) -> bool:
    segment_low = clean_text(segment).lower()
    brick_low = clean_text(brick).lower()
    if segment_low and segment_low not in {"women", "woman", "girls", "girl"}:
        if segment_low in {"men", "man", "boys", "boy"}:
            return False

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

    if brick_low and "shirt" not in brick_low:
        return False

    return bool(re.search(r"\bshirts?\b", name) or re.search(r"\bblouses?\b", name) or brick_low == "shirts")


def parse_search_product(item: dict[str, Any]) -> dict[str, Any]:
    brand_data = item.get("fnlColorVariantData", {})
    brand = ""
    if isinstance(brand_data, dict):
        brand = clean_text(str(brand_data.get("brandName", "")))

    name = clean_text(str(item.get("name", "")))
    alt_text = pick_alt_text(item)
    product_name = alt_text or clean_text(f"{brand} {name}".strip())

    price_data = item.get("offerPrice") or item.get("price") or {}
    original_data = item.get("wasPriceData") or {}
    price = ""
    original_price = ""
    if isinstance(price_data, dict):
        price = extract_number(str(price_data.get("value", "")))
    if isinstance(original_data, dict):
        original_price = extract_number(str(original_data.get("value", "")))
    if not price and isinstance(item.get("price"), dict):
        price = extract_number(str(item["price"].get("value", "")))

    discount_percent = compute_discount_percent(
        price,
        original_price,
        str(item.get("discountPercent", "")),
    )

    inferred = infer_from_text(" ".join([product_name, name, alt_text]))
    color_group = ""
    if isinstance(brand_data, dict):
        color_group = clean_text(str(brand_data.get("colorGroup", "")))
    color = extract_color_from_color_group(color_group) or inferred["color"] or infer_color(color_group.replace("_", " "))

    max_quantity = 0
    if isinstance(brand_data, dict):
        try:
            max_quantity = int(brand_data.get("maxQuantity") or 0)
        except (TypeError, ValueError):
            max_quantity = 0
    availability = "InStock"
    if isinstance(brand_data, dict) and brand_data.get("sizeFlag") is False and max_quantity == 0:
        availability = "InStock"

    product_code = clean_text(str(brand_data.get("colorGroup", ""))) or clean_text(str(item.get("code", "")))
    url_path = clean_text(str(item.get("url", "")))
    if not product_code and "/p/" in url_path:
        product_code = url_path.rsplit("/p/", 1)[-1]

    product = {
        "product_code": product_code,
        "product_name": product_name or name,
        "product_url": build_product_url(url_path),
        "product_image": pick_primary_image(item),
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "brand": brand,
        "category": clean_text(str(item.get("segmentNameText", ""))) or "Women",
        "subcategory": (
            "Shirts"
            if "shirt" in clean_text(str(item.get("brickNameText", ""))).lower()
            else clean_text(str(item.get("brickNameText", ""))) or "Shirts"
        ),
        "rating": "",
        "review_count": "",
        "size_options": extract_size_from_sku(str(item.get("sellerSku", ""))),
        "color": color,
        "fit_type": inferred["fit_type"],
        "fabric": inferred["fabric"],
        "sleeve_type": inferred["sleeve_type"],
        "pattern": inferred["pattern"],
        "description": "",
        "availability": availability,
        "seller": "",
        "segment": clean_text(str(item.get("segmentNameText", ""))),
        "brick": clean_text(str(item.get("brickNameText", ""))),
    }
    return enrich_search_product_fields(product, item)


def normalize_fabric(value: str | None) -> str:
    if not value:
        return ""
    parts = [clean_text(part) for part in re.split(r"[,/|]", str(value))]
    return unique_join([part for part in parts if part])


def parse_size_options_from_payload(data: dict[str, Any]) -> str:
    sizes: list[str] = []
    for key in ("variantOptions", "sizeOptions", "sizes"):
        options = data.get(key)
        if not isinstance(options, list):
            continue
        for option in options:
            if not isinstance(option, dict):
                continue
            label = clean_text(
                str(
                    option.get("scDisplaySize")
                    or option.get("displaySize")
                    or option.get("size")
                    or option.get("code", "")
                )
            )
            stock = option.get("stock", {})
            in_stock = True
            if isinstance(stock, dict):
                level = clean_text(str(stock.get("stockLevelStatus", ""))).lower()
                in_stock = level not in {"outofstock", "out_of_stock"}
            if label and in_stock:
                sizes.append(label.upper())
    return unique_join(sizes)


def parse_ratings_from_payload(data: dict[str, Any]) -> tuple[str, str]:
    ratings = data.get("ratingsResponse") or data.get("ratings") or {}
    if not isinstance(ratings, dict):
        return "", ""
    rating = format_rating(
        ratings.get("averageRating")
        or ratings.get("avgRating")
        or ratings.get("rating")
    )
    review_count = extract_number(
        str(
            ratings.get("numUserRatings")
            or ratings.get("ratingCount")
            or ratings.get("totalCount")
            or ratings.get("reviewCount")
            or ""
        )
    )
    return rating, review_count


def parse_specs_from_payload(data: dict[str, Any]) -> dict[str, str]:
    specs: dict[str, str] = {}
    for key in ("productFeatureDescriptions", "featureData", "classifications"):
        block = data.get(key)
        if isinstance(block, list):
            for entry in block:
                if not isinstance(entry, dict):
                    continue
                name = clean_text(str(entry.get("name") or entry.get("key") or ""))
                value = clean_text(str(entry.get("value") or entry.get("description") or ""))
                if name and value:
                    specs[name.lower()] = value
        elif isinstance(block, dict):
            for name, value in block.items():
                specs[clean_text(str(name)).lower()] = clean_text(str(value))

    for entry in data.get("baseOptions", []) if isinstance(data.get("baseOptions"), list) else []:
        if not isinstance(entry, dict):
            continue
        for variant in entry.get("options", []) if isinstance(entry.get("options"), list) else []:
            if not isinstance(variant, dict):
                continue
            for feature in variant.get("variantOptionQualifiers", []) if isinstance(
                variant.get("variantOptionQualifiers"), list
            ) else []:
                if not isinstance(feature, dict):
                    continue
                name = clean_text(str(feature.get("name", "")))
                value = clean_text(str(feature.get("value", "")))
                if name and value:
                    specs[name.lower()] = value

    return specs


def parse_description_from_payload(data: dict[str, Any]) -> str:
    for key in ("description", "productDescription", "summary"):
        value = clean_text(str(data.get(key, "")))
        if value and len(value) > 20:
            return value

    sections: list[str] = []
    for entry in data.get("productFeatureDescriptions", []) if isinstance(
        data.get("productFeatureDescriptions"), list
    ) else []:
        if not isinstance(entry, dict):
            continue
        text = clean_text(str(entry.get("value") or entry.get("description") or ""))
        if text:
            sections.append(text)
    return " ".join(sections)


def parse_pdp_payload(data: dict[str, Any]) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}

    product = data
    for key in ("product", "data", "pdpData"):
        nested = data.get(key)
        if isinstance(nested, dict) and (
            nested.get("variantOptions") or nested.get("ratingsResponse") or nested.get("name")
        ):
            product = nested
            break

    rating, review_count = parse_ratings_from_payload(product)
    specs = parse_specs_from_payload(product)
    keyword_text = " ".join(
        [
            clean_text(str(product.get("name", ""))),
            " ".join(f"{k} {v}" for k, v in specs.items()),
        ]
    )
    inferred = infer_from_text(keyword_text)

    seller = ""
    for key in ("sellerName", "seller", "soldBy"):
        value = clean_text(str(product.get(key, "")))
        if value:
            seller = value
            break
    if not seller:
        for entry in product.get("sellers", []) if isinstance(product.get("sellers"), list) else []:
            if isinstance(entry, dict):
                seller = clean_text(str(entry.get("sellerName") or entry.get("name") or ""))
                if seller:
                    break

    fabric = (
        normalize_fabric(specs.get("fabric") or specs.get("material") or specs.get("fabric composition"))
        or inferred["fabric"]
    )

    return {
        "product_name": clean_text(str(product.get("name", ""))),
        "rating": rating,
        "review_count": review_count,
        "size_options": parse_size_options_from_payload(product),
        "color": clean_text(str(specs.get("color", ""))) or inferred["color"],
        "fit_type": clean_text(str(specs.get("fit") or specs.get("fit type", ""))) or inferred["fit_type"],
        "fabric": fabric,
        "sleeve_type": clean_text(str(specs.get("sleeve length") or specs.get("sleeve type", "")))
        or inferred["sleeve_type"],
        "pattern": clean_text(str(specs.get("pattern", ""))) or inferred["pattern"],
        "description": parse_description_from_payload(product),
        "seller": seller,
    }


def is_blocked_page(html: str) -> bool:
    lowered = html.lower()
    return "access denied" in lowered or "don't have permission to access" in lowered


def parse_pdp_html(html: str) -> dict[str, str]:
    if is_blocked_page(html):
        return {}

    soup = BeautifulSoup(html, "html.parser")
    details: dict[str, str] = {}

    for script in soup.select("script[type='application/ld+json']"):
        raw = clean_text(script.get_text())
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("@type") == "Product":
                rating = block.get("aggregateRating", {})
                if isinstance(rating, dict):
                    details["rating"] = format_rating(rating.get("ratingValue", ""))
                    details["review_count"] = extract_number(str(rating.get("reviewCount", "")))
                description = clean_text(str(block.get("description", "")))
                if description and len(description) > 20:
                    details["description"] = description

    body = clean_text(soup.get_text(" ", strip=True))
    rating_match = re.search(r"(\d(?:\.\d)?)\s*(?:out of 5|/ ?5|\★)", body, flags=re.IGNORECASE)
    if rating_match:
        details["rating"] = format_rating(rating_match.group(1))

    review_match = re.search(r"(\d[\d,]*)\s+(?:ratings?|reviews?)", body, flags=re.IGNORECASE)
    if review_match:
        details["review_count"] = extract_number(review_match.group(1))

    for pattern in (
        r"Sold by\s+([^|.\n]{2,80})",
        r"Seller\s*[:\n]\s*([^|.\n]{2,80})",
        r"Marketed by\s+([^|.\n]{2,80})",
        r"View\s+Store\s+([^|.\n(]{2,80})",
        r"View\s+Seller\s+([^|.\n(]{2,80})",
    ):
        match = re.search(pattern, body, flags=re.IGNORECASE)
        if match:
            seller = clean_text(match.group(1))
            if seller.lower() not in {"ajio", "seller"}:
                details["seller"] = seller
                break

    sizes = re.findall(
        r">\s*(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)\s*<",
        html,
        flags=re.IGNORECASE,
    )
    if sizes:
        details["size_options"] = unique_join([size.upper() for size in sizes])

    specs: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = [clean_text(cell.get_text()) for cell in row.select("td, th")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2 and len(cells[0]) <= 40:
            specs[cells[0].lower()] = cells[1]

    for item in soup.select("li"):
        text = clean_text(item.get_text())
        if ":" not in text or len(text) > 120:
            continue
        key, value = text.split(":", 1)
        specs[clean_text(key).lower()] = clean_text(value)

    keyword_text = body + " " + " ".join(f"{k} {v}" for k, v in specs.items())
    inferred = infer_from_text(keyword_text)
    details.setdefault("color", specs.get("color", "") or inferred["color"])
    details.setdefault("fit_type", specs.get("fit", "") or specs.get("fit type", "") or inferred["fit_type"])
    details.setdefault(
        "fabric",
        normalize_fabric(specs.get("fabric") or specs.get("material", "")) or inferred["fabric"],
    )
    details.setdefault(
        "sleeve_type",
        specs.get("sleeve length", "") or specs.get("sleeve type", "") or inferred["sleeve_type"],
    )
    details.setdefault("pattern", specs.get("pattern", "") or inferred["pattern"])

    desc_parts: list[str] = []
    for selector in ("#pdp_product_description", "[class*='description']", "[class*='prod-desc']"):
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text())
            if text and len(text) > 30:
                desc_parts.append(text)
    if desc_parts:
        details["description"] = unique_join(desc_parts)

    return details


def merge_details(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for key, value in extra.items():
        if clean_text(value):
            merged[key] = clean_text(value)
    return merged


def has_meaningful_product_details(details: dict[str, str]) -> bool:
    important_fields = ["rating", "size_options", "fabric", "description", "seller"]
    return sum(1 for field in important_fields if details.get(field)) >= 2


def fetch_product_details(page: Page, product_url: str, product_code: str) -> tuple[dict[str, str], bool]:
    if not product_url:
        return {}, False

    captured: list[dict[str, Any]] = []

    def on_response(response) -> None:
        if "/api/" not in response.url and "/rilfnl" not in response.url:
            return
        try:
            if not response.ok:
                return
            data = response.json()
            if isinstance(data, dict):
                captured.append(data)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        page.wait_for_timeout(5000)
        html = page.content()
    except Exception as exc:
        print(f"[WARN] PDP failed for {product_url}: {exc}")
        return {}, False

    blocked = is_blocked_page(html)
    details = parse_pdp_html(html)
    if blocked:
        print(f"[WARN] Ajio blocked PDP for {product_code or product_url}")
        return details, True

    for payload in captured:
        parsed = parse_pdp_payload(payload)
        if parsed:
            details = merge_details(details, parsed)
        if has_meaningful_product_details(details):
            break

    return details, False


def fetch_product_details_with_retry(
    context: BrowserContext,
    detail_page: Page,
    product_url: str,
    product_code: str,
    blocked_streak: int,
) -> tuple[dict[str, str], int, Page]:
    details, blocked = fetch_product_details(detail_page, product_url, product_code)
    if not blocked:
        return details, 0, detail_page

    blocked_streak += 1
    if blocked_streak < 2:
        return details, blocked_streak, detail_page

    print("[WARN] Resetting browser tab after repeated Ajio PDP blocks", flush=True)
    try:
        detail_page.close()
    except Exception:
        pass
    detail_page = context.new_page()
    detail_page.goto(build_search_page_url(DEFAULT_KEYWORD), wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
    detail_page.wait_for_timeout(3000)
    return details, 0, detail_page


def fetch_search_page(context: BrowserContext, keyword: str, page_num: int) -> dict[str, Any]:
    url = build_search_api_url(keyword, page_num)
    response = context.request.get(
        url,
        headers={
            "accept": "application/json",
            "referer": build_search_page_url(keyword),
        },
    )
    if not response.ok:
        raise RuntimeError(f"search API HTTP {response.status} for page {page_num + 1}")
    return response.json()


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
        "website_name": "Ajio",
        "product_name": product_details.get("product_name", "") or product.get("product_name", ""),
        "product_image": product_details.get("product_image", "") or product.get("product_image", ""),
        "brand": product.get("brand", ""),
        "category": product.get("category", "Women"),
        "subcategory": product.get("subcategory", "Shirts"),
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "rating": product.get("rating", "") or product_details.get("rating", ""),
        "review_count": product.get("review_count", "") or product_details.get("review_count", ""),
        "size_options": product_details.get("size_options", "") or product.get("size_options", "") or title_fallback.get("size_options", ""),
        "color": product_details.get("color", "") or product.get("color", "") or title_fallback.get("color", ""),
        "fit_type": product_details.get("fit_type", "") or product.get("fit_type", "") or title_fallback.get("fit_type", ""),
        "fabric": product_details.get("fabric", "") or product.get("fabric", "") or title_fallback.get("fabric", ""),
        "sleeve_type": product_details.get("sleeve_type", "") or product.get("sleeve_type", "") or title_fallback.get("sleeve_type", ""),
        "pattern": product_details.get("pattern", "") or product.get("pattern", "") or title_fallback.get("pattern", ""),
        "description": product_details.get("description", "") or product.get("description", "") or title_fallback.get("description", ""),
        "availability": product.get("availability", "") or product_details.get("availability", ""),
        "seller": product_details.get("seller", "") or product.get("seller", ""),
        "product_url": product.get("product_url", ""),
        "scrape_date": scrape_time,
    }


def scrape_ajio_women_shirts(
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
        seen_codes: set[str] = set()
        page_num = 0

        while True:
            if max_pages is not None and page_num >= max_pages:
                break

            try:
                payload = fetch_search_page(context, keyword, page_num)
            except Exception as exc:
                print(f"[WARN] Failed to fetch search page {page_num + 1}: {exc}")
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
                if not is_womens_shirt(
                    product_name,
                    product.get("segment", ""),
                    product.get("brick", ""),
                ):
                    continue

                product_code = product.get("product_code", "")
                if not product_code or product_code in seen_codes:
                    continue
                seen_codes.add(product_code)
                products.append(product)
                page_matches += 1

                if max_products is not None and len(products) >= max_products:
                    break

            pagination = payload.get("pagination", {})
            total_pages = 0
            if isinstance(pagination, dict):
                try:
                    total_pages = int(pagination.get("totalPages") or 0)
                except (TypeError, ValueError):
                    total_pages = 0

            print(
                f"[INFO] Page {page_num + 1}"
                f"{f'/{total_pages}' if total_pages else ''}: "
                f"{page_matches} women's shirts ({len(products)} total so far)"
            )

            if max_products is not None and len(products) >= max_products:
                break
            if total_pages and page_num + 1 >= total_pages:
                break

            page_num += 1
            time.sleep(0.35)

        product_details_by_code: dict[str, dict[str, str]] = {}
        if not search_only:
            detail_page = context.new_page()
            blocked_streak = 0
            for index, product in enumerate(products, start=1):
                if index < detail_from:
                    continue
                if detail_to is not None and index > detail_to:
                    continue
                product_code = product.get("product_code", "")
                product_url = product.get("product_url", "")
                if not product_url:
                    continue
                print(f"[INFO] Fetching details {index}/{len(products)}", flush=True)
                details, blocked_streak, detail_page = fetch_product_details_with_retry(
                    context,
                    detail_page,
                    product_url,
                    product_code,
                    blocked_streak,
                )
                product_details_by_code[product_code] = details
                time.sleep(DETAIL_SLEEP_S)
            detail_page.close()
            print(f"[INFO] Full mode: search + PDP for {len(products)} women's shirts")
        else:
            print(
                f"[INFO] Fast mode (search API enriched): {len(products)} women's shirts "
                "(use --full for ratings/seller when Ajio allows product pages)"
            )

        for product in products:
            product_code = product.get("product_code", "")
            rows.append(
                build_product_row(
                    product,
                    product_details_by_code.get(product_code, {}),
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
#   --full          visit product pages for sizes, fabric, seller, ratings
#   --output FILE   CSV output path (default: ajio_women_shirts_raw.csv)
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
    mode_label = "search API only" if search_only else "full (search + PDP)"
    print(
        f"[INFO] Scraping Ajio women's shirts: '{keyword}' | "
        f"mode={mode_label} | max_products={products_label} | max_pages={pages_label}"
    )

    data = scrape_ajio_women_shirts(
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
