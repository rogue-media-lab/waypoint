#!/usr/bin/env python3
"""
Canonicalise an OEM fluid designator to a FAMILY name.

WHY THIS EXISTS
---------------
Every vendor writes the same fluid differently: `Honda Genuine ATF Z-1`, `Honda
Z-1`, `Z-1`. Left alone, one fluid becomes three families and corroboration
silently collapses to zero — the "identifier rendered differently by each source,
failing closed" failure this pipeline keeps hitting. Canonicalising to a family
merges the spellings.

WHAT A FAMILY IS NOT
--------------------
A family is NOT an assertion of interchangeability. NS-2 and NS-3 are separate
families on purpose. Collapsing them would claim a fluid works where it doesn't,
which on a transmission is expensive.

WHERE THIS LIVES
----------------
`~/.hermes/scripts/` — deliberately NOT the scratch dir. This module was
originally written to `~/.hermes/profiles/sage/cache/scratch/`, which is pruned
after 24h idle, so `waypoint_batch_specs.py` lost its import and broke. Code a
scheduled job depends on must live somewhere permanent.
"""
import re

# Priority-ordered. FIRST match wins, so the specific patterns come before the
# general ones (DEXRON III before bare DEXRON; SP-IV before SP-III).
RULES = [
    # --- ZF family (BMW / VW / Shell / generic part numbers map here) ---
    # `LIFEGUARD` is spelled "LifeguardFluid 8", "ZF Lifeguard 8", "ZF8" etc,
    # so match any word characters between the name and the number.
    (r"LIFEGUARD\w*\s*8|ZF\s*8\b|83\s*22\s*9\s*407\s*807|G\s*060\s*162", "ZF LIFEGUARD 8"),
    (r"LIFEGUARD\w*\s*7|ZF\s*7\s*DCT|DCT\b", "ZF LIFEGUARD 7 (DCT)"),
    (r"LIFEGUARD\w*\s*6|83\s*22\s*2\s*163\s*514|G\s*055\s*005|G\s*055\s*540", "ZF LIFEGUARD 6"),
    (r"LIFEGUARD\w*\s*5|83\s*22\s*9\s*407\s*765|G\s*052\s*162|LA-?2634|LA2634", "ZF LIFEGUARD 5"),
    (r"LIFEGUARD\w*\s*(4|3|2|1)\b", "ZF LIFEGUARD 4"),
    # --- GM ---
    (r"DEXRON\s*HP|DEX\s*HP|83\s*22\s*2\s*152\s*426", "DEXRON HP"),
    (r"DEXRON\s*(VI|6)\b", "DEXRON VI"),
    (r"DEXRON\s*III|DEXRON\s*3\b|DEXRON\s*II\b|DEXRON\s*I\b|DEXRON\b|ETL-?7045", "DEXRON III"),
    # --- Ford ---
    (r"MERCON\s*ULV", "MERCON ULV"),
    (r"MERCON\s*LV", "MERCON LV"),
    (r"MERCON\s*SP", "MERCON SP"),
    (r"MERCON\s*V\b|MERCON\s*5\b", "MERCON V"),
    (r"MOTORCRAFT\s*XT-8-QAW", "MOTORCRAFT XT-8-QAW"),
    (r"\bMERCON\b", "MERCON"),
    # --- Chrysler ---
    (r"ATF\s*\+\s*\+?\s*4|MS\s*9602|9602", "CHRYSLER ATF+4"),
    (r"ATF\s*\+\s*\+?\s*3|MS\s*7176|7176", "CHRYSLER ATF+3"),
    (r"CVT\s*\+?\s*4\b", "MOPAR CVT+4"),
    (r"AS\s*68RC", "MOPAR ASRC"),
    # --- Toyota / Mazda (JWS 3309 is shared) ---
    (r"TYPE\s*WS\b|\bWS\b", "TOYOTA WS"),
    (r"TYPE\s*T-?IV\b|T-?IV\b|JWS\s*3309|3309", "TOYOTA T-IV"),
    (r"ATF\s*FZ|FZ\s*LG\s*6|\bFZ\b", "MAZDA ATF FZ"),
    (r"ATF\s*M-?V\b|M-?V\b", "MAZDA ATF M-V"),
    # --- Honda / Acura ---
    (r"Z-?1\b|ATF\s*Z-?1", "HONDA Z-1"),
    (r"DW-?1\b", "HONDA DW-1"),
    (r"TYPE\s*2\.0", "ACURA TYPE 2.0"),
    # --- Hyundai / Kia ---
    (r"SP\s*-?\s*IV\s*RR", "SP-IV RR"),
    (r"SP\s*-?\s*IV\b|SP\s*4\b", "SP-IV"),
    (r"SP\s*-?\s*III\b|SP\s*3\b|DIAMOND", "SP-III"),
    # --- Nissan / Infiniti / Suzuki ---
    (r"NS-?3\b", "NISSAN NS-3"),
    (r"NS-?2\b", "NISSAN NS-2"),
    (r"NS-?1\b", "NISSAN NS-1"),
    (r"MATIC\s*-?\s*S\b|MATIC-?S", "NISSAN MATIC S"),
    (r"MATIC\s*-?\s*J\b", "NISSAN MATIC J"),
    (r"MATIC\s*-?\s*D\b", "NISSAN MATIC D"),
    (r"\bMATIC\b", "NISSAN MATIC"),
    # --- Subaru ---
    (r"TYPE\s*HP\b|ATF\s*HP\b|^HP$|\bHP\b", "SUBARU ATF HP"),
    (r"SUBARU\s*ATF", "SUBARU ATF"),
    # --- MB ---
    (r"236\.\d+|SHEET\s*236|MB\s*236", "MB 236.x"),
    # --- VW/Audi ---
    (r"G\s*052\s*529", "VW G 052 529 (DCT)"),
    (r"G\s*052\s*182|G\s*052\s*145", "VW G 052 182 (DCT)"),
    # --- misc named families ---
    (r"LA-?2634|LT\s*71141|71141", "ESSO LT 71141"),
]

# Normalise before matching: collapse whitespace, upper-case.
def _norm(s):
    return re.sub(r"\s+", " ", (s or "").upper()).strip()


def canonical_spec(raw):
    """Return (canonical_family, matched_rule_index) or (None, None)."""
    if not raw:
        return None, None
    n = _norm(raw)
    for i, (pat, fam) in enumerate(RULES):
        if re.search(pat, n, re.I):
            return fam, i
    return None, None


if __name__ == "__main__":
    import sys
    for a in sys.argv[1:]:
        c, i = canonical_spec(a)
        print(f"{a!r}  ->  {c!r}  (rule {i})")
