"""Menyusun daily report dengan Claude Code yang terpasang di laptop.

Memakai akun langganan Claude yang login di laptop itu (auth login --claudeai),
bukan API key, jadi tidak ada biaya tambahan di luar langganan. Semua tool
Claude dimatikan: Claude hanya menerima teks chat dan mengembalikan teks report.
"""

import glob
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime

from core.redact import redact
from core.summary import MEDIA_RE, SOCIAL_RE, clean, in_window, nickname_form, report_title

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SYSTEM_PROMPT = """Kamu membantu staf kantor menyusun daily report kerja dari chat WhatsApp.
Tulis HANYA teks report, tanpa pembuka, penutup, penjelasan, atau markdown (tanpa **, #, atau ```)."""

RULES = {
    "id": """Aturan:
- Baris pertama persis: {title}
- Lalu satu baris kosong, lalu daftar bernomor "1.", "2.", dst. Detail memakai sub-poin yang diawali "- ".
- Jangan ada baris kosong di antara nomor maupun sub-poin; semua poin ditulis rapat.
- Satu poin per pekerjaan. Gabungkan chat yang membahas pekerjaan yang sama menjadi satu poin dengan sub-poin per orang.
- Tulis dari sudut pandang penulis report dengan kalimat kerja yang singkat tapi jelas: apa yang dikerjakan dan hasil atau statusnya (selesai, sudah normal, masih pending, menunggu konfirmasi, dst.).
- Hanya pekerjaan kantor. Abaikan obrolan pribadi, ucapan duka atau selamat, basa-basi, candaan, notifikasi kurir atau promosi, dan hal sepele yang tidak menghasilkan apa pun.
- Buang juga: saran cepat lewat chat, info atau permintaan yang hanya diterima, koordinasi kecil (mis. orang datang ke ruangan, janji ketemu), masalah sepele (mis. kertas printer habis, stok kosong), dan pekerjaan yang belum ada hasil atau isinya di chat.
- Jangan pernah menulis kalimat seperti "tidak tertulis di chat", "detailnya belum ada di chat", atau "topiknya tidak diketahui"; kalau isinya tidak jelas, poin itu dibuang.
- Permintaan atau pembelian barang (kabel, mouse, titip beli, Shopee, dsb.) tidak dimasukkan sama sekali, kecuali pembelian atau lisensi software.
- Jangan tulis harga, nomor, atau spesifikasi panjang; cukup inti pekerjaannya dan hasilnya.
- Jangan mengarang. Semua isi harus berasal dari chat. Kalau statusnya tidak jelas, tulis apa adanya.
- Jangan pernah menulis password, OTP, PIN, atau nomor rekening.
- Nama orang: buang awalan "TCI". Pakai sapaan pak/bu/mba/mas hanya kalau terlihat dari chat; kalau ragu, tulis namanya saja.
- "Saya" di chat adalah penulis report ({name}).
{routine}- Bahasa report: Bahasa Indonesia.
- Kalau tidak ada pekerjaan sama sekali, tulis judul lalu "(Tidak ada pekerjaan dari chat.)".

Contoh gaya penulisan (nama dan isi hanya contoh):
1. Follow up masalah storage OneDrive ke user:
- Budi dan Sari: sudah aman, notifikasi storage penuh tidak muncul lagi.
- mba Rina: dipandu menjalankan "Free up space"; file bisa dibuka normal.
2. Penanganan printer lantai 2 (Andi): kertas macet, roller dibersihkan; printer kembali normal.
3. Koordinasi pengajuan ATK mingguan dengan Andi: form sudah diterima, menunggu persetujuan atasan.""",
    "en": """Rules:
- The first line must be exactly: {title}
- Then one blank line, then a numbered list "1.", "2.", etc. Details use sub-points starting with "- ".
- No blank lines between numbers or sub-points; keep the list compact.
- One point per task. Merge chats about the same task into one point with a sub-point per person.
- Write from the report author's point of view, short but clear: what was done and the result or status (done, back to normal, still pending, waiting for confirmation, etc.).
- Work only. Ignore personal chats, condolences or greetings, small talk, jokes, courier or promo notifications, and trivial things.
- Also drop: quick advice over chat, information or requests that were only received, small coordination (e.g. someone dropping by, arranging a meeting), trivial issues (e.g. printer out of paper, empty stock), and work with no result or content in the chats.
- Never write sentences like "not stated in the chat" or "details not in the chat"; if the content is unclear, drop the point.
- Requests for or purchases of goods (cables, mice, buying via Shopee, etc.) are never included, except software purchases or licenses.
- Do not write prices, numbers, or long specifications; keep only the core task and result.
- Do not invent anything. Everything must come from the chats. If the status is unclear, say so.
- Never write passwords, OTPs, PINs, or account numbers.
- People's names: drop the "TCI" prefix. Keep Indonesian honorifics (pak/bu/mba/mas) as they are, only when visible in the chat.
- "Saya" in the chats is the report author ({name}).
{routine}- Report language: English. Translate the content into natural English.
- If there is no work at all, write the title followed by "(No work found in the chats.)".

Style example (names and content are only examples):
1. Followed up OneDrive storage issues with users:
- Budi and Sari: resolved, the storage full notification no longer appears.
- mba Rina: guided through "Free up space"; files open normally.
2. Printer support on the 2nd floor (Andi): paper jam, roller cleaned; printer back to normal.""",
}

