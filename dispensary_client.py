from __future__ import annotations

import time
from dataclasses import dataclass
from typing import List

from curl_cffi import requests

STORE_ID = 5713
_BASE_MENU_URL = (
    "https://shop.gardensdispensary.com"
    "/locations/cannabis-dispensary-garfield-nj/rec-menu/5713/menu"
)

_ALGOLIA_URL = (
    "https://search.iheartjane.com"
    "/1/indexes/menu-products-production/query"
)
_HEADERS = {
    "X-Algolia-Application-Id": "VFM4X0N23A",
    "X-Algolia-API-Key": "edc5435c65d771cecbd98bbd488aa8d3",
    "Content-Type": "application/json",
    "Referer": "https://shop.gardensdispensary.com/",
    "Origin": "https://shop.gardensdispensary.com",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}
_ATTRS = [
    "name", "brand", "kind", "kind_subtype", "category",
    "product_id", "url_slug",
]
_PER_PAGE = 100  # page through in batches of 100


@dataclass
class DispensaryProduct:
    product_id: int
    name: str
    brand: str
    kind: str        # flower, pre-roll, concentrate, vaporizers, edible, tincture, topical
    kind_subtype: str
    category: str    # hybrid, sativa, indica, or ""
    url_slug: str

    @property
    def url(self) -> str:
        return f"{_BASE_MENU_URL}/products/{self.product_id}/{self.url_slug}"


def fetch_dispensary_products() -> List[DispensaryProduct]:
    """Fetch all available menu products for Gardens Dispensary (store 5713), page by page."""
    products: List[DispensaryProduct] = []
    page = 0

    while True:
        payload = {
            "filters": f"store_id:{STORE_ID}",
            "hitsPerPage": _PER_PAGE,
            "page": page,
            "attributesToRetrieve": _ATTRS,
        }
        try:
            resp = requests.post(
                _ALGOLIA_URL, json=payload, headers=_HEADERS,
                impersonate="chrome124", timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  WARNING: Failed to fetch dispensary products (page {page}): {e}")
            break

        hits = data.get("hits", [])
        for hit in hits:
            products.append(DispensaryProduct(
                product_id=hit.get("product_id", 0),
                name=hit.get("name", ""),
                brand=hit.get("brand", ""),
                kind=hit.get("kind", ""),
                kind_subtype=hit.get("kind_subtype", ""),
                category=hit.get("category") or "",
                url_slug=hit.get("url_slug", ""),
            ))

        nb_pages = data.get("nbPages", 1)
        print(f"  Page {page + 1}/{nb_pages}: {len(hits)} products")
        page += 1
        if page >= nb_pages:
            break
        time.sleep(0.3)

    return products
