"""Pengaturan dan lokasi data app, disimpan per user Windows."""

import json
import os


APP_NAME = "HRGA WA Report"

# Data tiap laptop disimpan di %LOCALAPPDATA%, bukan di folder .exe.
# HRGA_WA_DATA bisa dipakai untuk menunjuk folder lain (mis. saat uji coba).
DATA_DIR = os.environ.get("HRGA_WA_DATA") or os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), APP_NAME
)
PROFILE_DIR = os.environ.get("HRGA_WA_PROFILE") or os.path.join(DATA_DIR, "wa-profile")
RAW_DIR = os.path.join(DATA_DIR, "chat")
REPORTS_DIR = os.path.join(DATA_DIR, "report")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "app.log")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
NOTES_DIR = os.path.join(DATA_DIR, "notes")

# Report hanya dikirim ke grup ini; sengaja tidak bisa diubah dari app.
REPORT_GROUP = "GRUP TEAM HRGA"

DEFAULTS = {
    "name": "",
    "phone": "",
    "start_hour": 6,
    "end_hour": 17,
    "lang": "id",
    # Pekerjaan rutin harian yang selalu masuk report, diselipkan di nomor acak.
    "routine": [],
    # Nama chat yang tidak pernah dibaca, mis. chat keluarga.
    "exclude": [],
}


def ensure_dirs():
    for d in (DATA_DIR, RAW_DIR, REPORTS_DIR, NOTES_DIR):
        os.makedirs(d, exist_ok=True)


def load():
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data.update(json.load(f))
    except (OSError, ValueError):
        pass
    data["group"] = REPORT_GROUP
    return data


def save(data):
    ensure_dirs()
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