NICKNAMES = {
    "id": "- Pakai sapaan ini setiap menyebut orang tersebut (huruf kecil, sebelum nama), mis. 'pak Juproni':\n{items}\n",
    "en": "- Always use these Indonesian honorifics before the person's name (lowercase), e.g. 'pak Juproni':\n{items}\n",
}

ROUTINE = {
    "id": "- Masukkan item rutin berikut apa adanya sebagai poin tersendiri, di nomor acak (jangan selalu di akhir):\n{items}\n",
    "en": "- Include these routine items as separate points, word for word, at random positions (not always last):\n{items}\n",
}


# Catatan manual dari user: pekerjaan yang tidak ada di chat.
MANUAL = {
    "id": "Catatan manual dari penulis (pekerjaan yang tidak ada di chat). WAJIB dimasukkan sebagai poin report; rapikan kalimatnya tanpa mengubah isinya:\n",
    "en": "Manual notes from the author (work that is not in the chats). They MUST be included as report points; tidy the wording without changing the content:\n",
}


def find_cli():
    """Lokasi claude.exe: dari PATH, instalasi CLI, atau bawaan aplikasi Claude desktop."""
    found = shutil.which("claude")
    if found:
        return found
    home = os.path.expanduser("~")
    local = os.path.join(home, ".local", "bin", "claude.exe")
    if os.path.exists(local):
        return local

    # Aplikasi Claude desktop menyimpan Claude Code di %APPDATA%\Claude\claude-code\<versi>\<hash>\.
    appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    bundled = glob.glob(os.path.join(appdata, "Claude", "claude-code", "*", "*", "claude.exe"))

    def version(path):
        v = os.path.basename(os.path.dirname(os.path.dirname(path)))
        return tuple(int(p) if p.isdigit() else 0 for p in v.split("."))

    return max(bundled, key=version) if bundled else None


def status(cli):
    """{"loggedIn": bool, "email": ..., ...} dari `claude auth status --json`."""
    r = subprocess.run([cli, "auth", "status", "--json"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30, creationflags=NO_WINDOW)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return {"loggedIn": False}


def login(cli):
    """Buka login akun langganan Claude di jendela console sendiri (browser ikut terbuka)."""
    return subprocess.Popen([cli, "auth", "login", "--claudeai"],
                            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))


def logout(cli):
    subprocess.run([cli, "auth", "logout"], capture_output=True, text=True, timeout=30, creationflags=NO_WINDOW)


def chat_transcript(chats, day, start_hour, end_hour, me="Saya"):
    """Chat terpilih -> teks ringkas untuk Claude, sudah disaring dan disamarkan."""
    parts = []
    for name, messages in chats.items():
        lines = []
        for m in messages:
            text = (m.get("text") or "").strip()
            if not in_window(m, day, start_hour, end_hour) or not text or MEDIA_RE.match(text):
                continue
            if SOCIAL_RE.search(text):
                continue
            who = me if m["out"] else m["sender"]
            hhmm = datetime.fromisoformat(m["time"]).strftime("%H:%M")
            lines.append(f"[{hhmm}] {who}: {' '.join(redact(clean(text)).split())}")
        if lines:
            parts.append(f"### Chat: {name}\n" + "\n".join(lines))
    return "\n\n".join(parts)


