from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, quote_plus

from bs4 import BeautifulSoup
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright

FLIPKART_BASE_URL = "https://www.flipkart.com"
OUTPUT_FILE = "flipkart_women_shirts_raw.csv"
DEFAULT_KEYWORD = "women shirts"
NAVIGATION_TIMEOUT_MS = 25_000
ACTION_TIMEOUT_MS = 12_000
DETAIL_SLEEP_S = 0.5

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

SKIP_CARD_TOKENS = {
    "hot deal",
    "sponsored",
    "ad",
    "bestseller",
    "trending",
    "new arrival",
}


def build_search_url(keyword: str) -> str:
    return f"{FLIPKART_BASE_URL}/search?q={quote_plus(keyword)}"


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.split()).strip()


def to_full_url(url: str | None) -> str:
    if not url:
        return ""
    return urljoin(FLIPKART_BASE_URL, url)


def extract_number(text: str | None) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"[\d,.]+", cleaned)
    return match.group(0).replace(",", "") if match else ""


def first_text(soup: BeautifulSoup, selectors: list[str]) -> str:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            text = clean_text(tag.get_text())
            if text:
                return text
    return ""


def first_attr(soup: BeautifulSoup, selectors: list[str], attr: str) -> str:
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag and tag.get(attr):
            value = clean_text(str(tag.get(attr)))
            if value:
                return value
    return ""


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


