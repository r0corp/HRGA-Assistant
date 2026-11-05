"""Chat dengan Claude di dalam app, memakai Claude Code langganan di laptop ini.

Setiap pesan dikirim ulang bersama riwayat percakapan dan konteks hari itu
(draf report + chat WhatsApp yang sudah disamarkan), jadi tidak ada sesi
yang disimpan di luar app. Jawaban dialirkan sepotong-sepotong supaya
langsung tampil saat Claude mengetik.
"""

import json
import re
import subprocess
import tempfile

from core.claude_ai import NO_WINDOW, chat_transcript
from core.redact import redact

SYSTEM_PROMPT = """Kamu asisten di aplikasi "HRGA WA Report" milik staf HRGA PT Tradecorp Indonesia.
Bantu penulis report: menjawab pertanyaan, merapikan atau merevisi daily report, menjelaskan isi chat kerja,
menyusun pesan, atau pertanyaan umum lainnya. Jawab singkat, jelas, dalam bahasa yang dipakai penulis.
Tulis teks biasa tanpa markdown (tanpa **, #, atau tabel).

Report disusun otomatis dari chat, jadi bisa saja tidak sesuai kenyataan. Kalau penulis bertanya tentang suatu
poin (mis. "poin 3 dari mana?"), tunjukkan dasar poin itu dari chat di konteks: nama chat, jam, dan kutipan
singkat pesannya. Kalau tidak ada dasarnya di chat, katakan terus terang. Kalau penulis mengoreksi (mis. "itu
bukan kerjaan saya", "sebenarnya sudah selesai"), percayai koreksi penulis dan tawarkan report yang sudah diperbaiki.
Kalau ada hal yang kurang jelas, boleh balik bertanya ke penulis.

Setiap kali kamu menulis report (diubah, ditambah, dihapus, atau dibuat ulang), WAJIB tulis report LENGKAP
versi barunya di antara baris [REPORT] dan [/REPORT] (masing-masing di baris sendiri). Aplikasi langsung
memasang isi blok itu ke draf, jadi report di luar blok tidak akan tersimpan. Format: baris pertama persis
judul report dari konteks, satu baris kosong, lalu daftar bernomor rapat tanpa baris kosong di antara nomor.
Penjelasan singkat boleh ditulis di luar blok itu.

Kalau penulis menyebut pekerjaan yang TIDAK ada di chat WhatsApp (mis. "tambahkan: perbaikan laptop Ilham"),
selain memasukkannya ke report, tulis juga setiap pekerjaan itu di blok [CATATAN] ... [/CATATAN] (satu blok per
pekerjaan, isi singkat seperti catatan manual). Aplikasi menyimpannya sebagai catatan manual supaya tetap ikut
saat report di-generate ulang. Jangan buat [CATATAN] untuk pekerjaan yang sudah ada di chat, item rutin, atau
yang sudah ada di daftar catatan manual. Jangan mengarang pekerjaan yang tidak ada di chat, catatan, atau
ucapan penulis.
Jangan pernah menulis password, OTP, PIN, atau nomor rekening."""

REPORT_RE = re.compile(r"\[REPORT\]\s*\n(.*?)\n\s*\[/REPORT\]", re.S)
NOTE_RE = re.compile(r"\[CATATAN\]\s*(.*?)\s*\[/CATATAN\]", re.S)
# Cadangan kalau Claude lupa penanda: judul "Daily Report" diikuti daftar bernomor.
LOOSE_RE = re.compile(r"^(Daily Report[^\n]*)\n+((?:(?:\d+\.|-)\s[^\n]*\n?|[ \t]+[^\n]*\n?)+)", re.M)


def context_text(draft, chats, day, start_hour, end_hour, name="", routine=(), notes=(), title=""):
    """Konteks tanggal yang sedang dibuka: draf report, item rutin, catatan manual, dan chat kerja."""
    parts = [f"Penulis report: {name or '-'}. Tanggal report: {day.isoformat()}."]
    if title:
        parts.append(f"Judul report (pakai persis): {title}")
    parts.append("Draf report saat ini:\n" + (draft.strip() or "(masih kosong)"))
    if routine:
        parts.append("Item rutin (pekerjaan harian tetap dari pengaturan, memang tidak ada di chat):\n"
                     + "\n".join(f"- {r}" for r in routine))
    notes = [n.strip() for n in notes if n.strip()]
    if notes:
        parts.append("Catatan manual dari penulis (pekerjaan di luar chat):\n"
                     + "\n".join(f"- {' '.join(redact(n).split())}" for n in notes))
    transcript = chat_transcript(chats or {}, day, start_hour, end_hour)
    if transcript:
        parts.append(f"Chat WhatsApp kerja tanggal itu (jam {start_hour:02d}:00-{end_hour:02d}:00):\n\n{transcript}")
    return "\n\n".join(parts)


