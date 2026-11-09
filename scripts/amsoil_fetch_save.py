#!/usr/bin/env python3
"""Fetch one AMSOIL lookup page (browser headers, 200 OK) and save the body.

Composes waypoint_batch_specs.fetch — no fetch logic of its own. Reused so the
agent can hand the SAME text to filters-extract / diff-extract.

usage: amsoil_fetch_save.py <url> <out_file>
"""
import os
import sys

sys.path.insert(0, os.path.expanduser("~/.hermes/scripts"))
from waypoint_batch_specs import fetch  # noqa: E402


def main():
    if len(sys.argv) < 3:
        print("usage: amsoil_fetch_save.py <url> <out_file>")
        return 2
    url, out = sys.argv[1], sys.argv[2]
    body = fetch(url)
    with open(out, "w") as f:
        f.write(body)
    print(f"{len(body)} bytes -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
