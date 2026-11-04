"""Riwayat report yang sudah dikirim ke grup, untuk timeline 5 hari kerja."""

import json
import re
from datetime import date, datetime, timedelta

from core.i18n import MONTHS


MONTH_NUM = {m.lower(): i + 1 for names in MONTHS.values() for i, m in enumerate(names)}

# "Daily Report Rabu/04 November 2026 (Nama)." atau versi Inggrisnya.
TITLE_RE = re.compile(r"(?i)daily\s+report\s+\w+\s*/\s*(\d{1,2})\s+([a-z]+)\s+(\d{4})")


def report_date(text):
    """Tanggal report dari judulnya, atau None kalau bukan pesan daily report."""
    m = TITLE_RE.search((text or "")[:120])
    if not m:
        return None
    month = MONTH_NUM.get(m.group(2).lower())
    if not month:
        return None
    try:
        return date(int(m.group(3)), month, int(m.group(1)))
    except ValueError:
        return None


def workdays(today, n=5):
    """n hari kerja (Senin-Jumat) terakhir sampai hari ini, urut dari terlama."""
    days = []
    d = today
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


def from_messages(messages):
    """Pesan grup -> {tanggal_report_iso: waktu_kirim_iso} untuk pesan sendiri."""
    found = {}
    for m in messages:
        if not m["out"]:
            continue
        d = report_date(m["text"])
        if d:
            found[d.isoformat()] = m["time"]
    return found


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, sort_keys=True)


def merge(path, found):
    data = load(path)
    data.update(found)
    save(path, data)
    return data


def mark_sent(path, day, when=None):
    when = when or datetime.now()
    return merge(path, {day.isoformat(): when.isoformat(timespec="minutes")})