def build_prompt(history, message, context=""):
    """history: [(peran, teks)] dengan peran "user"/"assistant"; message: pesan baru penulis."""
    out = []
    if context:
        out.append(f"<konteks>\n{context}\n</konteks>")
    if history:
        lines = [f"{'Penulis' if role == 'user' else 'Claude'}: {text}" for role, text in history]
        out.append("<percakapan_sebelumnya>\n" + "\n\n".join(lines) + "\n</percakapan_sebelumnya>")
    out.append(f"Pesan baru dari penulis:\n{message}")
    return "\n\n".join(out)


def extract_report(text):
    """Isi blok [REPORT]...[/REPORT] terakhir; kalau tidak ada, report tanpa penanda; atau None."""
    text = NOTE_RE.sub("", text or "")
    found = REPORT_RE.findall(text)
    if found:
        return found[-1].strip()
    loose = LOOSE_RE.findall(text)
    if loose:
        head, body = loose[-1]
        return f"{head.strip()}\n\n{body.strip()}"
    return None


def extract_notes(text):
    """Pekerjaan di luar chat dari blok [CATATAN]...[/CATATAN]."""
    return [" ".join(n.split()) for n in NOTE_RE.findall(text or "") if n.strip()]


def reply_only(text):
    """Penjelasan Claude saja, tanpa blok report dan catatan (report sudah tampil di draf)."""
    text = REPORT_RE.sub("", NOTE_RE.sub("", text or ""))
    loose = LOOSE_RE.search(text)
    if loose:
        text = text[:loose.start()] + text[loose.end():]
    return re.sub(r"\n{2,}", "\n", text).replace("**", "").strip()


def display_text(text):
    """Teks jawaban tanpa penanda [REPORT] dan tanpa blok [CATATAN]."""
    text = NOTE_RE.sub("", text or "")
    text = re.sub(r"^\s*\[/?REPORT\]\s*$\n?", "", text, flags=re.M)
    return re.sub(r"\n{3,}", "\n\n", text).replace("**", "").strip()


class Session:
    """Satu permintaan ke Claude yang bisa dihentikan di tengah jalan."""

    def __init__(self, cli):
        self.cli = cli
        self.proc = None
        self.stopped = False

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def ask(self, prompt, on_text, timeout=300):
        """Kirim prompt, panggil on_text(potongan) saat jawaban mengalir, kembalikan teks lengkap."""
        with tempfile.TemporaryDirectory(prefix="hrga-chat-") as cwd:
            self.proc = subprocess.Popen(
                [self.cli, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
                 "--model", "sonnet", "--tools", "", "--strict-mcp-config", "--no-session-persistence",
                 "--system-prompt", SYSTEM_PROMPT],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", cwd=cwd, creationflags=NO_WINDOW,
            )
            self.proc.stdin.write(prompt)
            self.proc.stdin.close()
            parts, final, error = [], None, None
            for line in self.proc.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if ev.get("type") == "stream_event":
                    delta = ev.get("event", {}).get("delta", {})
                    if delta.get("type") == "text_delta":
                        parts.append(delta["text"])
                        on_text(delta["text"])
                elif ev.get("type") == "result":
                    final = ev.get("result")
                    if ev.get("is_error"):
                        error = final or ev.get("subtype")
            err = self.proc.stderr.read()
            self.proc.wait(timeout=timeout)
        if self.stopped:
            return "".join(parts)
        text = final if final is not None else "".join(parts)
        if error or (self.proc.returncode and not text):
            raise RuntimeError(str(error or err or f"exit {self.proc.returncode}").strip()[:300])
        if "not logged in" in text.lower() or "/login" in text.lower():
            raise RuntimeError(text[:300])
        return text
