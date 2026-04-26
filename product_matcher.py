from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from rapidfuzz import fuzz

from analyzer import ProductMention
from dispensary_client import DispensaryProduct

# Maps freeform type strings (from Reddit/Claude) to Jane's canonical kind values
_KIND_CANONICAL = {
    "flower": "flower",
    "bud": "flower",
    "nug": "flower",
    "herb": "flower",
    "eighth": "flower",
    "pre-roll": "pre-roll",
    "preroll": "pre-roll",
    "pre roll": "pre-roll",
    "joint": "pre-roll",
    "blunt": "pre-roll",
    "cone": "pre-roll",
    "infused pre-roll": "pre-roll",
    "concentrate": "concentrate",
    "wax": "concentrate",
    "shatter": "concentrate",
    "rosin": "concentrate",
    "live rosin": "concentrate",
    "live resin": "concentrate",
    "resin": "concentrate",
    "hash": "concentrate",
    "dab": "concentrate",
    "extract": "concentrate",
    "distillate": "concentrate",
    "badder": "concentrate",
    "budder": "concentrate",
    "sauce": "concentrate",
    "diamonds": "concentrate",
    "vaporizers": "vaporizers",
    "vaporizer": "vaporizers",
    "vape": "vaporizers",
    "cart": "vaporizers",
    "cartridge": "vaporizers",
    "pod": "vaporizers",
    "pen": "vaporizers",
    "oil": "vaporizers",
    "edible": "edible",
    "edibles": "edible",
    "gummy": "edible",
    "gummies": "edible",
    "chocolate": "edible",
    "candy": "edible",
    "cookie": "edible",
    "brownie": "edible",
    "beverage": "edible",
    "drink": "edible",
    "tincture": "tincture",
    "drops": "tincture",
    "topical": "topical",
    "cream": "topical",
    "lotion": "topical",
    "balm": "topical",
    "salve": "topical",
    "patch": "topical",
}

_SIZE_RE = re.compile(r"\s*[\[\(][\d.]+\s*g[\]\)]|\s*[\[\(]\d+mg[\]\)]", re.IGNORECASE)


def _normalize_kind(kind_str: str) -> str:
    s = kind_str.lower().strip()
    if s in _KIND_CANONICAL:
        return _KIND_CANONICAL[s]
    for key, canonical in _KIND_CANONICAL.items():
        if key in s:
            return canonical
    return s


def _kinds_compatible(a: str, b: str) -> float:
    """1.0 if same, 0.7 if either is unknown, 0.0 if different."""
    na, nb = _normalize_kind(a), _normalize_kind(b)
    if not na or not nb:
        return 0.7
    return 1.0 if na == nb else 0.0


def _strip_size(name: str) -> str:
    """Remove weight qualifiers like [3.5g] or (28g) from product names."""
    return _SIZE_RE.sub("", name).strip()


@dataclass
class MatchResult:
    mention: ProductMention
    dispensary_product: Optional[DispensaryProduct]
    name_score: float
    brand_score: float
    composite_score: float  # 0–100; 0 if no match found


_MIN_COMPOSITE = 50.0


def match_products(
    mentions: List[ProductMention],
    dispensary_products: List[DispensaryProduct],
) -> List[MatchResult]:
    return [_best_match(m, dispensary_products) for m in mentions]


def _best_match(
    mention: ProductMention,
    dispensary_products: List[DispensaryProduct],
) -> MatchResult:
    m_name = _strip_size(mention.name).lower()
    m_brand = mention.brand.lower()

    best_composite = -1.0
    best_dp: Optional[DispensaryProduct] = None
    best_name_score = 0.0
    best_brand_score = 0.0

    for dp in dispensary_products:
        dp_name = _strip_size(dp.name).lower()
        dp_brand = dp.brand.lower()

        name_score = float(fuzz.token_sort_ratio(m_name, dp_name))
        brand_score = float(fuzz.token_sort_ratio(m_brand, dp_brand))
        kind_factor = _kinds_compatible(mention.kind, dp.kind)

        # Name 60 %, brand 30 %, kind bonus 10 %
        composite = (name_score * 0.60 + brand_score * 0.30) * (0.90 + kind_factor * 0.10)

        if composite > best_composite:
            best_composite = composite
            best_dp = dp
            best_name_score = name_score
            best_brand_score = brand_score

    if best_composite < _MIN_COMPOSITE:
        best_dp = None

    return MatchResult(
        mention=mention,
        dispensary_product=best_dp,
        name_score=best_name_score,
        brand_score=best_brand_score,
        composite_score=round(best_composite, 1) if best_dp else 0.0,
    )