def build_prompt(chats, day, name="", start_hour=6, end_hour=17, lang="id", routine=(), manual=(),
                 nicknames=None):
    title = report_title(day, name, lang)
    items = "\n".join(f"  {r}" for r in routine)
    nick = "\n".join(f"  {n}: {nickname_form(n, h)}" for n, h in (nicknames or {}).items())
    rules = RULES[lang].format(
        title=title,
        name=name or "penulis",
        routine=(ROUTINE[lang].format(items=items) if routine else "")
        + (NICKNAMES[lang].format(items=nick) if nick else ""),
    )
    chats_text = chat_transcript(chats, day, start_hour, end_hour)
    notes = ""
    if manual:
        notes = MANUAL[lang] + "\n".join(f"- {' '.join(redact(m).split())}" for m in manual) + "\n\n"
    return (f"{rules}\n\n{notes}"
            f"Chat kerja tanggal {day.isoformat()} (jam {start_hour:02d}:00-{end_hour:02d}:00):\n\n{chats_text}\n")


STORY = {
    "id": """Penulis menceritakan pekerjaannya hari ini dengan bahasa sehari-hari (bisa hasil dikte suara,
jadi mungkin ada salah ketik atau kalimat berantakan). Susun menjadi daily report.
Aturan:
- Baris pertama persis: {title}
- Lalu satu baris kosong, lalu daftar bernomor "1.", "2.", dst., rapat tanpa baris kosong di antara nomor.
  Detail boleh memakai sub-poin yang diawali "- ".
- Satu poin per pekerjaan, kalimat kerja singkat tapi jelas: apa yang dikerjakan, di mana/untuk siapa, dan
  hasilnya kalau disebut.
- HANYA isi yang ada di cerita. Jangan menambah pekerjaan, tempat, nama, jam, atau hasil yang tidak disebut.
- Buang basa-basi dan hal pribadi. Jangan tulis password, OTP, PIN, atau nomor rekening.
- Perbaiki ejaan dan kata yang jelas salah dengar dari dikte suara.
{routine}- Bahasa report: Bahasa Indonesia.""",
    "en": """The author describes today's work in everyday language (possibly voice dictation with typos).
Turn it into a daily report.
Rules:
- The first line must be exactly: {title}
- Then one blank line, then a compact numbered list "1.", "2.", etc. with no blank lines. Details may use
  sub-points starting with "- ".
- One point per task, short but clear: what was done, where/for whom, and the result if mentioned.
- ONLY what is in the story. Never add tasks, places, names, times, or results that were not mentioned.
- Drop small talk and personal matters. Never write passwords, OTPs, PINs, or account numbers.
- Fix spelling and words clearly misheard by voice dictation.
{routine}- Report language: English.""",
}


def build_story_prompt(story, day, name="", lang="id", routine=()):
    """Cerita bebas (ketik/dikte dari HP) -> prompt daily report."""
    title = report_title(day, name, lang)
    items = "\n".join(f"  {r}" for r in routine)
    rules = STORY[lang].format(title=title, routine=ROUTINE[lang].format(items=items) if routine else "")
    return f"{rules}\n\nCerita penulis ({name or 'penulis'}):\n{' '.join(redact(story).split())}\n"


def tidy(text, title):
    """Bersihkan jawaban Claude: buang markdown dan pastikan judulnya benar."""
    text = text.strip().replace("**", "")
    text = re.sub(r"^```\w*\n|\n```$", "", text).strip()
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("daily report")), None)
    body = lines if start is None else lines[start + 1:]
    # Daftar ditulis rapat: tanpa baris kosong di antara nomor (hanya satu setelah judul).
    body = [l.rstrip() for l in body if l.strip()]
    return "\n".join([title, ""] + body).strip()


def generate(cli, prompt, title, timeout=300):
    """Jalankan Claude tanpa tool dan tanpa jendela; kembalikan teks report."""
    # Folder kosong sebagai working directory supaya tidak ada file proyek yang ikut terbaca.
    with tempfile.TemporaryDirectory(prefix="hrga-claude-") as cwd:
        r = subprocess.run(
            [cli, "-p", "--output-format", "text", "--model", "sonnet",
             "--tools", "", "--strict-mcp-config", "--no-session-persistence",
             "--system-prompt", SYSTEM_PROMPT],
            input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=cwd, timeout=timeout, creationflags=NO_WINDOW,
        )
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not out:
        raise RuntimeError((r.stderr or out or f"exit {r.returncode}").strip()[:300])
    if "not logged in" in out.lower() or "/login" in out.lower():
        raise RuntimeError(out[:300])
    return tidy(out, title)
