#!/usr/bin/env python3
"""
Extract brand-keyed filter part numbers from an AMSOIL lookup page.

ONE implementation, shared by the batch runner and the nightly cron, so both
write filters identically. It accepts either shape of the same page:

  raw HTML      <a href="/p/wix-oil-filter-wixoil/?code=57356-EA">WIX Oil Filter</a>
  web_extract   [WIX Oil Filter](https://www.amsoil.com/p/wix-oil-filter-wixoil/?code=57356-EA)

Both carry the part number in `code=<PART>-EA`; only the label's position
differs. The cron uses web_extract (which drops the spec TABLE but keeps the
product LINKS), so it can capture filters from the fetch it already makes —
no second request, which is the whole point.

WHY BRAND-KEYED: a shop wants the filter it can actually buy today (Valvoline
house brand, NAPA for a mobile mechanic). Storing one winner would destroy the
only information that matters.
"""
import json
import re

# order matters: "Cabin Air Filter" must not land in "air"
KIND_ORDER = [
    ("cabin", "cabin"),
    ("oil vapor", "oil_vapor"),
    ("transmission", "transmission"),
    ("air", "air"),
    ("oil", "oil"),
]

PART_RE = re.compile(r"code=([A-Za-z0-9._-]+?)-EA")

# markdown link:  [LABEL](...code=PART-EA)
MD_LINK = re.compile(r"\[([^\]]{1,80})\]\([^)]*?code=([A-Za-z0-9._-]+?)-EA", re.I)
# html link:      <a ... code=PART-EA ...>LABEL</a>
HTML_LINK = re.compile(r"<a[^>]*?code=([A-Za-z0-9._-]+?)-EA[^>]*>(.*?)</a>", re.S | re.I)


def _clean_label(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = re.sub(r"&#\d+;|&\w+;", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _classify(label):
    low = label.lower()
    if "filter" not in low:
        return None
    for needle, kind in KIND_ORDER:
        if needle in low:
            return kind
    return None


def _brand(label):
    parts = label.split()
    if not parts:
        return "OEM"
    b = parts[0].upper()
    if len(b) > 14 or b.lower() in ("the", "oil"):
        return "OEM"
    return b


def extract_filters(text):
    """Return (filters_dict, flat_oil_filter_oem or None)."""
    filters = {}
    pairs = []
    for m in MD_LINK.finditer(text or ""):
        pairs.append((m.group(2), m.group(1)))          # (part, label)
    for m in HTML_LINK.finditer(text or ""):
        pairs.append((m.group(1), _clean_label(m.group(2))))

    for part, label in pairs:
        label = _clean_label(label)
        kind = _classify(label)
        if not kind:
            continue
        brand = _brand(label)
        filters.setdefault(kind, {})
        filters[kind].setdefault(brand, part.strip())

    flat = None
    if filters.get("oil"):
        first = sorted(filters["oil"].items())[0]
        flat = f"{first[0]} {first[1]}"
    return filters, flat


if __name__ == "__main__":
    import sys
    txt = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    f, flat = extract_filters(txt)
    print(json.dumps({"filters_json": json.dumps(f, sort_keys=True) if f else None,
                      "oil_filter_oem": flat}, indent=2))
