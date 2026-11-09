#!/usr/bin/env python3
"""
Waypoint Job Check — shop floor cron reports for Mason's shop.

Three modes (detected by current hour):
  start-of-day  : 8 AM — morning briefing (held-over jobs, week status, tips)
  hourly        : 9 AM–5 PM — standard check-in
  end-of-day    : 6 PM — closing time report with open job alert

Delivery: discord:#labs-lounge
Cron jobs:
  waypoint-job-check-weekday  — 0 8-17 * * 1-5   (covers 8 AM through 5 PM)
  waypoint-job-check-saturday — 0 8-17 * * 6
  waypoint-eod-check          — 0 18   * * 1-5   (6 PM close)
"""
import sqlite3
import os
import urllib.request
import json
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/.hermes/data/vehicle_data.db")
LAT, LON = 34.99, -81.03  # Rock Hill, SC

# Service checklist — ordered for display
# Keywords matched against completed job descriptions (case-insensitive)
SERVICES = [
    ("oil_change",            "Oil Change",            ["oil change"]),
    ("tire_rotation",         "Tire Rotation",         ["tire rotation", "rotate tires", "tires rotated"]),
    ("coolant_flush",         "Coolant Flush",         ["coolant flush", "coolant fluid flush"]),
    ("brake_flush",           "Brake Flush",           ["brake flush", "flush brakes", "brake fluid flush"]),
    ("power_steering_flush",  "Power Steering Flush",  ["power steering flush", "ps flush", "power steering fluid"]),
    ("transmission_flush",    "Transmission Flush",    ["transmission flush", "trans fluid flush", "tf flush"]),
    ("alignment",             "Alignment",             ["alignment", "wheel alignment"]),
    ("battery_service",       "Battery Service",       ["battery replacement", "battery test", "battery service", "new battery", "battery"]),
]

HOURS_GOAL = 27


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def get_work_week_bounds():
    """
    Return (monday_str, saturday_str) for the current work week.
    Work week = Monday through Saturday.
    On Sunday, returns the previous Mon-Sat window.
    Both values are YYYY-MM-DD strings for SQLite DATE() comparison.
    """
    now = datetime.now()
    dow = now.weekday()  # Mon=0, Sun=6
    if dow == 6:
        # Sunday — look back at last completed work week
        days_back = 6  # back to Monday
    else:
        days_back = dow  # 0 on Monday, 5 on Saturday
    monday = now - timedelta(days=days_back)
    saturday = monday + timedelta(days=5)
    return monday.strftime("%Y-%m-%d"), saturday.strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Data queries — single source of truth for hours
# ---------------------------------------------------------------------------

