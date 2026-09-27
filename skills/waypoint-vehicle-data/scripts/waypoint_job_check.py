#!/usr/bin/env python3
"""
Waypoint Job Check — shop floor cron reports for Mason's shop.
See full source at ~/.hermes/scripts/waypoint_job_check.py
Skill reference copy — keep in sync with deployed script.

Three modes detected by current hour:
  8 AM  → start-of-day (morning briefing)
  18    → end-of-day   (closing time)
  other → hourly check-in
"""
# Full source maintained at ~/.hermes/scripts/waypoint_job_check.py
# This file is a pointer — the deployed script is the canonical version.
