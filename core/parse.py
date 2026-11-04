import re
from datetime import date, datetime, timedelta


# Atribut data-pre-plain-text pada tiap pesan, mis. "[15:24, 10/27/2026] Jamal: "
# atau "[3:24 PM, 10/27/2026] Jamal: ".
PRE_RE = re.compile(
    r"^\[(?P<time>\d{1,2}[:.]\d{2})(?:\s*(?P<ampm>[AaPp][Mm]))?,\s*"
    r"(?P<date>\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4})\]\s*(?P<sender>.*?):\s*$"
)

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

TIME_LABEL_RE = re.compile(r"^\d{1,2}[:.]\d{2}(\s*[AaPp][Mm])?$")
DATE_LABEL_RE = re.compile(r"^\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}$")


def parse_date(text, order="MDY"):
    parts = [int(p) for p in re.split(r"[/.-]", text)]

    if parts[0] > 999:
        y, m, d = parts
    elif order == "DMY":
        d, m, y = parts
    else:
        m, d, y = parts

    if y < 100:
        y += 2000

    # Bagian "bulan" > 12 berarti urutannya terbalik dari tebakan.
    if m > 12 and d <= 12:
        m, d = d, m

    return date(y, m, d)


def detect_order(date_texts, default="MDY"):
    """Tebak urutan tanggal dari beberapa contoh: bagian > 12 pasti hari.

    Atribut pesan dan label daftar chat di WhatsApp Web bisa beda urutan
    (mis. pesan 27/10/2026 tetapi label 10/20/2026), jadi dideteksi terpisah.
    """
    for text in date_texts:
        parts = [int(p) for p in re.split(r"[/.-]", text)]
        if parts[0] > 999:
            continue
        if parts[0] > 12:
            return "DMY"
        if parts[1] > 12:
            return "MDY"
    return default


def pre_date_text(pre):
    m = PRE_RE.match(pre.strip())
    return m.group("date") if m else None


def parse_pre(pre, order="MDY"):
    """Kembalikan (datetime, pengirim) dari data-pre-plain-text, atau None."""
    m = PRE_RE.match(pre.strip())
    if not m:
        return None

    hh, mm = (int(x) for x in re.split(r"[:.]", m.group("time")))
    ampm = (m.group("ampm") or "").upper()
    if ampm == "PM" and hh < 12:
        hh += 12
    elif ampm == "AM" and hh == 12:
        hh = 0

    d = parse_date(m.group("date"), order)

    return datetime(d.year, d.month, d.day, hh, mm), m.group("sender").strip()


def label_to_date(label, today, order="MDY"):
    """Label waktu di daftar chat ("15:28", "Yesterday", "Friday", "10/20/2026") -> tanggal."""
    label = label.strip()

    if TIME_LABEL_RE.match(label):
        return today

    if label == "Yesterday":
        return today - timedelta(days=1)

    if label in WEEKDAYS:
        # Nama hari dipakai WhatsApp untuk 2-6 hari ke belakang.
        back = (today.weekday() - WEEKDAYS.index(label)) % 7 or 7
        return today - timedelta(days=back)

    if DATE_LABEL_RE.match(label):
        return parse_date(label, order)

    return None
