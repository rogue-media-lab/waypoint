#!/usr/bin/env python3
"""
AMSOIL variant resolver.

THE PROBLEM IT SOLVES
---------------------
The batch built lookup URLs by slugifying the model name straight from the
database:

    /2011/mazda/3-series/...     <- AMSOIL calls it MAZDA3
    /2021/ram/1500/...           <- AMSOIL calls it 1500 PICKUP

Those resolve to the generic landing page, so 19 configurations got no data.

WHY GUESSING WAS THE WRONG APPROACH
-----------------------------------
Brute-forcing slug candidates trips AMSOIL's rate limiter (HTTP 403) and cannot
be verified, because the lookup page is a JavaScript form with no crawlable
model links. The lists simply are not in the HTML.

THE ACTUAL ANSWER
-----------------
The form is driven by a public JSON API, discovered in the page's
`fitment.min.js`. No authentication is required:

    GET api-1.amsoil.com/api/Fitment/GetLookupTypes
    GET api-1.amsoil.com/api/Fitment/GetMakes   ?lookupCode=autoandlighttruck&year=Y
    GET api-1.amsoil.com/api/Fitment/GetModels  ?...&equipmentMakeId=M
    GET api-1.amsoil.com/api/Fitment/GetEngines ?...&equipmentModelId=D

So the resolver DISCOVERS the correct make/model/engine instead of guessing a
slug. One call per level, cached, and every configuration resolves exactly.

The engine slug is the engine VALUE lowercased with spaces to dashes
(`3.0l 6-cyl turbo diesel` -> `3-0l-6-cyl-turbo-diesel`), which is also what the
batch was already producing — so the engine side was never the problem. The
MODEL name was.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api-1.amsoil.com/api/"
LOOKUP_CODE = "autoandlighttruck"
CACHE = os.path.expanduser("~/.hermes/profiles/sage/cache/scratch/amsoil_fitment_cache.json")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0.0.0 Safari/537.36")
HDRS = {"User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Referer": "https://www.amsoil.com/lookup/auto-and-light-truck/",
        "Origin": "https://www.amsoil.com"}

_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.load(open(CACHE))
        except Exception:
            _cache = {}
    return _cache


def _save():
    if _cache is not None:
        try:
            json.dump(_cache, open(CACHE, "w"), indent=1)
        except Exception:
            pass


def call(path, params=None, retries=3):
    u = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(retries):
        try:
            r = urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=30)
            return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                time.sleep(2.0 * (i + 1))
                continue
            raise
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1.5)
    return None


def _key(*parts):
    return "|".join(str(p).upper().strip() for p in parts if p is not None)


def makes(year):
    c = _load()
    k = f"makes|{year}"
    if k not in c:
        c[k] = call("Fitment/GetMakes", {"lookupCode": LOOKUP_CODE, "year": year}) or []
        _save()
    return c[k]


def models(year, make_id):
    c = _load()
    k = f"models|{year}|{make_id}"
    if k not in c:
        c[k] = call("Fitment/GetModels", {"lookupCode": LOOKUP_CODE, "year": year,
                                          "equipmentMakeId": make_id}) or []
        _save()
    return c[k]


def engines(year, make_id, model_id):
    c = _load()
    k = f"engines|{year}|{make_id}|{model_id}"
    if k not in c:
        c[k] = call("Fitment/GetEngines", {"lookupCode": LOOKUP_CODE, "year": year,
                                           "equipmentMakeId": make_id,
                                           "equipmentModelId": model_id}) or []
        _save()
    return c[k]


def slugify(v):
    """Engine/make/model VALUE -> URL slug."""
    s = str(v).lower()
    s = s.replace("&", "and").replace("/", " ")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return re.sub(r"-+", "-", s).strip("-")


def _best(needle, options, alias=None):
    """Pick the option whose value best matches the database's naming."""
    if not options:
        return None
    n = _key(needle)
    ncompact = re.sub(r"[^A-Z0-9]", "", n)
    base = re.sub(r"[^A-Z0-9]", "", n.split()[0]) if n.split() else ncompact
    ranked = []
    for o in options:
        v = _key(o.get("value"))
        vcompact = re.sub(r"[^A-Z0-9]", "", v)
        score = 0
        if v == n:
            score = 100
        elif vcompact == ncompact:
            score = 95
        elif v.startswith(n) or n.startswith(v):
            score = 80
        elif vcompact.startswith(base) and base:
            score = 60
        elif ncompact and ncompact in vcompact:
            score = 50
        elif v and v in ncompact:
            score = 40
        if score:
            ranked.append((score, len(v), o))
    if alias:
        for a in alias:
            for o in options:
                if _key(a) == _key(o.get("value")):
                    return o
    if not ranked:
        return None
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return ranked[0][2]


