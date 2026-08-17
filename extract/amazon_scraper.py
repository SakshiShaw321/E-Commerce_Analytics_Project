from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

AMAZON_BASE_URL = "https://www.amazon.in"
OUTPUT_FILE = "amazon_women_shirts_raw.csv"
DEFAULT_KEYWORD = "women shirts"

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


# ── NEW: Build search URL dynamically from a keyword ──────────────────────────
def build_search_url(keyword: str) -> str:
    """Build an Amazon India search URL from any keyword."""
    return f"{AMAZON_BASE_URL}/s?k={quote_plus(keyword)}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def to_full_url(url: str | None) -> str:
    if not url:
        return ""
    return urljoin(AMAZON_BASE_URL, url)


def extract_number(text: str | None) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"[\d,.]+", cleaned)
    return match.group(0).replace(",", "") if match else ""


def first_text(card: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        tag = card.select_one(selector)
        if tag:
            text = clean_text(tag.get_text())
            if text:
                return text
    return ""


def first_attr(card: BeautifulSoup, selectors: list[str], attr: str) -> str:
    for selector in selectors:
        tag = card.select_one(selector)
        if tag and tag.get(attr):
            value = clean_text(str(tag.get(attr)))
            if value:
                return value
    return ""


def parse_ld_json_blocks(soup: BeautifulSoup) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for script in soup.select("script[type='application/ld+json']"):
        raw = clean_text(script.get_text())
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            blocks.extend([item for item in data if isinstance(item, dict)])
        elif isinstance(data, dict):
            blocks.append(data)
    return blocks


def extract_ld_json_fields(soup: BeautifulSoup) -> dict[str, str]:
    details = {
        "price": "",
        "original_price": "",
        "discount_percent": "",
        "rating": "",
        "review_count": "",
        "availability": "",
    }
    for block in parse_ld_json_blocks(soup):
        aggregate = block.get("aggregateRating", {})
        offers = block.get("offers", {})

        if not details["rating"] and isinstance(aggregate, dict):
            details["rating"] = extract_number(str(aggregate.get("ratingValue", "")))
        if not details["review_count"] and isinstance(aggregate, dict):
            details["review_count"] = extract_number(str(aggregate.get("reviewCount", "")))

        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            if not details["price"]:
                details["price"] = extract_number(str(offer.get("price", "")))
            if not details["availability"]:
                availability = str(offer.get("availability", ""))
                details["availability"] = clean_text(
                    availability.replace("http://schema.org/", "").replace("https://schema.org/", "")
                )
    return details


def infer_fashion_attributes(text_blob: str) -> dict[str, str]:
    blob = text_blob.lower()

    def capture(patterns: list[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, blob)
            if match:
                return clean_text(match.group(1))
        return ""

    return {
        "fit_type": capture([r"fit(?: type)?[:\-\s]+([a-z ]{3,40})"]),
        "fabric": capture([r"(?:material|fabric)(?: composition)?[:\-\s]+([a-z0-9% /]{3,50})"]),
        "sleeve_type": capture([r"sleeve(?: type)?[:\-\s]+([a-z ]{3,40})"]),
        "pattern": capture([r"pattern[:\-\s]+([a-z ]{3,40})"]),
        "color": capture([r"colou?r[:\-\s]+([a-z0-9 /,-]{2,40})"]),
    }


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


def normalize_option_values(values: list[str], max_len: int = 40) -> list[str]:
    cleaned_values: list[str] = []
    for value in values:
        v = clean_text(value)
        if not v:
            continue
        low = v.lower()
        if low in {"select", "choose"}:
            continue
        if "select " in low:
            continue
        if low in {"size", "size:", "colour", "color"}:
            continue
        if "size selection" in low:
            continue
        if low.startswith("make a ") and "selection" in low:
            continue
        if len(v) > max_len:
            continue
        cleaned_values.append(v)
    return cleaned_values


def collect_variant_values(soup: BeautifulSoup, dimension_name: str) -> list[str]:
    selectors = [
        f"#variation_{dimension_name} li",
        f"#variation_{dimension_name} span",
        f"select#native_dropdown_selected_{dimension_name} option",
        f"select#native_dropdown_{dimension_name} option",
        f"[id*='{dimension_name}'] li",
        f"[id*='{dimension_name}'] span",
        f"[id*='{dimension_name}'] option",
    ]
    values: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            candidates = [
                node.get("title"),
                node.get("aria-label"),
                node.get("data-csa-c-content-id"),
                node.get_text(),
            ]
            for candidate in candidates:
                text = clean_text(str(candidate)) if candidate is not None else ""
                if text:
                    values.append(text)
    return values


def infer_keywords(text: str) -> dict[str, str]:
    low = clean_text(text).lower()

    fit = ""
    for candidate in ["regular fit", "slim fit", "relaxed fit", "oversized fit", "comfort fit", "loose fit"]:
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
    ]:
        if candidate in low:
            fabric = candidate.title()
            break

    sleeve = ""
    for candidate in ["full sleeve", "half sleeve", "short sleeve", "long sleeve", "3/4 sleeve", "sleeveless"]:
        if candidate in low:
            sleeve = candidate.title()
            break

    pattern = ""
    for candidate in ["solid", "striped", "printed", "checkered", "floral", "self design"]:
        if candidate in low:
            pattern = candidate.title()
            break

    return {
        "fit_type": fit,
        "fabric": fabric,
        "sleeve_type": sleeve,
        "pattern": pattern,
    }


def extract_review_count_from_text(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    for pattern in (
        r"([\d,]+)\s*(?:global\s+)?(?:ratings?|reviews?)",
        r"([\d,]+)\s+verified",
        r"\(([\d,]+)\)",
        r"([\d,]+)\s+customer",
    ):
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            count = extract_number(match.group(1))
            if count and int(float(count)) >= 1:
                return count
    return ""


INVALID_SELLER_RE = re.compile(
    r"(best sellers? rank|see top \d+|clothing & accessories|^\s*#\d+\s+in\b)",
    re.IGNORECASE,
)


def is_valid_seller(value: str) -> bool:
    seller = clean_text(value)
    if not seller or len(seller) < 2:
        return False
    if seller.startswith("#"):
        return False
    if INVALID_SELLER_RE.search(seller):
        return False
    if re.fullmatch(r"[\d,.\s]+", seller):
        return False
    return True


def is_valid_description(text: str, product_name: str = "") -> bool:
    description = clean_text(text)
    if len(description) < 50:
        return False
    name = clean_text(product_name).lower()
    if name and description.lower() == name:
        return False
    if len(description.split()) <= 4 and description.isupper():
        return False
    if INVALID_SELLER_RE.search(description):
        return False
    return True


def extract_seller_from_soup(soup: BeautifulSoup) -> str:
    for selector in (
        "#sellerProfileTriggerId",
        "#tabular-buybox-truncate-1",
        "a#sellerProfileTriggerId",
        "#offer-display-features .offer-display-feature-text span",
    ):
        tag = soup.select_one(selector)
        if tag:
            seller = clean_text(tag.get_text())
            if is_valid_seller(seller):
                return seller

    merchant = soup.select_one("#merchant-info, #merchantInfoFeature_feature_div")
    if merchant:
        text = clean_text(merchant.get_text())
        for pattern in (
            r"Sold by\s+([^.|]+)",
            r"Ships from\s+([^.|]+)",
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match and is_valid_seller(match.group(1)):
                return clean_text(match.group(1))

    for row in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        spans = [clean_text(span.get_text()) for span in row.select("span")]
        spans = [span for span in spans if span]
        if len(spans) < 2:
            continue
        key = spans[0].replace(":", "").strip().lower()
        value = spans[-1]
        if key in {"seller", "sold by", "ships from"} and is_valid_seller(value):
            return value

    for row in soup.select(
        "#productDetails_techSpec_section_1 tr, "
        "#productDetails_detailBullets_sections1 tr, table.a-keyvalue tr"
    ):
        key_tag = row.select_one("th, td:first-child")
        val_tag = row.select_one("td:last-child")
        if not key_tag or not val_tag:
            continue
        key = clean_text(key_tag.get_text()).lower()
        value = clean_text(val_tag.get_text())
        if key in {"seller", "sold by", "ships from"} and is_valid_seller(value):
            return value

    return ""


def build_description_fallback(product_name: str, details: dict[str, str]) -> str:
    parts: list[str] = []
    name = clean_text(product_name)
    if name:
        parts.append(name)
    for label, key in (
        ("Fabric", "fabric"),
        ("Fit", "fit_type"),
        ("Sleeve", "sleeve_type"),
        ("Pattern", "pattern"),
        ("Color", "color"),
        ("Sizes", "size_options"),
    ):
        value = clean_text(details.get(key, ""))
        if value:
            parts.append(f"{label}: {value}")
    return ". ".join(parts)


def pick_description(
    detail_description: str,
    card_description: str,
    product_name: str,
    detail_fields: dict[str, str] | None = None,
) -> str:
    for candidate in (detail_description, card_description):
        if is_valid_description(candidate, product_name):
            return candidate
    if detail_fields:
        fallback = build_description_fallback(product_name, detail_fields)
        if is_valid_description(fallback, product_name):
            return fallback
    return ""


def normalize_product_url(url: str) -> str:
    full = to_full_url(url)
    if not full:
        return ""

    candidates = [full]
    parsed = urlparse(full)
    if "sspa/click" in parsed.path:
        embedded_urls = parse_qs(parsed.query).get("url", [])
        for embedded in embedded_urls:
            candidates.append(unquote(embedded))

    for candidate in candidates:
        asin_match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", candidate, flags=re.IGNORECASE)
        if asin_match:
            return f"{AMAZON_BASE_URL}/dp/{asin_match.group(1).upper()}"

    return full.split("?")[0]


def infer_sizes_from_product_name(product_name: str) -> str:
    name = clean_text(product_name)
    sku_sizes = re.findall(
        r"(?:^|[-_/(\s])(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)(?:[-_/)\s]|$)",
        name,
        flags=re.IGNORECASE,
    )
    if not sku_sizes:
        return ""
    return unique_join([match.upper() for match in sku_sizes])


def filter_card_description(text: str) -> str:
    if not text:
        return ""
    skip_fragments = (
        "amazon pay",
        "back with",
        "free delivery",
        "cashback",
        "no cost emi",
        "bank offer",
    )
    parts = [clean_text(part) for part in text.split("|")]
    kept = [
        part for part in parts
        if part and not any(skip in part.lower() for skip in skip_fragments)
        and not re.search(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun),", part)
        and "tomorrow" not in part.lower()
    ]
    return " | ".join(kept)


def infer_from_product_name(product_name: str) -> dict[str, str]:
    name = clean_text(product_name)
    low = name.lower()

    color = ""
    color_candidates = [
        "light rose",
        "dark blue",
        "black & white",
        "navy",
        "cream",
        "olive",
        "teal",
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


def is_womens_shirt(product_name: str) -> bool:
    """Keep listings that look like women's shirts/blouses; drop men's and unrelated items."""
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


TRUNCATED_NAME_SUFFIX_RE = re.compile(r"(?:\.\.\.|…)\s*(?:more)?\s*$", re.IGNORECASE)
TRAILING_ELLIPSIS_RE = re.compile(r"(?:\.\.\.|…)\s*$")


def clean_product_name(value: str | None) -> str:
    name = clean_text(value)
    if not name:
        return ""
    name = TRUNCATED_NAME_SUFFIX_RE.sub("", name)
    name = TRAILING_ELLIPSIS_RE.sub("", name)
    return clean_text(name)


def extract_product_name_from_description(description: str) -> str:
    text = clean_text(description)
    if not text:
        return ""

    for pattern in (
        r"^(.+?)\s+-\s+Buy\s+",
        r"^(.+?)\s+-\s+Shop\s+",
        r"^(.+?)\s+-\s+Amazon",
        r"^(.+?)\s+For Only Rs",
        r"^(.+?)\s+Online in India",
        r"^(.+?)\s+OnlineMRP",
        r"^(.+?)\s+Fabric:",
    ):
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return clean_product_name(match.group(1))
    return ""


def is_incomplete_product_name(name: str) -> bool:
    raw = clean_text(name)
    value = clean_product_name(name)
    if not value:
        return True
    if TRUNCATED_NAME_SUFFIX_RE.search(raw) or TRAILING_ELLIPSIS_RE.search(raw):
        return True
    if TRAILING_ELLIPSIS_RE.search(value):
        return True
    if re.search(r"\b\w{1,5}\.{2,}$", value):
        return True
    if not re.search(
        r"\b(?:shirt|shirts|blouse|blouses|top|tops|tunic|tee|tees)\b",
        value,
        re.IGNORECASE,
    ):
        return True
    if re.search(r"\b(?:women|woman|girls?)\s+shirt\s*$", value, re.IGNORECASE) and len(value) < 35:
        return True
    if re.search(r"\bbutton down shirt\s*$", value, re.IGNORECASE) and len(value) < 45:
        return True
    return len(value) < 12


def pick_best_product_name(*candidates: str) -> str:
    for candidate in candidates:
        cleaned = clean_product_name(candidate)
        if cleaned and not is_incomplete_product_name(candidate):
            return cleaned

    cleaned = [clean_product_name(candidate) for candidate in candidates if clean_text(candidate)]
    if not cleaned:
        return ""
    return max(cleaned, key=len)


def build_product_row(
    product: dict[str, Any],
    product_details: dict[str, str],
    scrape_time: str,
) -> dict[str, str]:
    product_url = product.get("product_url", "")
    title_fallback = infer_from_product_name(product.get("product_name", ""))

    price = product.get("price", "") or product_details.get("price", "")
    original_price = product.get("original_price", "") or product_details.get("original_price", "")
    discount_percent = ""
    try:
        if price and original_price:
            p_val = float(price)
            op_val = float(original_price)
            if op_val > 0 and op_val > p_val:
                discount_percent = f"{((op_val - p_val) / op_val) * 100:.2f}"
    except ValueError:
        discount_percent = ""

    return {
        "website_name": "Amazon India",
        "product_name": pick_best_product_name(
            extract_product_name_from_description(product_details.get("description", "")),
            product_details.get("product_name", ""),
            product.get("product_name", ""),
        ),
        "product_image": product.get("product_image", ""),
        "brand": product_details.get("brand", "") or product.get("brand", ""),
        "category": product_details.get("category", "Women Fashion"),
        "subcategory": product_details.get("subcategory", "Shirts"),
        "price": price,
        "original_price": original_price,
        "discount_percent": (
            discount_percent
            or product.get("discount_percent", "")
            or product_details.get("discount_percent", "")
        ),
        "rating": product.get("rating", "") or product_details.get("rating", ""),
        "review_count": product.get("review_count", "") or product_details.get("review_count", ""),
        "size_options": (
            product_details.get("size_options", "")
            or product.get("size_options", "")
            or title_fallback.get("size_options", "")
        ),
        "color": product_details.get("color", "") or product.get("color", "") or title_fallback.get("color", ""),
        "fit_type": (
            product_details.get("fit_type", "")
            or product.get("fit_type", "")
            or title_fallback.get("fit_type", "")
        ),
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
        "pattern": (
            product_details.get("pattern", "")
            or product.get("pattern", "")
            or title_fallback.get("pattern", "")
        ),
        "description": pick_description(
            product_details.get("description", ""),
            filter_card_description(product.get("description", "")),
            product.get("product_name", ""),
            {
                "fabric": (
                    product_details.get("fabric", "")
                    or product.get("fabric", "")
                    or title_fallback.get("fabric", "")
                ),
                "fit_type": (
                    product_details.get("fit_type", "")
                    or product.get("fit_type", "")
                    or title_fallback.get("fit_type", "")
                ),
                "sleeve_type": (
                    product_details.get("sleeve_type", "")
                    or product.get("sleeve_type", "")
                    or title_fallback.get("sleeve_type", "")
                ),
                "pattern": (
                    product_details.get("pattern", "")
                    or product.get("pattern", "")
                    or title_fallback.get("pattern", "")
                ),
                "color": (
                    product_details.get("color", "")
                    or product.get("color", "")
                    or title_fallback.get("color", "")
                ),
                "size_options": (
                    product_details.get("size_options", "")
                    or product.get("size_options", "")
                    or title_fallback.get("size_options", "")
                ),
            },
        ),
        "availability": product_details.get("availability", "") or product.get("availability", ""),
        "seller": (
            product_details.get("seller", "")
            if is_valid_seller(product_details.get("seller", ""))
            else ""
        ),
        "product_url": product_url,
        "scrape_date": scrape_time,
    }


def sanitize_size_values(values: list[str]) -> list[str]:
    allowed_word_sizes = {
        "xxs", "xs", "s", "m", "l", "xl", "xxl",
        "2xl", "3xl", "4xl", "5xl", "6xl",
        "free size", "one size",
    }
    out: list[str] = []
    for value in values:
        v = clean_text(value)
        if not v:
            continue
        low = v.lower()
        if "₹" in v or "in stock" in low or "currently unavailable" in low:
            continue
        if "add to cart" in low or "wishlist" in low:
            continue
        if any(sym in v for sym in ["←", "→", "$"]):
            continue
        if re.fullmatch(r"\d+(?:\.\d+)?", low):
            continue
        if low in allowed_word_sizes:
            out.append(v.upper() if low in {"xs", "s", "m", "l", "xl", "xxl"} else v)
            continue
        if re.fullmatch(r"\d{2,3}", low):
            out.append(v)
            continue
        if re.fullmatch(r"\d{2,3}\s*-\s*\d{2,3}", low):
            out.append(v)
            continue
    return out


def extract_card_size_options(card: BeautifulSoup) -> str:
    size_candidates: list[str] = []
    for node in card.select("span, li, div"):
        text = clean_text(node.get_text())
        if not text:
            continue
        low = text.lower()
        if "size" in low and len(text) <= 80:
            size_candidates.append(text)

    inferred_sizes: list[str] = []
    for candidate in size_candidates:
        match = re.search(r"sizes?\s*[:\-]?\s*(.+)", candidate, flags=re.IGNORECASE)
        if match:
            raw = clean_text(match.group(1))
            if raw:
                parts = [clean_text(p) for p in re.split(r"[,/|]", raw)]
                inferred_sizes.extend([p for p in parts if p and len(p) <= 20])
    return unique_join(inferred_sizes)


def parse_search_page(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.s-result-item.s-asin[data-asin]")
    products: list[dict[str, Any]] = []

    for card in cards:
        asin = card.get("data-asin", "").strip()
        if not asin:
            continue

        url = to_full_url(
            first_attr(
                card,
                [
                    "h2 a.a-link-normal",
                    "a.a-link-normal.s-no-outline",
                    "a[href*='/dp/']",
                ],
                "href",
            )
        )
        if not url:
            continue
        url = normalize_product_url(url)

        image_url = first_attr(
            card,
            ["img.s-image", "img[data-image-latency='s-product-image']", "img"],
            "src",
        )
        product_name = pick_best_product_name(
            first_attr(card, ["img.s-image", "img"], "alt"),
            first_attr(card, ["h2 a", "a.a-link-normal.s-no-outline"], "aria-label"),
            first_text(card, ["h2 a span", "h2 span", "h2"]),
        )
        price_text = first_text(card, ["span.a-price > span.a-offscreen", "a span.a-price > span.a-offscreen"])
        original_price_text = first_text(
            card,
            [
                "span.a-price.a-text-price > span.a-offscreen",
                "span[data-a-strike='true'] span.a-offscreen",
            ],
        )
        discount_text = first_text(
            card, ["span.s-coupon-unclipped", "span.a-color-price", "span.a-size-base.a-color-secondary"]
        )
        rating_text = first_text(card, ["span.a-icon-alt", "i.a-icon-star-small span"])
        review_count_text = first_text(
            card,
            [
                "span.a-size-base.s-underline-text",
                "a[href*='#customerReviews'] span.a-size-base",
                "span[aria-label*='ratings']",
                "a.a-link-normal[href*='#customerReviews']",
            ],
        )
        if not review_count_text:
            for tag in card.select("[aria-label]"):
                aria = clean_text(tag.get("aria-label", ""))
                parsed = extract_review_count_from_text(aria)
                if parsed:
                    review_count_text = parsed
                    break
        if not extract_number(review_count_text):
            review_count_text = extract_review_count_from_text(rating_text) or review_count_text
        delivery_text = first_text(
            card,
            [
                "span.a-color-base.a-text-bold",
                "div[data-cy='delivery-recipe'] span",
                "div.a-row.a-size-base.a-color-secondary span",
            ],
        )
        badge_text = first_text(
            card,
            [
                "span.a-badge-text",
                "span.a-color-secondary",
                "span.a-color-base",
            ],
        )

        card_descriptions = [
            clean_text(node.get_text())
            for node in card.select("div.a-row.a-size-base.a-color-secondary span, ul li span")
            if clean_text(node.get_text())
        ]
        card_blob = filter_card_description(" | ".join(card_descriptions))
        title_inferred = infer_from_product_name(product_name)
        inferred = infer_fashion_attributes(card_blob)
        card_sizes = extract_card_size_options(card)

        brand_text = first_text(card, ["h5.s-line-clamp-1", "span.a-size-base-plus.a-color-base"])
        if not brand_text and product_name:
            brand_text = product_name.split()[0]

        products.append(
            {
                "asin": asin,
                "product_name": product_name,
                "product_url": url,
                "product_image": image_url,
                "price": extract_number(price_text),
                "original_price": extract_number(original_price_text),
                "discount_percent": extract_number(discount_text),
                "rating": extract_number(rating_text),
                "review_count": extract_number(review_count_text) or extract_review_count_from_text(review_count_text),
                "brand": clean_text(brand_text),
                "color": inferred["color"] or title_inferred.get("color", ""),
                "availability": clean_text(delivery_text),
                "badge": clean_text(badge_text),
                "size_options": card_sizes or title_inferred.get("size_options", ""),
                "fit_type": inferred["fit_type"] or title_inferred.get("fit_type", ""),
                "fabric": inferred["fabric"] or title_inferred.get("fabric", ""),
                "sleeve_type": inferred["sleeve_type"] or title_inferred.get("sleeve_type", ""),
                "pattern": inferred["pattern"] or title_inferred.get("pattern", ""),
                "description": card_blob,
            }
        )

    return products


def is_blocked_page(html: str) -> bool:
    lowered = html.lower()
    return (
        "503 - service unavailable error" in lowered
        or "enter the characters you see below" in lowered
        or "sorry, we just need to make sure you're not a robot" in lowered
    )


def has_meaningful_product_details(details: dict[str, str]) -> bool:
    important_fields = [
        "price", "rating", "review_count", "size_options",
        "color", "availability", "seller",
    ]
    return sum(1 for field in important_fields if details.get(field)) >= 3


def get_next_page_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    next_link = soup.select_one("a.s-pagination-next")
    if not next_link:
        return ""

    class_list = next_link.get("class", [])
    if "s-pagination-disabled" in class_list:
        return ""

    href = next_link.get("href")
    return to_full_url(href)


def extract_product_description(soup: BeautifulSoup) -> str:
    """Build description from bullets, product text, and structured data."""
    sections: list[str] = []
    skip_phrases = {
        "about this item",
        "brief content visible, double tap to read full content.",
        "make a size selection",
    }

    for block in parse_ld_json_blocks(soup):
        desc = block.get("description")
        if isinstance(desc, str):
            text = clean_text(desc)
            if is_valid_description(text):
                sections.append(text)

    bullets: list[str] = []
    for li in soup.select("#feature-bullets li span.a-list-item, #feature-bullets li"):
        text = clean_text(li.get_text())
        if not text or text.lower() in skip_phrases:
            continue
        if text.lower().startswith("make a ") and "selection" in text.lower():
            continue
        bullets.append(text)
    if bullets:
        sections.append(". ".join(bullets))

    paragraph_parts: list[str] = []
    for node in soup.select("#productDescription p, #productDescription_feature_div p"):
        text = clean_text(node.get_text())
        if text:
            paragraph_parts.append(text)
    if not paragraph_parts:
        for selector in ("#productDescription", "#productDescription_feature_div"):
            tag = soup.select_one(selector)
            if tag:
                text = clean_text(tag.get_text())
                if text:
                    paragraph_parts.append(text)
                    break
    if paragraph_parts:
        sections.append(" ".join(paragraph_parts))

    seen: set[str] = set()
    unique_sections: list[str] = []
    for section in sections:
        key = section.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        unique_sections.append(section)
    return " ".join(unique_sections)


def parse_bullets_and_details(soup: BeautifulSoup) -> dict[str, str]:
    text_blob = " ".join(
        [
            clean_text(li.get_text())
            for li in soup.select("#feature-bullets li span.a-list-item")
        ]
    ).lower()

    details: dict[str, str] = {
        "size_options": "",
        "color": "",
        "fit_type": "",
        "fabric": "",
        "sleeve_type": "",
        "pattern": "",
        "seller": "",
        "subcategory": "Shirts",
        "category": "Women Fashion",
        "price": "",
        "original_price": "",
        "discount_percent": "",
        "rating": "",
        "review_count": "",
        "description": "",
    }

    table_selectors = [
        "#productDetails_techSpec_section_1 tr",
        "#productDetails_detailBullets_sections1 tr",
        "#productOverview_feature_div tr",
        "table.prodDetTable tr",
        "table.a-keyvalue tr",
    ]

    for selector in table_selectors:
        for row in soup.select(selector):
            key_tag = row.select_one("th, td:first-child")
            val_tag = row.select_one("td:last-child")
            if not key_tag or not val_tag:
                continue
            key = clean_text(key_tag.get_text()).lower()
            value = clean_text(val_tag.get_text())

            if "brand" in key and not details.get("brand"):
                details["brand"] = value
            elif "fit" in key and not details["fit_type"]:
                details["fit_type"] = value
            elif ("material" in key or "fabric" in key) and not details["fabric"]:
                details["fabric"] = value
            elif "sleeve" in key and not details["sleeve_type"]:
                details["sleeve_type"] = value
            elif "pattern" in key and not details["pattern"]:
                details["pattern"] = value
            elif key in {"seller", "sold by", "ships from"} and not details["seller"]:
                if is_valid_seller(value):
                    details["seller"] = value
            elif "colour" in key and not details["color"]:
                details["color"] = value
            elif "color" in key and not details["color"]:
                details["color"] = value
            elif "size" in key and not details["size_options"]:
                details["size_options"] = value

    for row in soup.select("#poExpander tr, #productOverview_feature_div div.a-fixed-left-grid"):
        cells = [clean_text(cell.get_text()) for cell in row.select("span, td, th")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2 and len(cells[0]) <= 40:
            key = cells[0].lower()
            value = cells[-1]
            if "fit" in key and not details["fit_type"]:
                details["fit_type"] = value
            elif ("material" in key or "fabric" in key) and not details["fabric"]:
                details["fabric"] = value
            elif "sleeve" in key and not details["sleeve_type"]:
                details["sleeve_type"] = value
            elif "pattern" in key and not details["pattern"]:
                details["pattern"] = value
            elif ("colour" in key or "color" in key) and not details["color"]:
                details["color"] = value

    for li in soup.select("#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li"):
        spans = [clean_text(span.get_text()) for span in li.select("span")]
        spans = [s for s in spans if s]
        if len(spans) < 2:
            continue
        key = spans[0].replace(":", "").strip().lower()
        value = spans[-1]
        if not value:
            continue

        if "brand" in key and not details.get("brand"):
            details["brand"] = value
        elif "fit" in key and not details["fit_type"]:
            details["fit_type"] = value
        elif ("material" in key or "fabric" in key) and not details["fabric"]:
            details["fabric"] = value
        elif "sleeve" in key and not details["sleeve_type"]:
            details["sleeve_type"] = value
        elif "pattern" in key and not details["pattern"]:
            details["pattern"] = value
        elif ("colour" in key or "color" in key) and not details["color"]:
            details["color"] = value
        elif "size" in key and not details["size_options"]:
            details["size_options"] = value

    if not details["fit_type"] and "fit type" in text_blob:
        fit_match = re.search(r"fit type[:\s]+([a-zA-Z ]+)", text_blob)
        details["fit_type"] = clean_text(fit_match.group(1)) if fit_match else ""

    if not details["fabric"] and "material" in text_blob:
        fabric_match = re.search(r"material(?: composition)?[:\s]+([a-zA-Z ]+)", text_blob)
        details["fabric"] = clean_text(fabric_match.group(1)) if fabric_match else ""

    if not details["pattern"] and "pattern" in text_blob:
        pattern_match = re.search(r"pattern[:\s]+([a-zA-Z ]+)", text_blob)
        details["pattern"] = clean_text(pattern_match.group(1)) if pattern_match else ""

    if not details["sleeve_type"] and "sleeve" in text_blob:
        sleeve_match = re.search(r"sleeve(?: type)?[:\s]+([a-zA-Z ]+)", text_blob)
        details["sleeve_type"] = clean_text(sleeve_match.group(1)) if sleeve_match else ""

    if not details["size_options"]:
        size_match = re.search(r"sizes?[:\s]+([a-zA-Z0-9, /-]+)", text_blob)
        details["size_options"] = clean_text(size_match.group(1)) if size_match else ""

    details["description"] = extract_product_description(soup)
    seller = extract_seller_from_soup(soup)
    if seller:
        details["seller"] = seller
    elif not is_valid_seller(details.get("seller", "")):
        details["seller"] = ""
    return details


def parse_product_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    details = parse_bullets_and_details(soup)
    ld_json_fields = extract_ld_json_fields(soup)

    breadcrumb_nodes = soup.select("#wayfinding-breadcrumbs_feature_div ul li a")
    breadcrumb = [clean_text(node.get_text()) for node in breadcrumb_nodes if clean_text(node.get_text())]
    if breadcrumb:
        details["category"] = breadcrumb[0]
        details["subcategory"] = breadcrumb[-1]

    size_sources: list[str] = collect_variant_values(soup, "size_name")

    for option in soup.select("#native_dropdown_selected_size_name option, #native_dropdown_name option"):
        value = clean_text(option.get_text())
        if value and "select" not in value.lower():
            size_sources.append(value)

    for node in soup.select(
        "#variation_size_name li, #variation_size_name span, "
        "#size_name_0, #variation_size_name .a-button-text"
    ):
        value = clean_text(node.get_text())
        if value and "select" not in value.lower() and len(value) <= 24:
            size_sources.append(value)

    detail_bullets = [
        clean_text(node.get_text())
        for node in soup.select("#detailBullets_feature_div li, #feature-bullets li")
        if clean_text(node.get_text())
    ]
    for bullet in detail_bullets:
        match = re.search(r"sizes?\s*[:\-]?\s*(.+)", bullet, flags=re.IGNORECASE)
        if match:
            raw = clean_text(match.group(1))
            if raw:
                size_sources.extend([clean_text(x) for x in re.split(r"[,/|]", raw)])

    parsed_sizes = normalize_option_values(size_sources, max_len=30)
    parsed_sizes = sanitize_size_values(parsed_sizes)
    details["size_options"] = unique_join(parsed_sizes) or details.get("size_options", "")

    color_tag = soup.select_one("#inline-twister-expanded-dimension-text-color_name")
    if color_tag:
        details["color"] = clean_text(color_tag.get_text())
    else:
        color_values = collect_variant_values(soup, "color_name")
        color_values.extend(
            [
                clean_text(node.get("alt", ""))
                for node in soup.select("#variation_color_name img[alt], [id*='color_name'] img[alt]")
                if clean_text(node.get("alt", ""))
            ]
        )
        color_values = normalize_option_values(color_values, max_len=40)
        if color_values:
            details["color"] = unique_join(color_values)

    page_price = first_text(
        soup,
        [
            "#corePrice_feature_div span.a-price span.a-offscreen",
            "#corePriceDisplay_desktop_feature_div span.a-price span.a-offscreen",
            "#tp_price_block_total_price_ww span.a-offscreen",
        ],
    )
    page_original_price = first_text(
        soup,
        [
            "#corePrice_feature_div span.a-price.a-text-price span.a-offscreen",
            "#corePriceDisplay_desktop_feature_div span.a-price.a-text-price span.a-offscreen",
            "#listPrice_feature_div span.a-offscreen",
        ],
    )
    page_discount = first_text(
        soup,
        [
            "#corePrice_feature_div span.savingsPercentage",
            "#corePriceDisplay_desktop_feature_div span.savingsPercentage",
            "span.reinventPriceSavingsPercentageMargin",
        ],
    )
    page_rating = first_attr(
        soup,
        ["#acrPopover", "#acrPopover span", "span[data-hook='rating-out-of-text']"],
        "title",
    ) or first_attr(
        soup,
        ["#acrPopover", "#acrPopover span", "i.a-icon-star span.a-icon-alt"],
        "aria-label",
    ) or first_text(
        soup, ["#acrPopover", "span[data-hook='rating-out-of-text']", "i.a-icon-star span.a-icon-alt"]
    )
    page_review_count = first_text(
        soup,
        [
            "#acrCustomerReviewText",
            "#acrCustomerReviewLink span",
            "span[data-hook='total-review-count']",
            "span#acrCustomerReviewText",
        ],
    )
    if not extract_number(page_review_count):
        popover_label = first_attr(
            soup,
            ["#acrPopover", "#acrCustomerReviewLink", "a[data-hook='see-all-reviews-link-foot']"],
            "aria-label",
        )
        page_review_count = extract_review_count_from_text(popover_label) or page_review_count

    product_title = first_text(soup, ["#productTitle", "span#productTitle"])
    title_inferred = infer_from_product_name(product_title)

    details["price"] = extract_number(page_price) or ld_json_fields.get("price", "")
    details["original_price"] = extract_number(page_original_price)
    details["discount_percent"] = extract_number(page_discount)
    details["rating"] = extract_number(page_rating) or ld_json_fields.get("rating", "")
    details["review_count"] = extract_number(page_review_count) or ld_json_fields.get("review_count", "")

    keyword_text = " ".join(
        [
            clean_text(node.get_text())
            for node in soup.select(
                "#productTitle, #feature-bullets, #detailBullets_feature_div, #productDescription"
            )
            if clean_text(node.get_text())
        ]
    )
    inferred_keywords = infer_keywords(keyword_text)
    for key in ["fit_type", "fabric", "sleeve_type", "pattern"]:
        if not details.get(key):
            details[key] = inferred_keywords.get(key, "") or title_inferred.get(key, "")

    if product_title and not details.get("product_name"):
        details["product_name"] = product_title

    ld_json_names: list[str] = []
    for block in parse_ld_json_blocks(soup):
        name = block.get("name")
        if isinstance(name, str) and name:
            ld_json_names.append(clean_text(name))

    og_title = first_attr(soup, ["meta[property='og:title']", "meta[name='og:title']"], "content")
    og_name = clean_product_name(og_title.split(":")[0] if og_title else "")
    meta_description = first_attr(soup, ["meta[name='description']"], "content")

    details["product_name"] = pick_best_product_name(
        extract_product_name_from_description(details.get("description", "")),
        extract_product_name_from_description(meta_description or ""),
        product_title,
        og_name,
        *ld_json_names,
        details.get("product_name", ""),
    )

    seller = extract_seller_from_soup(soup)
    if seller:
        details["seller"] = seller
    elif not is_valid_seller(details.get("seller", "")):
        details["seller"] = ""

    brand_tag = soup.select_one("#bylineInfo")
    if brand_tag and not details.get("brand"):
        details["brand"] = (
            clean_text(brand_tag.get_text()).replace("Visit the ", "").replace(" Store", "")
        )

    availability_text = first_text(
        soup,
        [
            "#availability span",
            "#availabilityInsideBuyBox_feature_div span",
            "#outOfStock span",
            "#mir-layout-DELIVERY_BLOCK-slot-PRIMARY_DELIVERY_MESSAGE_LARGE span",
            "#mir-layout-DELIVERY_BLOCK-slot-DELIVERY_MESSAGE span",
        ],
    )
    details["availability"] = availability_text or ld_json_fields.get("availability", "")

    if not details["original_price"] and details["price"] and details["discount_percent"]:
        try:
            p_val = float(details["price"])
            d_val = float(details["discount_percent"])
            if 0 < d_val < 100:
                original = p_val / (1 - d_val / 100)
                details["original_price"] = f"{original:.2f}"
        except ValueError:
            pass

    return details


def parse_product_name_from_html(html: str) -> dict[str, str]:
    if is_blocked_page(html):
        return {}

    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []

    for block in parse_ld_json_blocks(soup):
        name = block.get("name")
        if isinstance(name, str) and name:
            candidates.append(clean_text(name))
        description = block.get("description")
        if isinstance(description, str):
            candidates.append(extract_product_name_from_description(description))

    product_title = first_text(soup, ["#productTitle", "span#productTitle"])
    if product_title:
        candidates.append(product_title)

    og_title = first_attr(soup, ["meta[property='og:title']", "meta[name='og:title']"], "content")
    if og_title:
        candidates.append(clean_product_name(og_title.split(":")[0]))

    meta_description = first_attr(soup, ["meta[name='description']"], "content")
    description = clean_text(meta_description)
    if description:
        candidates.append(extract_product_name_from_description(description))

    product_name = pick_best_product_name(*candidates)
    return {
        "product_name": product_name,
        "description": description,
    }


def wait_for_product_page(page) -> None:
    selectors = [
        "#productTitle",
        "#title",
        "#feature-bullets",
        "#corePrice_feature_div",
        "script[type='application/ld+json']",
    ]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=8000, state="attached")
            return
        except Exception:
            continue
    page.wait_for_timeout(1500)


def fetch_product_name_with_playwright(page, product_url: str) -> dict[str, str]:
    clean_url = normalize_product_url(product_url)
    for attempt in range(3):
        try:
            page.goto(clean_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_product_page(page)
            page.wait_for_timeout(800 + (attempt * 400))
            html = page.content()
            if is_blocked_page(html):
                time.sleep(1 + attempt)
                continue
            return parse_product_name_from_html(html)
        except Exception:
            time.sleep(1 + attempt)
    return {}


def fetch_product_details_with_playwright(page, product_url: str) -> dict[str, str]:
    clean_url = normalize_product_url(product_url)
    last_details: dict[str, str] = {}
    for attempt in range(3):
        try:
            page.goto(clean_url, wait_until="domcontentloaded", timeout=60000)
            wait_for_product_page(page)
            page.wait_for_timeout(1200 + (attempt * 800))
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(400)
            except Exception:
                pass
            html = page.content()
            if is_blocked_page(html):
                time.sleep(2 + attempt)
                continue

            details = parse_product_page(html)
            last_details = details
            if has_meaningful_product_details(details):
                return details

            time.sleep(1.5 + attempt)
            page.reload(wait_until="domcontentloaded", timeout=60000)
            wait_for_product_page(page)
            page.wait_for_timeout(1200 + (attempt * 800))
            html = page.content()
            if is_blocked_page(html):
                continue
            details = parse_product_page(html)
            last_details = details
            if has_meaningful_product_details(details):
                return details
        except Exception:
            time.sleep(1 + attempt)
            continue
    if last_details.get("price") or last_details.get("product_name"):
        return last_details
    print(f"[WARN] Product page returned sparse data: {clean_url}")
    return last_details


def fetch_product_description_with_playwright(page, product_url: str) -> str:
    for attempt in range(3):
        try:
            page.goto(product_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(800 + (attempt * 400))
            html = page.content()
            if is_blocked_page(html):
                time.sleep(1 + attempt)
                continue

            description = extract_product_description(BeautifulSoup(html, "html.parser"))
            if description:
                return description

            time.sleep(1 + attempt)
            page.reload(wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(800 + (attempt * 400))
            html = page.content()
            if is_blocked_page(html):
                continue
            description = extract_product_description(BeautifulSoup(html, "html.parser"))
            if description:
                return description
        except Exception:
            time.sleep(1 + attempt)
            continue
    return ""


# ── CHANGED: Added `keyword` param, replaced hardcoded URL, graceful block handling ──
def scrape_amazon_women_shirts(
    keyword: str = DEFAULT_KEYWORD,
    max_pages: int | None = None,
    max_products: int | None = None,
    search_only: bool = True,
    fetch_descriptions: bool = False,
    fetch_full_names: bool = False,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scrape_time = datetime.now(timezone.utc).isoformat()  # captured once at top

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        except Exception:
            browser = p.chromium.launch(
                headless=False,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            viewport={"width": 1366, "height": 768},
        )
        page = context.new_page()
        page.set_extra_http_headers(
            {
                "accept-language": "en-IN,en-US;q=0.9,en;q=0.8",
                "upgrade-insecure-requests": "1",
            }
        )

        products: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        visited_pages: set[str] = set()

        # ── CHANGED: build URL dynamically from keyword ──
        search_url = build_search_url(keyword)
        page_count = 0

        while search_url and search_url not in visited_pages:
            visited_pages.add(search_url)
            page_count += 1
            if max_pages is not None and page_count > max_pages:
                break

            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_selector("div.s-result-item[data-asin]", timeout=15000)
            html = page.content()

            # ── CHANGED: graceful break instead of crashing MCP server ──
            if is_blocked_page(html):
                print(f"[WARN] Amazon blocked request on page {page_count}. Stopping early.")
                break

            search_products = parse_search_page(html)
            page_matches = 0
            for product in search_products:
                product_name = product.get("product_name", "")
                if not is_womens_shirt(product_name):
                    continue

                product_url = product.get("product_url", "")
                if not product_url or product_url in seen_urls:
                    continue
                seen_urls.add(product_url)
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

            search_url = get_next_page_url(html)
            time.sleep(0.4)

        product_details_by_url: dict[str, dict[str, str]] = {}
        if not search_only or fetch_descriptions or fetch_full_names:
            detail_page = context.new_page()
            detail_page.set_extra_http_headers(
                {
                    "accept-language": "en-IN,en-US;q=0.9,en;q=0.8",
                    "upgrade-insecure-requests": "1",
                }
            )
            for index, product in enumerate(products, start=1):
                url = product.get("product_url", "")
                if not url:
                    continue
                if search_only and fetch_full_names and not fetch_descriptions:
                    print(f"[INFO] Fetching full name {index}/{len(products)}")
                    product_details_by_url[url] = fetch_product_name_with_playwright(detail_page, url)
                    time.sleep(0.5)
                elif search_only:
                    print(f"[INFO] Fetching description {index}/{len(products)}")
                    description = fetch_product_description_with_playwright(detail_page, url)
                    product_details_by_url[url] = {"description": description}
                    time.sleep(0.5)
                else:
                    print(f"[INFO] Fetching details {index}/{len(products)}")
                    product_details_by_url[url] = fetch_product_details_with_playwright(detail_page, url)
                    time.sleep(0.8)
            detail_page.close()

        if search_only and not fetch_descriptions and not fetch_full_names:
            print(
                f"[INFO] Fast mode (search only): {len(products)} women's shirts "
                "(use --full-names or --full for complete product titles)"
            )
        elif search_only and fetch_full_names:
            print(f"[INFO] Search + full product names for {len(products)} women's shirts")
        elif search_only:
            print(f"[INFO] Fast mode: search data + descriptions for {len(products)} women's shirts")

        for product in products:
            product_url = product.get("product_url", "")
            if not product_url:
                continue

            row = build_product_row(
                product,
                product_details_by_url.get(product_url, {}),
                scrape_time,
            )
            rows.append(row)

            if max_products is not None and len(rows) >= max_products:
                break

        browser.close()

    return rows


# ── CHANGED: now returns the file path (used by MCP server to report back) ──
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
    """Parse CLI limit: 'all' / 'none' / '0' → no limit; otherwise an integer cap."""
    if value is None:
        return None
    if value.lower() in {"all", "none", "0"}:
        return None
    return int(value)


# ── CLI: [keyword] [max_products] [max_pages]
#   --full          detail-page scraping (all fields)
#   --full-names    visit product pages for complete titles only
#   --descriptions  fast mode + visit each product page for description only
#   --no-descriptions  fast mode, search pages only (default)
#   --output FILE   CSV output path (default: amazon_women_shirts_raw.csv)
if __name__ == "__main__":
    flags = {arg for arg in sys.argv[1:] if arg.startswith("--")}
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    output_file = OUTPUT_FILE
    if "--output" in flags:
        out_idx = sys.argv.index("--output")
        if out_idx + 1 < len(sys.argv):
            output_file = sys.argv[out_idx + 1]
    search_only = "--full" not in flags
    fetch_full_names = "--full-names" in flags
    if search_only:
        fetch_descriptions = "--descriptions" in flags and "--no-descriptions" not in flags
    else:
        fetch_descriptions = True
        fetch_full_names = False

    keyword = args[0] if args else DEFAULT_KEYWORD
    max_products = _parse_limit_arg(args[1] if len(args) > 1 else None)
    max_pages = _parse_limit_arg(args[2] if len(args) > 2 else None)

    products_label = max_products if max_products is not None else "all"
    pages_label = max_pages if max_pages is not None else "all"
    if not search_only:
        mode_label = "full (detail pages)"
    elif fetch_full_names:
        mode_label = "search + full product names"
    elif fetch_descriptions:
        mode_label = "search + descriptions"
    else:
        mode_label = "search only (no product pages)"
    print(
        f"[INFO] Scraping women's shirts: '{keyword}' | "
        f"mode={mode_label} | max_products={products_label} | max_pages={pages_label}"
    )
    data = scrape_amazon_women_shirts(
        keyword=keyword,
        max_pages=max_pages,
        max_products=max_products,
        search_only=search_only,
        fetch_descriptions=fetch_descriptions,
        fetch_full_names=fetch_full_names,
    )
    path = save_to_csv(data, output_file)
    print(f"[INFO] Scraped {len(data)} products -> saved to {path}", flush=True)
    if data:
        bad_seller = sum(1 for row in data if not is_valid_seller(row.get("seller", "")))
        short_desc = sum(
            1
            for row in data
            if not is_valid_description(row.get("description", ""), row.get("product_name", ""))
        )
        if bad_seller:
            print(f"[WARN] {bad_seller}/{len(data)} rows still have missing/invalid seller", flush=True)
        if short_desc:
            print(f"[WARN] {short_desc}/{len(data)} rows have short descriptions", flush=True)