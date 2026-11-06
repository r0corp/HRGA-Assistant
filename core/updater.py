"""Cek dan pasang versi baru dari GitHub Releases."""

import json
import logging
import os
import subprocess
import sys
import tempfile
import urllib.request


VERSION = "1.3.1"

# Rilis diambil dari repo ini; file .exe dilampirkan sebagai asset rilis.
REPO = "r0corp/hrga-wa-report"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

NEW_EXE = os.path.join(tempfile.gettempdir(), "HRGA WA Report.new.exe")
BAT = os.path.join(tempfile.gettempdir(), "hrga-wa-report-update.bat")
CREATE_BREAKAWAY_FROM_JOB = 0x01000000

log = logging.getLogger(__name__)


def parse_version(text):
    """ "v1.2.3" -> (1, 2, 3); bagian yang bukan angka dianggap 0."""
    parts = []
    for p in text.strip().lstrip("vV").split("."):
        digits = "".join(c for c in p if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple((parts + [0, 0, 0])[:3])


def is_newer(latest, current=None):
    return parse_version(latest) > parse_version(current or VERSION)


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
    dest = NEW_EXE
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


def cleanup():
    """Hapus sisa file update lama di folder sementara (dipanggil saat app dibuka)."""
    for path in (NEW_EXE, BAT):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass


def bat_script(new_exe, target, pids):
    """Script yang menunggu app tertutup, mengganti .exe, membuka app lagi, lalu bersih-bersih."""
    waits = "\n".join(
        f'tasklist /nh /fi "PID eq {p}" | find " {p} " >nul && (timeout /t 1 /nobreak >nul & goto wait)'
        for p in pids)
    return f"""@echo off
set tries=0
:wait
{waits}
:move
move /y "{new_exe}" "{target}" >nul 2>&1 && goto moved
set /a tries+=1
if %tries% geq 30 goto moved
timeout /t 1 /nobreak >nul
goto move
:moved
if exist "{new_exe}" del /f /q "{new_exe}"
start "" "{target}"
del "%~f0"
"""


def _spawn_outside_job(cmd):
    """Jalankan perintah yang tetap hidup walau app keluar.

    App versi onefile berjalan di dalam Job object PyInstaller, sehingga proses anak
    ikut dimatikan saat app tertutup. Coba lepas dari job; kalau tidak diizinkan,
    minta WMI yang membuat prosesnya (proses WMI berada di luar job).
    """
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    # Variabel _PYI_* milik app lama tidak boleh terwarisi: app baru akan mencari DLL
    # di folder sementara app lama yang sudah dihapus ("Failed to load Python DLL").
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("_PYI", "_MEIPASS"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    try:
        subprocess.Popen(cmd, creationflags=flags | CREATE_BREAKAWAY_FROM_JOB, close_fds=True, env=env)
        return "breakaway"
    except OSError as e:
        log.info("Breakaway dari job ditolak (%s), pakai WMI.", e)
    line = subprocess.list2cmdline(cmd).replace("'", "''")
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create "
          f"-Arguments @{{CommandLine='{line}'}}; exit $r.ReturnValue")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   creationflags=subprocess.CREATE_NO_WINDOW, check=True, timeout=60)
    return "wmi"


def install(new_exe):
    """Ganti .exe yang sedang berjalan setelah app ditutup, lalu buka lagi.

    File .exe yang sedang berjalan tidak bisa ditimpa, jadi penggantian dilakukan oleh
    script .bat kecil yang menunggu proses app (dan proses induk onefile-nya) selesai.
    File unduhan dihapus setelah dipakai.
    """
    target = sys.executable
    with open(BAT, "w", encoding="mbcs") as f:
        f.write(bat_script(new_exe, target, (os.getpid(), os.getppid())))
    how = _spawn_outside_job(["cmd", "/c", BAT])
    log.info("Script update dijalankan (%s): %s -> %s", how, new_exe, target)