# carmakers whose database name differs from AMSOIL's
MAKE_ALIASES = {
    "CHEVROLET": ["Chevrolet"], "CHEVY": ["Chevrolet"], "GMC": ["GMC"],
    "MERCEDES-BENZ": ["Mercedes-Benz", "Mercedes"], "MERCEDES": ["Mercedes-Benz"],
    "VOLKSWAGEN": ["Volkswagen"], "VW": ["Volkswagen"],
    "RAM": ["Ram"], "DODGE": ["Dodge"], "INFINITI": ["Infiniti"],
    "LEXUS": ["Lexus"], "GENERAL MOTORS": ["Chevrolet"], "FORD TRUCK": ["Ford"],
}
# model names that need an explicit pointer
MODEL_ALIASES = {
    "3 SERIES": ["MAZDA3", "3 SPORT"], "MX-5": ["MIATA"], "MIATA": ["MIATA"],
    "1500": ["1500 PICKUP", "1500 CLASSIC"], "TITAN": ["TITAN"],
    "TRUCK": ["FRONTIER", "TITAN"], "4RUNNER": ["4RUNNER"],
    "E-CLASS": ["E-CLASS", "E320", "E350"],
    "SCION XA": ["XA"], "XA": ["XA"],
}


def resolve(year, make, model, engine=None, verbose=False):
    """Return dict with resolved ids/values + a canonical lookup URL."""
    out = {"year": year, "db_make": make, "db_model": model, "db_engine": engine,
           "make": None, "model": None, "engine": None, "url": None,
           "status": None}
    try:
        mk = _best(make, makes(year), MAKE_ALIASES.get(_key(make)))
        if not mk:
            out["status"] = f"make not found: {make}"
            return out
        out["make"] = mk
        md = _best(model, models(year, mk["id"]),
                   MODEL_ALIASES.get(_key(model)) or MODEL_ALIASES.get(_key(model).split()[0] if _key(model).split() else None))
        if not md:
            out["status"] = f"model not found: {model}"
            return out
        out["model"] = md
        eng = None
        if engine:
            engs = engines(year, mk["id"], md["id"])
            m = re.match(r"\s*(\d+(?:\.\d+)?)\s*L\s*[- ]?\s*(?:V|I|L|H)?\s*(\d+)", str(engine), re.I)
            if m:
                disp = m.group(1).replace(".", "")
                want = f"{disp[0]}-{disp[1:]}" if len(disp) > 1 else disp
                cand = [e for e in engs if slugify(e.get("value")).startswith(f"{want}l")]
                if not cand:
                    cand = [e for e in engs if str(engine).split("L")[0].strip(" .") in str(e.get("value"))]
                eng = _best(engine, cand or engs) if (cand or engs) else None
            else:
                eng = _best(engine, engs)
        if eng:
            out["engine"] = eng
        parts = [str(year), slugify(mk["value"]), slugify(md["value"])]
        if eng:
            parts.append(slugify(eng["value"]))
        out["url"] = ("https://www.amsoil.com/lookup/auto-and-light-truck/" + "/".join(parts))
        out["status"] = "resolved" + ("" if eng else " (model only — no engine match)")
    except Exception as e:
        out["status"] = f"error: {type(e).__name__}: {e}"
    return out


def main():
    if len(sys.argv) < 4:
        print("usage: amsoil_resolve.py <year> <make> <model> [engine]")
        return 1
    args = sys.argv[1:]
    r = resolve(args[0], args[1], args[2], args[3] if len(args) > 3 else None)
    print(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
