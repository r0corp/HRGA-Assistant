"""Terjemahkan draf report Indonesia -> Inggris lewat DeepL web (gratis, tanpa API key).

DeepL dibuka di Edge tanpa jendela, teks diketik ke kotak sumber, lalu hasilnya dibaca.
Aturan report tetap dijaga:
- judul memakai nama hari Indonesia dan bulan Inggris ("Daily Report Rabu/04 November 2026 (Rohman).");
- sapaan pak/mas/mba/bu tidak diterjemahkan jadi Mr./Ms.;
- susunan baris, nomor, dan sub-poin "-" sama seperti draf aslinya.
"""

import logging
import re
import time

from playwright.sync_api import sync_playwright

from core.i18n import DAYS, MONTHS

log = logging.getLogger(__name__)

DEEPL_URL = "https://www.deepl.com/translator#id/en-us/"
SOURCE_BOX = '[data-testid="translator-source-input"] [contenteditable]'
TARGET_BOX = '[data-testid="translator-target-input"]'
# Batas DeepL web gratis 1500 karakter per terjemahan; sisakan ruang.
CHUNK_LIMIT = 1300

TITLE_RE = re.compile(r"^\s*Daily Report\b.*$", re.I)
HONORIFIC_RE = re.compile(r"\b(pak|bapak|bu|ibu|mas|mba|mbak)\s+([A-Z][\w'-]*)")
ENGLISH_TITLES = r"(?:Mr|Mrs|Ms|Miss|Mister|Sir|Madam|Mdm|Brother|Sister|Bro|Sis)\.?"
QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', " ": " "})


def english_title(day, name):
    """Nama hari tetap Indonesia, bulan Inggris."""
    who = f" ({name})" if name else ""
    return f"Daily Report {DAYS['id'][day.weekday()]}/{day.day:02d} {MONTHS['en'][day.month - 1]} {day.year}{who}."


def chunks(lines, limit=CHUNK_LIMIT):
    """Kelompokkan baris jadi beberapa potong <= limit karakter (baris tidak dipotong)."""
    out, cur, size = [], [], 0
    for line in lines:
        if cur and size + len(line) + 1 > limit:
            out.append(cur)
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        out.append(cur)
    return out


def fix_honorifics(source, text):
    """Kembalikan sapaan Indonesia: "Mr. Juproni" -> "pak Juproni", "Ms. Lusi" -> "mba Lusi"."""
    seen = {}
    for hon, name in HONORIFIC_RE.findall(source):
        seen.setdefault(name, hon)
    for name, hon in seen.items():
        n = re.escape(name)
        text = re.sub(rf"\b{ENGLISH_TITLES}\s+{n}\b", f"{hon} {name}", text)
        # DeepL kadang mempertahankan sapaan tapi dengan huruf besar ("Pak Juproni").
        text = re.sub(rf"\b(?:pak|bapak|bu|ibu|mas|mba|mbak)\s+{n}\b", f"{hon} {name}", text, flags=re.I)
    return text


def align(source_lines, output):
    """Petakan hasil DeepL ke baris sumber; DeepL memisahkan tiap baris dengan baris kosong."""
    out = [l.strip() for l in output.translate(QUOTES).splitlines() if l.strip()]
    if len(out) != len(source_lines):
        log.warning("Jumlah baris DeepL %d, sumber %d", len(out), len(source_lines))
    return out


def rebuild(original, translated_lines, title):
    """Susun ulang teks dengan indentasi dan baris kosong seperti draf asli."""
    result, it = [], iter(translated_lines)
    for line in original.splitlines():
        if not line.strip():
            result.append("")
        elif TITLE_RE.match(line):
            result.append(title)
        else:
            indent = line[: len(line) - len(line.lstrip())]
            result.append(indent + next(it, line.strip()))
    # Sisa baris (kalau DeepL memecah satu baris jadi dua) tetap ditambahkan.
    result.extend(rest for rest in it)
    return "\n".join(result).strip() + "\n"


def _launch(pw):
    last = None
    for channel in ("msedge", "chrome"):
        try:
            return pw.chromium.launch(channel=channel, headless=True)
        except Exception as e:
            last = e
            log.warning("Browser %s tidak bisa dibuka: %s", channel, e)
    raise RuntimeError(f"Browser tidak bisa dibuka: {last}")


def _translate_chunk(page, text, timeout=60):
    box = page.locator(SOURCE_BOX)
    box.click()
    page.keyboard.press("Control+A")
    page.keyboard.press("Delete")
    page.keyboard.insert_text(text)
    target = page.locator(TARGET_BOX)
    last, stable, end = "", 0, time.time() + timeout
    # Hasil dianggap selesai setelah tidak berubah sekitar 2 detik.
    while time.time() < end:
        time.sleep(0.5)
        now = target.inner_text().strip()
        stable = stable + 1 if now and now == last else 0
        last = now
        if stable >= 4:
            return now
    raise RuntimeError("DeepL tidak memberi hasil terjemahan. Cek koneksi internet atau coba lagi nanti.")


def translate(text, day, name, progress=None):
    """Terjemahkan draf report ke Inggris. progress(pct) dipanggil selama proses."""
    lines = [l.strip() for l in text.splitlines() if l.strip() and not TITLE_RE.match(l)]
    if not lines:
        raise RuntimeError("Draf kosong, tidak ada yang diterjemahkan.")
    parts = chunks(lines)
    translated = []
    with sync_playwright() as pw:
        browser = _launch(pw)
        try:
            page = browser.new_page()
            page.goto(DEEPL_URL, wait_until="domcontentloaded", timeout=45000)
            page.locator(SOURCE_BOX).wait_for(timeout=30000)
            for i, part in enumerate(parts):
                if progress:
                    progress(20 + int(70 * i / len(parts)))
                out = _translate_chunk(page, "\n".join(part))
                got = align(part, out)
                # Kalau jumlah baris tidak cocok, pakai apa adanya supaya tidak ada yang hilang.
                translated.extend(got)
        finally:
            browser.close()
    result = rebuild(text, translated, english_title(day, name))
    return fix_honorifics(text, result)
