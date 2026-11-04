"""Cek dan pasang versi baru dari GitHub Releases."""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request


VERSION = "1.0.0"

# Rilis diambil dari repo ini; file .exe dilampirkan sebagai asset rilis.
REPO = "r0corp/hrga-wa-report"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


def parse_version(text):
    """ "v1.2.3" -> (1, 2, 3); bagian yang bukan angka dianggap 0."""
    parts = []
    for p in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple((parts + [0, 0, 0])[:3])


def is_newer(latest, current=VERSION):
    return parse_version(latest) > parse_version(current)


def check(timeout=10):
    """Rilis terbaru kalau lebih baru dari versi ini: {version, url, notes}, atau None."""
    req = urllib.request.Request(API_URL, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "hrga-wa-report",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)

    tag = data.get("tag_name", "")
    # Rilis berisi installer (…Setup….exe) dan .exe app; update memakai .exe app.
    exe = next((a for a in data.get("assets", [])
                if a["name"].lower().endswith(".exe") and "setup" not in a["name"].lower()), None)
    if not exe or not is_newer(tag):
        return None
    return {"version": tag.lstrip("vV"), "url": exe["browser_download_url"], "notes": data.get("body") or ""}


def download(url, progress=None):
    """Unduh .exe baru ke folder sementara, kembalikan path-nya."""
    dest = os.path.join(tempfile.gettempdir(), "HRGA WA Report.new.exe")
    req = urllib.request.Request(url, headers={"User-Agent": "hrga-wa-report"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done * 100 // total)
    return dest


def can_self_update():
    return getattr(sys, "frozen", False)


def install(new_exe):
    """Ganti .exe yang sedang berjalan setelah app ditutup, lalu buka lagi.

    File .exe yang sedang berjalan tidak bisa ditimpa, jadi penggantian
    dilakukan oleh script .bat kecil yang menunggu proses ini selesai.
    """
    target = sys.executable
    bat = os.path.join(tempfile.gettempdir(), "hrga-wa-report-update.bat")
    with open(bat, "w", encoding="mbcs") as f:
        f.write(f"""@echo off
:wait
tasklist /fi "PID eq {os.getpid()}" | find "{os.getpid()}" >nul && (timeout /t 1 /nobreak >nul & goto wait)
move /y "{new_exe}" "{target}" >nul
start "" "{target}"
del "%~f0"
""")
    subprocess.Popen(["cmd", "/c", bat], creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS)
