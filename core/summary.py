"""Menyusun draf daily report dari chat tanpa AI: satu poin per chat."""

import re
from datetime import datetime

from core.i18n import DAYS, MONTHS, t
from core.redact import redact

# Kata basa-basi; pesan yang seluruh katanya dari daftar ini dibuang.
FILLER_WORD_RE = re.compile(
    r"(?i)^(ok|oke+|okey|okay|siap+|sip+|noted|thanks?|thank|you|thx|tq|tks|makasih|"
    r"terima|kasih|sama|iya+|ya+|y|yo+|baik|aman|mantap|done|beres|wkwk\w*|haha\w*|"
    r"hehe\w*|hihi\w*|alhamdulillah|pagi|siang|sore|malam|halo|hai+|p|pak|bu|mba|mbak|"
    r"mas|bang|kak|dek|deh|dong|nya|ok-ok|sama-sama)$"
)

# Penanda lampiran dari WhatsApp Web.
MEDIA_RE = re.compile(
    r"(?i)^(\d+\s+)?(photo|photos|image|video|videos|sticker|gif|audio|voice message|"
    r"document|foto|gambar|stiker|pesan suara)s?$"
)

URL_RE = re.compile(r"https?://([^/\s:]+)\S*")

MAX_POINTS = 3
MAX_CHARS = 160


def report_title(day, name, lang="id"):
    who = f" ({name})" if name else ""
    return f"Daily Report {DAYS[lang][day.weekday()]}/{day.day:02d} {MONTHS[lang][day.month - 1]} {day.year}{who}."


def clean(text):
    """Link diringkas jadi nama situsnya saja, mis. "[link shopee.co.id]"."""
    return URL_RE.sub(lambda m: f"[link {m.group(1).removeprefix('www.')}]", text or "").strip()


def is_meaningful(text):
    # Link tidak dihitung sebagai kata: pesan berisi link saja tidak menjelaskan pekerjaan.
    text = URL_RE.sub("", text or "").strip()
    if not text or MEDIA_RE.match(text):
        return False
    words = [w for w in re.split(r"[\s,.!?]+", text) if w]
    # Emoji/tanda baca saja, atau seluruhnya basa-basi.
    if not re.search(r"\w", text) or all(FILLER_WORD_RE.match(w) for w in words):
        return False
    return len(words) >= 3


def in_window(msg, day, start_hour, end_hour):
    dt = datetime.fromisoformat(msg["time"])
    return dt.date() == day and start_hour <= dt.hour < end_hour


def shorten(text):
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."


def key_messages(messages):
    """Pilih maksimal 3 pesan yang paling menjelaskan isi chat.

    Pesan masuk pertama biasanya permintaan, pesan keluar terakhir biasanya
    jawaban/hasil, sisanya diisi pesan terpanjang.
    """
    useful = [m for m in messages if is_meaningful(m["text"])]
    if not useful:
        return []

    picked = []
    first_in = next((m for m in useful if not m["out"]), None)
    last_out = next((m for m in reversed(useful) if m["out"]), None)
    for m in (first_in, last_out):
        if m and m not in picked:
            picked.append(m)

    for m in sorted(useful, key=lambda m: len(m["text"]), reverse=True):
        if len(picked) >= MAX_POINTS:
            break
        if m not in picked:
            picked.append(m)

    return sorted(picked, key=lambda m: m["time"])


def build_report(chats, day, name="", start_hour=6, end_hour=17, lang="id"):
    """chats: {nama_chat: [pesan]} -> teks draf report."""
    items = []

    for chat, messages in chats.items():
        msgs = [m for m in messages if in_window(m, day, start_hour, end_hour)]
        points = key_messages(msgs)
        if not points:
            continue

        first = msgs[0]["time"][11:16]
        last = msgs[-1]["time"][11:16]
        span = first if first == last else f"{first}-{last}"

        lines = [f"{chat} ({span}):"]
        for m in points:
            who = t(lang, "me") if m["out"] else m["sender"]
            lines.append(f"- {who}: {shorten(redact(clean(m['text'])))}")
        items.append((first, lines))

    # Urut dari pekerjaan paling pagi.
    items.sort(key=lambda it: it[0])

    out = [report_title(day, name, lang), ""]
    if not items:
        out.append(t(lang, "empty_report", start=start_hour, end=end_hour))
    for i, (_, lines) in enumerate(items, 1):
        out.append(f"{i}. {lines[0]}")
        out.extend(lines[1:])

    return "\n".join(out)
