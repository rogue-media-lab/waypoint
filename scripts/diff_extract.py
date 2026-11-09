#!/usr/bin/env python3
"""
Extract differential and transfer-case specs from an AMSOIL lookup page.

WHAT THE PAGE ACTUALLY CARRIES — verified against a real saved page, not assumed
------------------------------------------------------------------------------
    ## Differential/Transfer Case
    ### Transfer Case Lubricant
    **For Transfer Case: U/K TRC....MLV**
    Capacity: U/K TRC 3.6 pints.
    Torque: 11 ft/lbs (Transfer Case Fill Plug)

    ### Differential Lubricant: Front
    **Standard Differential, GL-5 All TEMPS....80W-90**

    ### Differential Lubricant: Rear
    **Standard Differential, 9.75 RG Std....GL-5 All TEMPS....75W-140**

    ### Differential Lubricant: Rear
    **Limited Slip Differential, W/ 9.75 Trac-Lok....GL-5* All TEMPS....75W-140**

Shape of the bold spec line:  <variant>, <axle> .... <spec class> .... <WEIGHT>
so the WEIGHT is the LAST `....` segment and the variant is the FIRST. The axle
size frequently appears inside the variant text ('9.75 RG Std', 'W/ 9.75
Trac-Lok') but not always, so treat it as a bonus, never a guarantee.

**THE PAGE DOES NOT CARRY DIFFERENTIAL CAPACITIES.** `Capacity:` appears on the
page only for the engine oil and the transfer case. An earlier note in this
project claimed the lookup returned 'front and rear differential fluids and
capacities' — it does not. Weight yes, capacity no. Differential capacity comes
from the OEM axle chart instead (see differential_specs / Motorcraft Axle
Lubricant Quick Reference), and the two are combined in the same table.

MULTIPLE REAR ENTRIES ARE NORMAL AND ARE NOT A CONFLICT. The same vehicle is
listed once for Standard and once for Limited Slip — that is the axle ambiguity,
the same shape as several transmissions on one configuration. Store them ALL and
never collapse to one.

Accepts raw HTML and the rendered markdown web_extract returns, because the cron
fetches rendered text while other callers hold the raw body — the same reason
filter_extract accepts both.
"""
import json
import re

HEAD_RE = re.compile(r"^#{2,4}\s*(Differential Lubricant|Transfer Case Lubricant)\s*:?\s*"
                     r"(Front|Rear|Front and Rear|Rear \(Front\))?\s*$", re.I | re.M)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
CAP_RE = re.compile(r"Capacity:\s*\n?\s*([^\n]+)", re.I)
TORQUE_RE = re.compile(r"Torque:\s*\n?\s*([^\n]+)", re.I)
WEIGHT_RE = re.compile(r"\b(\d{2}W-\d{2,3})\b", re.I)
SIZE_RE = re.compile(r"\b(\d{2}\.\d{2}|\d\.\d{2})\s*(?:RG|in|inch)?\b", re.I)
LS_RE = re.compile(r"limited\s*slip|trac[- ]?lok|\bLS\b|posi", re.I)


def _segments(line):
    """Split a page spec line on its '....' separators, trimmed."""
    return [s.strip(" .") for s in re.split(r"\.{3,}", line) if s.strip(" .")]


def extract_differentials(text):
    """
    Returns (rows, transfer_case).
    Each rows entry: {position, variant, axle_size, limited_slip, weight, spec_class}
    """
    if not text:
        return [], None
    # markdown headings survive in both shapes; HTML callers should pre-strip tags
    plain = re.sub(r"<[^>]+>", "\n", str(text)) if "<" in str(text) else str(text)
    plain = plain.replace("\u00a0", " ")

    heads = list(HEAD_RE.finditer(plain))
    if not heads:
        # A silent [] is the worst possible answer here: a raw-HTML caller gets an
        # empty result that looks like "this vehicle has no differential spec", when
        # the truth is "this extractor was never fed input it can read". HEAD_RE
        # requires markdown headings (`## Differential Lubricant`), which raw bodies
        # do not contain. Always complain on stderr so the emptiness is visible.
        import sys as _sys
        _sys.stderr.write(
            "diff_extract: NO spec headings matched -> returning empty. "
            "HEAD_RE needs markdown headings ('## Differential Lubricant' / "
            "'## Transfer Case Lubricant'); a raw HTML body silently yields nothing. "
            "Pass rendered markdown, or pre-strip to headings, before trusting an empty result.\n")
    rows, tc = [], None

    for i, m in enumerate(heads):
        kind, pos = m.group(1), (m.group(2) or "")
        body = plain[m.end(): heads[i + 1].start() if i + 1 < len(heads) else m.end() + 1200]

        b = BOLD_RE.search(body)
        if not b:
            continue
        line = " ".join(b.group(1).split())
        segs = _segments(line)

        if kind.lower().startswith("transfer"):
            wm = WEIGHT_RE.search(line)
            tc = {
                "weight": (wm.group(1).upper() if wm else None),
                "capacity": (CAP_RE.search(body).group(1).strip()
                             if CAP_RE.search(body) else None),
                "torque": (TORQUE_RE.search(body).group(1).strip()
                           if TORQUE_RE.search(body) else None),
                "raw": line,
            }
            continue

        weight = WEIGHT_RE.search(line)
        size = SIZE_RE.search(line)
        rows.append({
            "position": (pos or "").strip().lower() or None,
            "variant": segs[0] if segs else line,
            "axle_size": size.group(1) if size else None,
            "limited_slip": 1 if LS_RE.search(line) else 0,
            "weight": weight.group(1).upper() if weight else None,
            "spec_class": next((s for s in segs if "GL-" in s.upper()), None),
            "raw": line,
        })
    return rows, tc


def summarise(rows, tc):
    out = {}
    for r in rows:
        pos = (r["position"] or "unknown").capitalize()
        key = f"{pos} differential" + (" (limited slip)" if r["limited_slip"] else "")
        out[key] = {
            "weight": r["weight"],
            "axle_size": r["axle_size"],
            "variant": r["variant"],
            "spec_class": r["spec_class"],
        }
    if tc:
        out["Transfer case"] = tc
    return out


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("usage: diff_extract.py <page-file>"); raise SystemExit(2)
    with open(path, encoding="utf-8", errors="replace") as f:
        t = f.read()
    rows, tc = extract_differentials(t)
    print(f"  {len(rows)} differential entries, transfer case: {'yes' if tc else 'no'}")
    print(json.dumps(summarise(rows, tc), indent=2))
    for r in rows:
        print(f"    RAW: {r['raw']}")