def get_weekly_hours():
    """
    Sum time_in_minutes for all completed jobs in the current work week (Mon-Sat).
    Uses COALESCE(end_date, start_date) so jobs with a NULL end_date still count.
    DATE() normalizes mixed datetime formats.
    Returns (hours_float, minutes_int, job_count).
    """
    monday, saturday = get_work_week_bounds()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT
            COALESCE(SUM(time_in_minutes), 0) AS total_minutes,
            COUNT(*) AS job_count
        FROM jobs
        WHERE status = 'complete'
          AND time_in_minutes IS NOT NULL
          AND time_in_minutes > 0
          AND DATE(COALESCE(end_date, start_date)) >= ?
          AND DATE(COALESCE(end_date, start_date)) <= ?
    """, (monday, saturday))
    row = c.fetchone()
    conn.close()
    total_min = row["total_minutes"] or 0
    job_count = row["job_count"] or 0
    return round(total_min / 60, 2), int(total_min), job_count


def get_weekly_job_breakdown():
    """
    Return list of completed jobs this work week for the detailed hours view.
    Each entry: {vehicle, description, minutes, date}
    """
    monday, saturday = get_work_week_bounds()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT j.description, j.time_in_minutes,
               DATE(COALESCE(j.end_date, j.start_date)) AS job_date,
               v.year, v.make, v.model
        FROM jobs j
        JOIN vehicles v ON j.vehicle_id = v.id
        WHERE j.status = 'complete'
          AND j.time_in_minutes IS NOT NULL
          AND j.time_in_minutes > 0
          AND DATE(COALESCE(j.end_date, j.start_date)) >= ?
          AND DATE(COALESCE(j.end_date, j.start_date)) <= ?
        ORDER BY job_date ASC
    """, (monday, saturday))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_services_done_this_week():
    """
    Return a set of service keys that appear in completed job descriptions this week.
    """
    monday, saturday = get_work_week_bounds()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT description
        FROM jobs
        WHERE status = 'complete'
          AND DATE(COALESCE(end_date, start_date)) >= ?
          AND DATE(COALESCE(end_date, start_date)) <= ?
    """, (monday, saturday))
    rows = c.fetchall()
    conn.close()

    done = set()
    for (desc,) in rows:
        if not desc:
            continue
        desc_lower = desc.lower()
        for key, label, keywords in SERVICES:
            if key not in done:
                for kw in keywords:
                    if kw in desc_lower:
                        done.add(key)
                        break
    return done


def get_active_jobs():
    """Return all open/active jobs ordered by priority then start date."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT j.id, j.job_number, j.description, j.status, j.start_date,
               j.priority, v.year, v.make, v.model, cu.name AS customer_name
        FROM jobs j
        JOIN vehicles v ON j.vehicle_id = v.id
        LEFT JOIN customers cu ON v.customer_id = cu.id
        WHERE j.status IN ('open', 'active')
        ORDER BY
            CASE j.priority
                WHEN 'rush'   THEN 1
                WHEN 'high'   THEN 2
                WHEN 'normal' THEN 3
                ELSE 4
            END,
            j.start_date ASC
    """)
    jobs = c.fetchall()
    conn.close()
    return jobs


def get_held_over_jobs():
    """
    Jobs that were opened on a previous calendar day and are still open/active.
    These are the carry-overs — customer cars waiting from a prior day.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("""
        SELECT j.id, j.job_number, j.description, j.status, j.start_date,
               j.priority, v.year, v.make, v.model, cu.name AS customer_name
        FROM jobs j
        JOIN vehicles v ON j.vehicle_id = v.id
        LEFT JOIN customers cu ON v.customer_id = cu.id
        WHERE j.status IN ('open', 'active')
          AND DATE(j.start_date) < ?
        ORDER BY j.start_date ASC
    """, (today,))
    jobs = c.fetchall()
    conn.close()
    return jobs


def get_weather():
    """Fetch current conditions and today's high/low for Rock Hill, SC."""
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,weather_code,wind_speed_10m"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&timezone=America/New_York"
        f"&temperature_unit=fahrenheit"
        f"&wind_speed_unit=mph"
    )
    CODES = {
        0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
        45: "Foggy", 48: "Foggy", 51: "Drizzle", 53: "Drizzle", 55: "Drizzle",
        61: "Rain", 63: "Rain", 65: "Heavy rain",
        80: "Showers", 81: "Showers", 82: "Heavy showers",
        95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm",
    }
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        cur = data["current"]
        day = data["daily"]
        return {
            "temp": round(cur["temperature_2m"]),
            "cond": CODES.get(cur["weather_code"], "Unknown"),
            "wind": round(cur["wind_speed_10m"]),
            "high": round(day["temperature_2m_max"][0]),
            "low":  round(day["temperature_2m_min"][0]),
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shared block builders
# ---------------------------------------------------------------------------

def get_weekly_payment_split():
    """
    Paid vs loaned hours for this work week. WORKED is not the same as PAID:
    a completed job can be performed and still unpaid indefinitely (customer
    financing a repair, shop withholding until the customer pays). The hours
    block counts what was DONE; this splits it into what was PAID FOR.

    Returns (hours_by_bucket, count_by_bucket). Degrades to empty if the
    payment_status column does not exist yet, so an old DB cannot break the report.
    """
    monday, saturday = get_work_week_bounds()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        c.execute("""
            SELECT COALESCE(payment_status, '(unrecorded)') AS bucket,
                   COUNT(*) AS n,
                   COALESCE(SUM(time_in_minutes), 0) AS mins
            FROM jobs
            WHERE status = 'complete'
              AND time_in_minutes IS NOT NULL
              AND time_in_minutes > 0
              AND DATE(COALESCE(end_date, start_date)) >= ?
              AND DATE(COALESCE(end_date, start_date)) <= ?
            GROUP BY bucket
        """, (monday, saturday))
        rows = c.fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    hours = {r["bucket"]: round(r["mins"] / 60, 2) for r in rows}
    counts = {r["bucket"]: r["n"] for r in rows}
    return hours, counts


def payment_block(hours):
    """One line showing how much of the week's work was actually paid for."""
    buckets, counts = get_weekly_payment_split()
    if not buckets:
        return None
    paid   = buckets.get("paid", 0.0)
    loaned = buckets.get("loaned", 0.0)
    unrec  = buckets.get("(unrecorded)", 0.0)

    parts = []
    if paid:   parts.append(f"{paid:.1f} paid")
    if loaned: parts.append(f"{loaned:.1f} LOANED")
    if unrec:  parts.append(f"{unrec:.1f} untagged")
    if not parts:
        return None

    line = f"💰 **Money:** {' | '.join(parts)} of {hours:.1f} hr"
    if unrec:
        line += f" ({counts.get('(unrecorded)', 0)} job(s) have no payment status)"
    elif loaned and paid <= 0:
        line += " — none of this week is paid yet"
    return line


def get_banked_jobs():
    """
    Book time sitting in jobs that are NOT finished yet — the quoted hours the
    customer will be charged. This is banked money, not hours worked, so it is
    reported on its own line and never added to the 27-hour goal. Degrades to an
    empty list if the booked_minutes column does not exist yet.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT j.job_number, j.description, j.booked_minutes,
                   COALESCE((SELECT SUM(e.duration_minutes) FROM job_time_entries e
                             WHERE e.job_id = j.id), 0) AS performed_minutes
            FROM jobs j
            WHERE j.status IN ('open', 'active')
              AND j.booked_minutes IS NOT NULL
              AND j.booked_minutes > 0
            ORDER BY j.booked_minutes DESC
        """).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    return [dict(r) for r in rows]


