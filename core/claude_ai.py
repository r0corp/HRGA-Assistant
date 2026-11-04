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
from core.summary import MEDIA_RE, SOCIAL_RE, clean, in_window, report_title

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

SYSTEM_PROMPT = """Kamu membantu staf kantor menyusun daily report kerja dari chat WhatsApp.
Tulis HANYA teks report, tanpa pembuka, penutup, penjelasan, atau markdown (tanpa **, #, atau ```)."""

RULES = {
    "id": """Aturan:
- Baris pertama persis: {title}
- Lalu satu baris kosong, lalu daftar bernomor "1.", "2.", dst. Detail memakai sub-poin yang diawali "- ".
- Satu poin per pekerjaan. Gabungkan chat yang membahas pekerjaan yang sama menjadi satu poin dengan sub-poin per orang.
- Tulis dari sudut pandang penulis report dengan kalimat kerja yang singkat tapi jelas: apa yang dikerjakan dan hasil atau statusnya (selesai, sudah normal, masih pending, menunggu konfirmasi, dst.).
- Hanya pekerjaan kantor. Abaikan obrolan pribadi, ucapan duka atau selamat, basa-basi, candaan, notifikasi kurir atau promosi, dan hal sepele yang tidak menghasilkan apa pun.
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
- One point per task. Merge chats about the same task into one point with a sub-point per person.
- Write from the report author's point of view, short but clear: what was done and the result or status (done, back to normal, still pending, waiting for confirmation, etc.).
- Work only. Ignore personal chats, condolences or greetings, small talk, jokes, courier or promo notifications, and trivial things.
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

ROUTINE = {
    "id": "- Masukkan item rutin berikut apa adanya sebagai poin tersendiri, di nomor acak (jangan selalu di akhir):\n{items}\n",
    "en": "- Include these routine items as separate points, word for word, at random positions (not always last):\n{items}\n",
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


def build_prompt(chats, day, name="", start_hour=6, end_hour=17, lang="id", routine=()):
    title = report_title(day, name, lang)
    items = "\n".join(f"  {r}" for r in routine)
    rules = RULES[lang].format(
        title=title,
        name=name or "penulis",
        routine=ROUTINE[lang].format(items=items) if routine else "",
    )
    chats_text = chat_transcript(chats, day, start_hour, end_hour)
    return f"{rules}\n\nChat kerja tanggal {day.isoformat()} (jam {start_hour:02d}:00-{end_hour:02d}:00):\n\n{chats_text}\n"


def tidy(text, title):
    """Bersihkan jawaban Claude: buang markdown dan pastikan judulnya benar."""
    text = text.strip().replace("**", "")
    text = re.sub(r"^```\w*\n|\n```$", "", text).strip()
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.lower().startswith("daily report")), None)
    if start is None:
        lines = [title, ""] + lines
    else:
        lines = [title] + lines[start + 1:]
    return "\n".join(lines).strip()


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
