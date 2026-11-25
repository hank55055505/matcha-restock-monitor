
"""Marukyu Koyamaen per-variant stock scraper."""

from __future__ import annotations

import json
import logging
import re
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .common import Item, StoreError, polite_get

log = logging.getLogger(__name__)

STORE = "Marukyu Koyamaen"
BASE = "https://www.marukyu-koyamaen.co.jp"

DEFAULT_CATALOGS = [
    f"{BASE}/english/shop/products/catalog/matcha?viewall=1",
]

PRODUCT_PATH = re.compile(
    r"^/english/shop/products/(?!catalog/)([0-9a-z]{6,14})/?$",
    re.I,
)

# The 18 confirmed variants across the four requested products.
WATCHED_SKUS = {
    "1171020C1", "1171040C1", "1171100C1",
    "1171100C6", "1171200C1",

    "1161020C1", "1161040C1", "1161100C1",
    "1161100C6", "1161200C1",

    "1181040C1", "1181100C1", "1181100C6",
    "1181200C1",

    "1191040C1", "1191100C1", "1F43100C6",
    "1191200C1",
}


def discover_products(
    session,
    catalogs: Iterable[str],
    delay: float,
) -> list[tuple[str, str]]:
    found: dict[str, str] = {}

    for catalog_url in catalogs:
        resp = polite_get(session, catalog_url, delay=delay)
        soup = BeautifulSoup(resp.text, "html.parser")

        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(BASE, anchor["href"])
            path = absolute.replace(BASE, "").split("?")[0]

            if not PRODUCT_PATH.match(path):
                continue

            name = (
                anchor.get("title")
                or anchor.get_text(" ", strip=True)
                or ""
            ).strip()

            if absolute not in found or (
                name and len(name) < len(found[absolute])
            ):
                found[absolute] = name

    if not found:
        raise StoreError(
            "No product links found in the Marukyu catalog."
        )

    log.info("Marukyu: discovered %d products", len(found))
    return sorted(found.items())


def _variants_from_form_json(
    soup: BeautifulSoup,
) -> Optional[list[dict]]:
    form = soup.find(attrs={"data-product_variations": True})

    if not form:
        return None

    raw = form.get("data-product_variations")

    if not raw or raw in ("false", "[]"):
        return None

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None

    return data if isinstance(data, list) and data else None


def _variants_from_dom(soup: BeautifulSoup) -> Optional[list[dict]]:
    results: list[dict] = []

    for node in soup.find_all(
        class_=re.compile(
            r"(variation|product-sku|item-sku|spec)",
            re.I,
        )
    ):
        text = node.get_text(" ", strip=True)

        sku_match = re.search(
            r"\b([0-9A-Z]{9,12})\b",
            text,
            re.I,
        )

        if not sku_match:
            continue

        stock_node = node.find(
            class_=re.compile(
                r"(out-of-stock|in-stock|stock)",
                re.I,
            )
        )

        if stock_node is None:
            continue

        classes = " ".join(stock_node.get("class", []))
        stock_text = stock_node.get_text(" ", strip=True).lower()

        if "out-of-stock" in classes.lower():
            available = False
        elif "in-stock" in classes.lower():
            available = True
        elif "out of stock" in stock_text:
            available = False
        elif "in stock" in stock_text:
            available = True
        else:
            continue

        size_match = re.search(r"(\d+\s*g[^,\n]*)", text, re.I)

        results.append(
            {
                "sku": sku_match.group(1).upper(),
                "is_in_stock": available,
                "variant": (
                    size_match.group(1).strip()
                    if size_match
                    else None
                ),
            }
        )

    return results or None


def _price_for(soup: BeautifulSoup) -> Optional[str]:
    node = soup.find(class_=re.compile(r"price", re.I))

    if not node:
        return None

    text = node.get_text(" ", strip=True)
    match = re.search(r"[¥￥]\s?[\d,]+", text)

    return match.group(0) if match else (text[:40] or None)


def scrape_product(
    session,
    url: str,
    fallback_name: str,
    delay: float,
) -> list[Item]:

    resp = polite_get(session, url, delay=delay)
    soup = BeautifulSoup(resp.text, "html.parser")

    heading = soup.find("h1")
    name = (
        fallback_name
        or (heading.get_text(strip=True) if heading else url)
    )
    price = _price_for(soup)

    variations = _variants_from_form_json(soup)

    if variations:
        results = []

        for var in variations:
            sku = str(var.get("sku") or "").upper()

            if sku not in WATCHED_SKUS:
                continue

            attrs = var.get("attributes") or {}
            variant = (
                next((str(v) for v in attrs.values() if v), None)
                or sku
            )

            results.append(
                Item(
                    key=f"marukyu:{sku}",
                    store=STORE,
                    name=name,
                    variant=variant,
                    url=url,
                    price=(
                        f"¥{var['display_price']:,}"
                        if var.get("display_price") is not None
                        else price
                    ),
                    available=bool(var.get("is_in_stock")),
                    detection="variations-json",
                )
            )

        return results

    dom_variants = _variants_from_dom(soup)

    if dom_variants:
        return [
            Item(
                key=f"marukyu:{var['sku']}",
                store=STORE,
                name=name,
                variant=var.get("variant") or var["sku"],
                url=url,
                price=price,
                available=bool(var["is_in_stock"]),
                detection="dom-variant",
            )
            for var in dom_variants
            if var["sku"] in WATCHED_SKUS
        ]

    raise StoreError(
        f"No reliable per-variant stock data found for {url}"
    )


def fetch(session, config: dict) -> list[Item]:
    """Read all watched Marukyu variants or fail the entire cycle."""

    delay = float(config.get("request_delay_seconds", 1.5))
    catalogs = config.get("catalog_urls") or DEFAULT_CATALOGS

    products = discover_products(session, catalogs, delay)

    # These product URL slugs correspond to the four requested products.
    target_slugs = {
        "1171020c1",
        "1161020c1",
        "1181040c1",
        "1191040c1",
    }

    selected = {
        url.rstrip("/").rsplit("/", 1)[-1].lower(): (url, name)
        for url, name in products
        if url.rstrip("/").rsplit("/", 1)[-1].lower()
        in target_slugs
    }

    missing_products = target_slugs - set(selected)

    if missing_products:
        raise StoreError(
            "Catalog is missing target products: "
            + ", ".join(sorted(missing_products))
        )

    items: list[Item] = []

    for slug in sorted(target_slugs):
        url, name = selected[slug]

        try:
            items.extend(
                scrape_product(session, url, name, delay)
            )
        except StoreError as exc:
            raise StoreError(
                f"Failed to read product {url}: {exc}"
            ) from exc

    found_skus = {item.key.split(":", 1)[1] for item in items}
    missing_skus = WATCHED_SKUS - found_skus

    if missing_skus:
        raise StoreError(
            "Some watched variants were not found: "
            + ", ".join(sorted(missing_skus))
        )

    if len(items) != len(WATCHED_SKUS):
        raise StoreError(
            f"Expected {len(WATCHED_SKUS)} variants, "
            f"but received {len(items)}."
        )

    log.info(
        "Marukyu: successfully read all %d watched variants",
        len(items),
    )

    return items