def banked_block(hours, banked):
    """Banked (quoted, uncollected) hours line + week position. None if nothing banked."""
    if not banked:
        return None
    total = sum(j["booked_minutes"] for j in banked) / 60
    parts = []
    for j in banked:
        jid = j["job_number"] or "?"
        desc = (j["description"] or "").split("(")[0].strip()
        if len(desc) > 32:
            desc = desc[:31].rstrip() + "…"
        if len(banked) == 1:
            parts.append(f"{jid} {desc} (in progress)")
        else:
            parts.append(f"{jid} {desc} — {j['booked_minutes'] / 60:.1f} hr")
    line = f"🏦 **Banked:** {total:.1f} hr — " + "; ".join(parts)
    position = f"📈 **Position:** {hours:.1f} done + {total:.1f} banked = {hours + total:.1f} hr _(goal counts done only)_"
    return line + "\n" + position


def hours_block(hours, job_count):
    monday, saturday = get_work_week_bounds()
    if hours >= HOURS_GOAL:
        over = round(hours - HOURS_GOAL, 1)
        head = f"✅ **Hours:** {hours:.1f}/27 billed — goal met (+{over} over)"
    else:
        remaining = round(HOURS_GOAL - hours, 1)
        days_left = _work_days_remaining()
        per_day = round(remaining / days_left, 1) if days_left > 0 else remaining
        pace = f"{per_day}/day needed over {days_left} day{'s' if days_left != 1 else ''}" if days_left > 0 else "last day — push it"
        head = f"⏱ **Hours:** {hours:.1f}/27 billed — {remaining} to go ({pace})"
    lines = [head]
    bb = banked_block(hours, get_banked_jobs())
    if bb:
        lines.append(bb)
    pay = payment_block(hours)
    if pay:
        lines.append(pay)
    return "\n".join(lines)


def _work_days_remaining():
    """Count work days (Mon-Sat) remaining in this work week including today."""
    now = datetime.now()
    dow = now.weekday()  # Mon=0, Sat=5, Sun=6
    if dow == 6:
        return 0
    # Days from today through Saturday
    return 5 - dow + 1  # +1 to include today


def services_block(done):
    lines = ["**Services this week:**"]
    for key, label, _ in SERVICES:
        mark = "✅" if key in done else "⬜"
        lines.append(f"  {mark} {label}")
    return "\n".join(lines)