def extract_rating_from_text(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    match = re.search(r"(\d(?:\.\d)?)\s*(?:★|out of|stars?)?", cleaned, flags=re.IGNORECASE)
    if match:
        value = float(match.group(1))
        if 0 < value <= 5:
            return str(value)
    return ""


def extract_review_count_from_text(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    patterns = [
        r"([\d,]+)\s*(?:ratings?|reviews?)",
        r"\(([\d,]+)\)",
        r"([\d,]+)\s*$",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            count = extract_number(match.group(1))
            if count and int(float(count)) >= 1:
                return count
    return ""


def parse_sizes_from_text(text: str) -> list[str]:
    allowed_word_sizes = {
        "xxs", "xs", "s", "m", "l", "xl", "xxl",
        "2xl", "3xl", "4xl", "5xl", "6xl",
        "free size", "one size",
    }
    sizes: list[str] = []
    for token in re.split(r"[,/|]", text):
        value = clean_text(token)
        if not value:
            continue
        low = value.lower()
        if low in allowed_word_sizes:
            sizes.append(value.upper() if low in {"xs", "s", "m", "l", "xl", "xxl"} else value)
        elif re.fullmatch(r"\d{2,3}", low):
            sizes.append(value)
        elif re.fullmatch(r"\d{2,3}\s*-\s*\d{2,3}", low):
            sizes.append(value)
    return sizes


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


def is_womens_shirt(product_name: str) -> bool:
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


TRUNCATED_NAME_SUFFIX_RE = re.compile(r"(?:\.\.\.|…)\s*more\s*$", re.IGNORECASE)
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
        r"^(.+?)\s+For Only Rs",
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
    if not re.search(r"\b(?:shirt|shirts|blouse|blouses|top|tunic|tee|tees)\b", value, re.IGNORECASE):
        return True
    if re.search(r"\(\s*pack\s*$", value, re.IGNORECASE):
        return True
    if re.search(r"\b\w{1,5}\.{2,}$", value):
        return True
    return len(value) < 10


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
    discount_percent = product.get("discount_percent", "") or product_details.get("discount_percent", "")
    try:
        if price and original_price and not discount_percent:
            p_val = float(price)
            op_val = float(original_price)
            if op_val > 0 and op_val > p_val:
                discount_percent = f"{((op_val - p_val) / op_val) * 100:.2f}"
    except ValueError:
        pass

    return {
        "website_name": "Flipkart",
        "product_name": pick_best_product_name(
            extract_product_name_from_description(product_details.get("description", "")),
            product_details.get("product_name", ""),
            product.get("product_name", ""),
        ),
        "product_image": product_details.get("product_image", "") or product.get("product_image", ""),
        "brand": product_details.get("brand", "") or product.get("brand", ""),
        "category": product_details.get("category", "Women Fashion"),
        "subcategory": product_details.get("subcategory", "Shirts"),
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
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
        "description": product_details.get("description", "") or product.get("description", ""),
        "availability": product_details.get("availability", "") or product.get("availability", ""),
        "seller": product_details.get("seller", ""),
        "product_url": product_url,
        "scrape_date": scrape_time,
    }


def parse_search_card(card: BeautifulSoup) -> dict[str, Any] | None:
    anchor = card.select_one('a[href*="/p/"]')
    if not anchor:
        return None

    href = anchor.get("href", "")
    if not href:
        return None

    product_url = to_full_url(href.split("?")[0])
    image_tag = card.select_one("img")
    image_url = clean_text(image_tag.get("src", "")) if image_tag else ""
    anchor_title = clean_product_name(
        str(anchor.get("title", "") or anchor.get("aria-label", "") or "")
    )
    image_title = ""
    if image_tag:
        image_title = clean_product_name(
            str(image_tag.get("alt", "") or image_tag.get("title", "") or "")
        )

    brand = ""
    product_name = ""
    price = ""
    original_price = ""
    discount_percent = ""
    rating = ""
    review_count = ""
    availability = ""
    non_meta: list[str] = []

    for text in card.stripped_strings:
        value = clean_text(str(text))
        if not value:
            continue
        low = value.lower()
        if low in SKIP_CARD_TOKENS:
            continue
        if low in {"more", "...more"} or value.endswith("...more"):
            continue
        if value.startswith("₹"):
            amount = extract_number(value)
            if not price:
                price = amount
            elif not original_price:
                original_price = amount
            continue
        if "off" in low and "%" in value:
            discount_percent = extract_number(value)
            continue
        if "only few left" in low or "out of stock" in low:
            availability = value
            continue
        if not rating and ("★" in value or re.search(r"\d\.\d", value)):
            parsed_rating = extract_rating_from_text(value)
            if parsed_rating:
                rating = parsed_rating
                parsed_reviews = extract_review_count_from_text(value)
                if parsed_reviews:
                    review_count = parsed_reviews
                continue
        if not review_count and ("rating" in low or "review" in low or value.startswith("(")):
            parsed_reviews = extract_review_count_from_text(value)
            if parsed_reviews:
                review_count = parsed_reviews
                continue
        non_meta.append(value)

    if len(non_meta) >= 2:
        brand = non_meta[0]
        product_name = non_meta[1]
    elif len(non_meta) == 1:
        product_name = non_meta[0]

    product_name = pick_best_product_name(
        f"{brand} {product_name}" if brand and product_name else product_name,
        product_name,
        anchor_title,
        image_title,
    )

    if not product_name:
        return None

    title_fallback = infer_from_product_name(product_name)
    return {
        "product_name": product_name,
        "product_url": product_url,
        "product_image": image_url,
        "price": price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "rating": rating,
        "review_count": review_count,
        "brand": brand,
        "color": title_fallback.get("color", ""),
        "availability": availability,
        "fit_type": title_fallback.get("fit_type", ""),
        "fabric": title_fallback.get("fabric", ""),
        "sleeve_type": title_fallback.get("sleeve_type", ""),
        "pattern": title_fallback.get("pattern", ""),
        "description": "",
    }


def parse_search_page(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    products: list[dict[str, Any]] = []
    seen_paths: set[str] = set()

    for card in soup.select("div[data-tkid]"):
        product = parse_search_card(card)
        if not product:
            continue

        path = product["product_url"].replace(FLIPKART_BASE_URL, "")
        if path in seen_paths:
            continue
        seen_paths.add(path)
        products.append(product)

    if products:
        return products

    for anchor in soup.select('a[href*="/p/"]'):
        href = anchor.get("href", "")
        if not href:
            continue
        path = href.split("?")[0]
        if path in seen_paths:
            continue
        seen_paths.add(path)
        product_name = pick_best_product_name(
            clean_text(anchor.get_text()),
            clean_product_name(str(anchor.get("title", "") or anchor.get("aria-label", "") or "")),
        )
        if not product_name:
            continue
        products.append(
            {
                "product_name": product_name,
                "product_url": to_full_url(path),
                "product_image": "",
                "price": "",
                "original_price": "",
                "discount_percent": "",
                "rating": "",
                "review_count": "",
                "brand": "",
                "color": "",
                "availability": "",
                "fit_type": "",
                "fabric": "",
                "sleeve_type": "",
                "pattern": "",
                "description": "",
            }
        )

    return products


def is_blocked_page(html: str) -> bool:
    lowered = html.lower()
    return (
        "are you a human" in lowered
        or "unusual traffic from your computer network" in lowered
        or "robot check" in lowered
        or "please verify you are a human" in lowered
    )


def get_next_page_url(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for anchor in soup.select('a[href*="page="]'):
        if clean_text(anchor.get_text()).lower() == "next":
            href = anchor.get("href")
            return to_full_url(href) if href else ""
    return ""


def extract_highlights(soup: BeautifulSoup) -> list[str]:
    highlights: list[str] = []
    for tag in soup.find_all(string=re.compile(r"key highlights", re.IGNORECASE)):
        container = tag.find_parent("div")
        if not container:
            continue
        for item in container.select("li"):
            text = clean_text(item.get_text())
            if text and text.lower() != "key highlights":
                highlights.append(text)
    return highlights


def extract_react_specs(html: str) -> dict[str, str]:
    """Parse Flipkart's React-rendered spec labels embedded in HTML."""
    specs: dict[str, str] = {}
    labels = [
        "Fabric",
        "Sleeve Type",
        "Fit Type",
        "Pattern",
        "Brand",
        "Color",
        "Ideal For",
        "Neck Type",
        "Occasion",
    ]
    for label in labels:
        pattern = rf">{re.escape(label)}</[^>]+>(?:[^<]{{0,160}}<[^>]+>)?([^<]{{2,80}})<"
        match = re.search(pattern, html)
        if match:
            specs[label.lower()] = clean_text(match.group(1))
    return specs


def extract_sizes_from_html(html: str) -> list[str]:
    sizes: list[str] = []
    for match in re.findall(r">(XXS|XS|S|M|L|XL|XXL|2XL|3XL|4XL|5XL)</", html, flags=re.IGNORECASE):
        sizes.append(match.upper())
    return sizes


def extract_seller_from_html(html: str) -> str:
    patterns = [
        r"Fulfilled by\s+([^<]{2,80})<",
        r"Fulfilled by\s+([A-Za-z0-9][A-Za-z0-9 &.,'()-]{1,78})",
        r">Seller</[^>]+>(?:[^<]{0,160}<[^>]+>)?([^<]{2,80})<",
        r">Sold by</[^>]+>(?:[^<]{0,160}<[^>]+>)?([^<]{2,80})<",
        r'"sellerName"\s*:\s*"([^"]+)"',
        r'"SellerName"\s*:\s*"([^"]+)"',
        r'"sellerDisplayName"\s*:\s*"([^"]+)"',
        r'"listingSellerName"\s*:\s*"([^"]+)"',
    ]
    skip_names = {"become a seller", "seller", "flipkart", "flipkart.com"}
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.IGNORECASE)
        if match:
            seller = clean_text(match.group(1))
            if seller and seller.lower() not in skip_names:
                return seller
    return ""


def extract_specs_map(soup: BeautifulSoup, html: str = "") -> dict[str, str]:
    specs: dict[str, str] = {}
    for row in soup.select("tr"):
        cells = [clean_text(cell.get_text()) for cell in row.select("td, th")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2 and len(cells[0]) <= 40:
            specs[cells[0].lower()] = cells[1]

    for row in soup.select("div[class*='col'], div._1UoMrZ, div._3RrcB_, table[class*='spec'] tr"):
        children = [clean_text(child.get_text()) for child in row.find_all(["div", "td", "th"], recursive=False)]
        children = [child for child in children if child]
        if len(children) >= 2 and len(children[0]) <= 40:
            specs[children[0].lower()] = children[1]

    for item in soup.select("li"):
        text = clean_text(item.get_text())
        if ":" not in text or len(text) > 120:
            continue
        key, value = text.split(":", 1)
        specs[clean_text(key).lower()] = clean_text(value)

    if html:
        specs.update(extract_react_specs(html))

    return specs


def extract_size_options(soup: BeautifulSoup, html: str = "") -> str:
    size_values: list[str] = []

    if html:
        size_values.extend(extract_sizes_from_html(html))

    for label in soup.find_all(string=re.compile(r"^size$", re.IGNORECASE)):
        container = label.find_parent(["div", "section", "td"])
        if not container:
            continue
        parent = container.find_parent("div") or container
        for node in parent.select("a, button, li, span, div"):
            text = clean_text(node.get_text())
            if text and len(text) <= 12:
                size_values.extend(parse_sizes_from_text(text))

    for node in soup.select("[class*='size'] a, [class*='size'] li, [class*='Size'] a, [class*='Size'] li"):
        text = clean_text(node.get_text())
        if text and len(text) <= 12:
            size_values.extend(parse_sizes_from_text(text))

    return unique_join(size_values)


def extract_seller(soup: BeautifulSoup, html: str = "") -> str:
    if html:
        seller = extract_seller_from_html(html)
        if seller:
            return seller

    seller = first_text(
        soup,
        [
            "#sellerName",
            "a#sellerName",
            "div#sellerName",
            "a[href*='seller.fkrt']",
        ],
    )
    if seller and seller.lower() not in {"become a seller", "seller"}:
        return clean_text(seller.replace("Seller:", "").replace("Seller", ""))

    for node in soup.find_all(["div", "span", "a"]):
        text = clean_text(node.get_text())
        low = text.lower()
        if low.startswith("fulfilled by") and len(text) < 100:
            seller = clean_text(re.sub(r"^fulfilled by[:\s]*", "", text, flags=re.IGNORECASE))
            if seller and seller.lower() not in {"flipkart", "seller"}:
                return seller
        if low.startswith("seller") and 3 < len(text) < 100:
            seller = clean_text(re.sub(r"^seller[:\s]*", "", text, flags=re.IGNORECASE))
            if seller and seller.lower() not in {"become a seller", "seller"}:
                return seller
    return ""


def has_meaningful_product_details(details: dict[str, str]) -> bool:
    important_fields = [
        "price", "rating", "review_count", "size_options",
        "color", "fabric", "description", "seller",
    ]
    return sum(1 for field in important_fields if details.get(field)) >= 3


def extract_breadcrumbs(soup: BeautifulSoup) -> tuple[str, str]:
    crumbs: list[str] = []
    for selector in ("div._1MR4o5 a", "a._2whKao", "nav a[href*='/c/']", "div[class*='breadcrumb'] a"):
        for node in soup.select(selector):
            text = clean_text(node.get_text())
            if text and text.lower() not in {"home", "flipkart"}:
                crumbs.append(text)
        if crumbs:
            break
    if not crumbs:
        return "Women Fashion", "Shirts"
    return crumbs[0], crumbs[-1]


def extract_product_description(soup: BeautifulSoup) -> str:
    sections: list[str] = []

    for block in parse_ld_json_blocks(soup):
        desc = block.get("description")
        if isinstance(desc, str) and clean_text(desc):
            sections.append(clean_text(desc))

    highlights = extract_highlights(soup)
    if highlights:
        sections.append("Highlights: " + ". ".join(highlights))

    seen: set[str] = set()
    unique_sections: list[str] = []
    for section in sections:
        key = section.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        unique_sections.append(section)
    return " ".join(unique_sections)


def parse_product_page(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    details: dict[str, str] = {
        "product_name": "",
        "product_image": "",
        "brand": "",
        "category": "Women Fashion",
        "subcategory": "Shirts",
        "price": "",
        "original_price": "",
        "discount_percent": "",
        "rating": "",
        "review_count": "",
        "size_options": "",
        "color": "",
        "fit_type": "",
        "fabric": "",
        "sleeve_type": "",
        "pattern": "",
        "description": "",
        "availability": "",
        "seller": "",
    }

    for block in parse_ld_json_blocks(soup):
        name = block.get("name")
        if isinstance(name, str) and name:
            details["product_name"] = clean_text(name)

        description = block.get("description")
        if isinstance(description, str) and description:
            details["description"] = clean_text(description)

        brand = block.get("brand")
        if isinstance(brand, dict) and brand.get("name"):
            details["brand"] = clean_text(str(brand["name"]))

        color = block.get("color")
        if color:
            details["color"] = clean_text(str(color))

        aggregate = block.get("aggregateRating", {})
        if isinstance(aggregate, dict):
            details["rating"] = extract_number(str(aggregate.get("ratingValue", "")))
            review_count = aggregate.get("ratingCount") or aggregate.get("reviewCount") or ""
            details["review_count"] = extract_number(str(review_count))

        offers = block.get("offers", {})
        offer_list = offers if isinstance(offers, list) else [offers]
        for offer in offer_list:
            if not isinstance(offer, dict):
                continue
            if not details["price"]:
                details["price"] = extract_number(str(offer.get("price", "")))
            if not details["availability"]:
                availability = str(offer.get("availability", ""))
                if availability:
                    details["availability"] = clean_text(
                        availability.replace("https://schema.org/", "").replace("http://schema.org/", "")
                    )

        images = block.get("image", [])
        if isinstance(images, list) and images:
            details["product_image"] = clean_text(str(images[0]))
        elif isinstance(images, str):
            details["product_image"] = clean_text(images)

    highlights = extract_highlights(soup)
    if highlights:
        highlight_text = "Highlights: " + ". ".join(highlights)
        details["description"] = f"{details['description']} {highlight_text}".strip()

    specs = extract_specs_map(soup, html)
    for key, value in specs.items():
        if "brand" in key and not details["brand"]:
            details["brand"] = value
        elif "fit" in key and not details["fit_type"]:
            details["fit_type"] = value
        elif ("fabric" in key or "material" in key) and not details["fabric"]:
            details["fabric"] = value
        elif "sleeve" in key and not details["sleeve_type"]:
            details["sleeve_type"] = value
        elif "pattern" in key and not details["pattern"]:
            details["pattern"] = value
        elif ("color" in key or "colour" in key) and not details["color"]:
            details["color"] = value
        elif "size" in key and not details["size_options"]:
            details["size_options"] = value

    category, subcategory = extract_breadcrumbs(soup)
    details["category"] = category
    details["subcategory"] = subcategory

    page_title = first_text(soup, ["span.B_NuCI", "h1 span", "h1", "span[class*='title']"])
    if page_title:
        details["product_name"] = page_title

    page_price = first_text(soup, ["div._30jeq3", "div[class*='_30jeq3']", "div[class*='price']"])
    page_original = first_text(
        soup,
        ["div._3I9_wc", "div[class*='_3I9_wc']", "del span", "span[class*='strike']"],
    )
    page_discount = first_text(soup, ["div._3Ay6Sb", "div[class*='_3Ay6Sb']", "div[class*='discount']"])
    page_rating = first_text(
        soup,
        ["div._3LWZlK", "div.XQDdHH", "div[class*='rating']", "span[class*='rating']"],
    )
    page_reviews = first_text(
        soup,
        ["span._2_R_DZ span", "span.Wphh3L", "span[class*='review']", "div[class*='review'] span"],
    )

    details["price"] = details["price"] or extract_number(page_price)
    details["original_price"] = extract_number(page_original)
    details["discount_percent"] = extract_number(page_discount)
    details["rating"] = details["rating"] or extract_rating_from_text(page_rating)
    details["review_count"] = details["review_count"] or extract_review_count_from_text(page_reviews)

    if not details["original_price"] and details["price"] and details["discount_percent"]:
        try:
            p_val = float(details["price"])
            d_val = float(details["discount_percent"])
            if 0 < d_val < 100:
                details["original_price"] = f"{p_val / (1 - d_val / 100):.2f}"
        except ValueError:
            pass

    if not details["discount_percent"] and details["price"] and details["original_price"]:
        try:
            p_val = float(details["price"])
            op_val = float(details["original_price"])
            if op_val > p_val > 0:
                details["discount_percent"] = f"{((op_val - p_val) / op_val) * 100:.2f}"
        except ValueError:
            pass

    parsed_sizes = extract_size_options(soup, html)
    if parsed_sizes:
        details["size_options"] = parsed_sizes

    availability_text = first_text(
        soup,
        [
            "div._16FRp0",
            "div[class*='stock']",
            "div[class*='availability']",
            "span[class*='delivery']",
        ],
    )
    if availability_text:
        details["availability"] = availability_text
    elif details["availability"]:
        details["availability"] = clean_text(
            details["availability"].replace("InStock", "In Stock").replace("OutOfStock", "Out of Stock")
        )

    seller = extract_seller(soup, html)
    if seller:
        details["seller"] = seller

    brand_line = first_text(soup, ["a[href*='brand=']", "span[class*='brand']"])
    if brand_line and not details["brand"]:
        details["brand"] = brand_line

    image_url = first_attr(soup, ["img[class*='_396cs4']", "img._396cs4", "img[src*='flixcart']"], "src")
    if image_url and not details["product_image"]:
        details["product_image"] = image_url

    keyword_text = " ".join(
        [
            details.get("product_name", ""),
            details.get("description", ""),
            " ".join(highlights),
        ]
    )
    inferred = infer_keywords(keyword_text)
    for key in ["fit_type", "fabric", "sleeve_type", "pattern"]:
        if not details.get(key):
            details[key] = inferred.get(key, "")

    if not details["description"]:
        details["description"] = extract_product_description(soup)

    meta_description = first_attr(soup, ["meta[name='description']"], "content")
    og_title = first_attr(soup, ["meta[property='og:title']", "meta[name='og:title']"], "content")
    og_name = clean_product_name(og_title.split("|")[0] if og_title else "")

    details["product_name"] = pick_best_product_name(
        details.get("product_name", ""),
        page_title,
        og_name,
        extract_product_name_from_description(details.get("description", "")),
        extract_product_name_from_description(meta_description or ""),
    )

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

    page_title = first_text(soup, ["span.B_NuCI", "h1 span", "h1", "span[class*='title']"])
    if page_title:
        candidates.append(page_title)

    og_title = first_attr(soup, ["meta[property='og:title']", "meta[name='og:title']"], "content")
    if og_title:
        candidates.append(clean_product_name(og_title.split("|")[0]))

    meta_description = first_attr(soup, ["meta[name='description']"], "content")
    description = clean_text(meta_description)
    if description:
        candidates.append(extract_product_name_from_description(description))

    product_name = pick_best_product_name(*candidates)
    return {
        "product_name": product_name,
        "description": description,
    }


def dismiss_login_popup(page: Page) -> None:
    selectors = [
        "button:has-text('✕')",
        "span:has-text('✕')",
        "button._2KpZ6l._2doB4z",
    ]
    for selector in selectors:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=500):
                button.click(timeout=1500)
                page.wait_for_timeout(200)
                return
        except Exception:
            continue


def wait_for_product_page(page: Page) -> None:
    """Wait for Flipkart product page markers (short timeouts to avoid hangs)."""
    selectors = [
        "script[type='application/ld+json']",
        "img[src*='flixcart']",
        "div[class*='_30jeq3']",
        "h1 span",
    ]
    for selector in selectors:
        try:
            page.wait_for_selector(selector, timeout=4000, state="attached")
            return
        except Exception:
            continue
    page.wait_for_timeout(500)


def fetch_product_name_with_playwright(page: Page, product_url: str) -> dict[str, str]:
    for attempt in range(2):
        try:
            page.goto(
                product_url,
                wait_until="commit",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            dismiss_login_popup(page)
            wait_for_product_page(page)
            page.wait_for_timeout(500 + (attempt * 200))
            html = page.content()
            if is_blocked_page(html):
                time.sleep(1 + attempt)
                continue
            return parse_product_name_from_html(html)
        except PlaywrightTimeoutError:
            time.sleep(1)
        except Exception:
            time.sleep(1)
    return {}


def fetch_product_details_with_playwright(page: Page, product_url: str) -> dict[str, str]:
    last_details: dict[str, str] = {}
    for attempt in range(2):
        try:
            page.goto(
                product_url,
                wait_until="commit",
                timeout=NAVIGATION_TIMEOUT_MS,
            )
            dismiss_login_popup(page)
            wait_for_product_page(page)
            page.wait_for_timeout(600 + (attempt * 300))
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(250)
            except Exception:
                pass
            html = page.content()
            if is_blocked_page(html):
                print(f"[WARN] Blocked on product page (attempt {attempt + 1})", flush=True)
                time.sleep(1 + attempt)
                continue
            details = parse_product_page(html)
            last_details = details
            if has_meaningful_product_details(details):
                return details
            if details.get("price") or details.get("product_name"):
                return details
        except PlaywrightTimeoutError:
            print(f"[WARN] Timeout fetching product (attempt {attempt + 1}): {product_url[:80]}", flush=True)
            time.sleep(1)
        except Exception as exc:
            print(f"[WARN] Error fetching product (attempt {attempt + 1}): {exc}", flush=True)
            time.sleep(1)
    return last_details


def fetch_product_description_with_playwright(page: Page, product_url: str) -> dict[str, str]:
    details = fetch_product_details_with_playwright(page, product_url)
    if details:
        return details
    return {"description": ""}


def wait_for_search_results(page: Page, page_count: int) -> bool:
    """Wait for product cards; return False if the page never loads (block/end of crawl)."""
    try:
        page.wait_for_selector('a[href*="/p/"]', timeout=20000, state="attached")
        return True
    except Exception:
        page.wait_for_timeout(2000)
        try:
            page.reload(wait_until="domcontentloaded", timeout=60000)
            dismiss_login_popup(page)
            page.wait_for_selector('a[href*="/p/"]', timeout=20000, state="attached")
            return True
        except Exception:
            print(
                f"[WARN] No product results on page {page_count} "
                "(timeout or block). Stopping pagination."
            )
            return False


def scrape_flipkart_women_shirts(
    keyword: str = DEFAULT_KEYWORD,
    max_pages: int | None = None,
    max_products: int | None = None,
    search_only: bool = True,
    fetch_descriptions: bool = False,
    fetch_full_names: bool = False,
    detail_from: int = 1,
    detail_to: int | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    scrape_time = datetime.now(timezone.utc).isoformat()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
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
        page.set_extra_http_headers({"accept-language": "en-IN,en-US;q=0.9,en;q=0.8"})

        products: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        visited_pages: set[str] = set()
        search_url = build_search_url(keyword)
        page_count = 0

        while search_url and search_url not in visited_pages:
            visited_pages.add(search_url)
            page_count += 1
            if max_pages is not None and page_count > max_pages:
                break

            page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
            dismiss_login_popup(page)
            if not wait_for_search_results(page, page_count):
                html = page.content()
                if is_blocked_page(html):
                    print(f"[WARN] Flipkart blocked request on page {page_count}. Stopping early.")
                break
            page.wait_for_timeout(4000)
            html = page.content()

            if is_blocked_page(html):
                print(f"[WARN] Flipkart blocked request on page {page_count}. Stopping early.")
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
            detail_page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
            detail_page.set_default_timeout(ACTION_TIMEOUT_MS)
            detail_page.set_extra_http_headers({"accept-language": "en-IN,en-US;q=0.9,en;q=0.8"})
            consecutive_failures = 0
            for index, product in enumerate(products, start=1):
                url = product.get("product_url", "")
                if not url:
                    continue
                if index < detail_from:
                    continue
                if detail_to is not None and index > detail_to:
                    continue
                if search_only and fetch_full_names and not fetch_descriptions:
                    print(f"[INFO] Fetching full name {index}/{len(products)}", flush=True)
                    product_details_by_url[url] = fetch_product_name_with_playwright(detail_page, url)
                    time.sleep(0.4)
                elif search_only:
                    print(f"[INFO] Fetching description {index}/{len(products)}", flush=True)
                    product_details_by_url[url] = fetch_product_description_with_playwright(detail_page, url)
                    time.sleep(0.4)
                else:
                    print(f"[INFO] Fetching details {index}/{len(products)}", flush=True)
                    details = fetch_product_details_with_playwright(detail_page, url)
                    product_details_by_url[url] = details
                    if not details:
                        consecutive_failures += 1
                    else:
                        consecutive_failures = 0
                    if consecutive_failures >= 2:
                        print("[WARN] Resetting browser tab after repeated timeouts", flush=True)
                        try:
                            detail_page.close()
                        except Exception:
                            pass
                        detail_page = context.new_page()
                        detail_page.set_default_navigation_timeout(NAVIGATION_TIMEOUT_MS)
                        detail_page.set_default_timeout(ACTION_TIMEOUT_MS)
                        detail_page.set_extra_http_headers(
                            {"accept-language": "en-IN,en-US;q=0.9,en;q=0.8"}
                        )
                        consecutive_failures = 0
                    time.sleep(DETAIL_SLEEP_S)
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
            rows.append(
                build_product_row(
                    product,
                    product_details_by_url.get(product_url, {}),
                    scrape_time,
                )
            )
            if max_products is not None and len(rows) >= max_products:
                break

        browser.close()

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


#   --output FILE   CSV output path (default: flipkart_women_shirts_raw.csv)
#   --full-names    visit product pages for complete titles (faster than --full)
#   --detail-from N  start detail fetching at product N (1-based)
#   --detail-to N    stop detail fetching at product N (inclusive)
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
    detail_label = f"{detail_from}" if detail_to is None else f"{detail_from}-{detail_to}"
    print(
        f"[INFO] Scraping Flipkart women's shirts: '{keyword}' | "
        f"mode={mode_label} | max_products={products_label} | max_pages={pages_label} | "
        f"detail_range={detail_label}"
    )
    data = scrape_flipkart_women_shirts(
        keyword=keyword,
        max_pages=max_pages,
        max_products=max_products,
        search_only=search_only,
        fetch_descriptions=fetch_descriptions,
        fetch_full_names=fetch_full_names,
        detail_from=detail_from,
        detail_to=detail_to,
    )
    path = save_to_csv(data, output_file)
    print(f"[INFO] Scraped {len(data)} products -> saved to {path}")