def open_jobs_block(jobs, header="**Open Jobs"):
    if not jobs:
        return None
    lines = [f"{header} ({len(jobs)}):**"]
    for j in jobs:
        vehicle = f"{j['year']} {j['make']} {j['model']}"
        if j['customer_name']:
            vehicle += f" ({j['customer_name']})"
        job_id = j['job_number'] or f"#{j['id']}"
        pri = f" 🚨" if j['priority'] == 'rush' else (" ⚡" if j['priority'] == 'high' else "")
        lines.append(f"  • {vehicle} — {job_id}: {j['description']}{pri}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report modes
# ---------------------------------------------------------------------------

def build_start_of_day():
    now      = datetime.now()
    weather  = get_weather()
    hours, total_min, job_count = get_weekly_hours()
    done     = get_services_done_this_week()
    held     = get_held_over_jobs()
    monday, saturday = get_work_week_bounds()

    lines = []

    # Header
    day_str = now.strftime("%A %B %-d")
    lines.append(f"🔧 **WAYPOINT — Good morning. {day_str}.**")

    if weather:
        wx = (f"{weather['temp']}°F {weather['cond']}, "
              f"wind {weather['wind']}mph | "
              f"H {weather['high']}° / L {weather['low']}°")
        lines.append(wx)

    lines.append("----------")

    # Held-over jobs — priority section
    if held:
        lines.append(f"**Held Over from Previous Day ({len(held)}):**")
        for j in held:
            vehicle = f"{j['year']} {j['make']} {j['model']}"
            if j['customer_name']:
                vehicle += f" ({j['customer_name']})"
            job_id = j['job_number'] or f"#{j['id']}"
            started = j['start_date'][:10] if j['start_date'] else "?"
            pri = " 🚨" if j['priority'] == 'rush' else (" ⚡" if j['priority'] == 'high' else "")
            lines.append(f"  • {vehicle} — {job_id}: {j['description']}{pri} _(since {started})_")
        lines.append("----------")
    else:
        lines.append("✅ **No held-over jobs.** Clean slate.")
        lines.append("----------")

    # Hours + pace
    lines.append(hours_block(hours, job_count))
    lines.append(f"  _(Week: {monday} – {saturday} | {job_count} job{'s' if job_count != 1 else ''} logged)_")
    lines.append("----------")

    # Services checklist
    lines.append(services_block(done))

    return "\n".join(lines)


def build_hourly():
    now     = datetime.now()
    weather = get_weather()
    hours, total_min, job_count = get_weekly_hours()
    done    = get_services_done_this_week()
    jobs    = get_active_jobs()

    lines = []

    time_str = now.strftime("%I:%M %p").lstrip("0")
    day_str  = now.strftime("%A")
    lines.append(f"**WAYPOINT — {day_str} {time_str}**")

    if weather:
        wx = (f"{weather['temp']}°F {weather['cond']}, "
              f"wind {weather['wind']}mph | "
              f"H {weather['high']}° / L {weather['low']}°")
        lines.append(wx)

    lines.append("----------")
    lines.append(hours_block(hours, job_count))
    lines.append("----------")
    lines.append(services_block(done))

    ob = open_jobs_block(jobs)
    if ob:
        lines.append("----------")
        lines.append(ob)

    return "\n".join(lines)


def build_end_of_day():
    now     = datetime.now()
    weather = get_weather()
    hours, total_min, job_count = get_weekly_hours()
    done    = get_services_done_this_week()
    jobs    = get_active_jobs()

    lines = []

    day_str = now.strftime("%A %B %-d")
    lines.append(f"🔒 **WAYPOINT — Closing time. {day_str}.**")

    if weather:
        wx = (f"{weather['temp']}°F {weather['cond']}, "
              f"wind {weather['wind']}mph | "
              f"H {weather['high']}° / L {weather['low']}°")
        lines.append(wx)

    lines.append("----------")

    # Open jobs — most important thing at EOD
    if jobs:
        lines.append(f"⚠️ **{len(jobs)} job{'s' if len(jobs) != 1 else ''} still open — will carry over:**")
        for j in jobs:
            vehicle = f"{j['year']} {j['make']} {j['model']}"
            if j['customer_name']:
                vehicle += f" ({j['customer_name']})"
            job_id = j['job_number'] or f"#{j['id']}"
            pri = " 🚨" if j['priority'] == 'rush' else (" ⚡" if j['priority'] == 'high' else "")
            lines.append(f"  • {vehicle} — {job_id}: {j['description']}{pri}")
        lines.append("  _These will appear in tomorrow's morning briefing._")
    else:
        lines.append("✅ **All jobs closed. Good close.**")

    lines.append("----------")

    # Day's hours summary
    lines.append(hours_block(hours, job_count))
    lines.append("----------")
    lines.append(services_block(done))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Mode detection + entry point
# ---------------------------------------------------------------------------

def build_report():
    hour = datetime.now().hour
    if hour == 8:
        return build_start_of_day()
    elif hour == 18:
        return build_end_of_day()
    else:
        return build_hourly()


def main():
    print(build_report())


if __name__ == "__main__":
    main()
