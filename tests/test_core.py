from datetime import date

from app import to_wa_number
from core.reader import is_self_chat
from core.summary import build_report, is_meaningful, key_messages, report_title


DAY = date(2026, 11, 4)


def msg(hhmm, text, out=False, sender="Andi", day="2026-11-04"):
    return {"time": f"{day}T{hhmm}", "sender": sender, "out": out, "text": text}


def test_judul_pakai_hari_dan_bulan_indonesia():
    assert report_title(DAY, "Sari") == "Daily Report Rabu/04 November 2026 (Sari)."
    assert report_title(DAY, "") == "Daily Report Rabu/04 November 2026."


def test_basa_basi_dan_lampiran_dibuang():
    for t in ["ok", "Oke siap pak", "makasih ya", "Photo", "3 photos", "wkwkwk", "👍👍", "iya mba"]:
        assert not is_meaningful(t), t
    assert is_meaningful("tolong cek printer lantai 2 tidak bisa print")


def test_pesan_kunci_permintaan_dan_jawaban():
    msgs = [
        msg("08:00", "pagi pak"),
        msg("08:01", "printer lantai 2 error kertas macet terus"),
        msg("08:05", "ok", out=True),
        msg("08:30", "sudah saya bersihkan rollernya dan sudah bisa print", out=True),
        msg("08:31", "makasih"),
    ]
    picked = key_messages(msgs)
    assert [m["time"][11:] for m in picked] == ["08:01", "08:30"]


def test_report_hanya_jam_kerja_dan_urut_pagi():
    chats = {
        "Grup HRGA": [msg("10:00", "rapat evaluasi vendor kebersihan jam 2 siang", sender="Rina")],
        "Andi": [
            msg("05:30", "ini sebelum jam kerja jangan dihitung"),
            msg("08:15", "form pengajuan ATK minggu ini sudah saya kirim"),
            msg("17:30", "ini setelah jam kerja jangan dihitung juga"),
        ],
        "Keluarga": [msg("18:00", "nanti malam makan di luar ya", sender="Ibu")],
    }
    text = build_report(chats, DAY, "Sari", 6, 17)
    lines = text.splitlines()

    assert lines[0] == "Daily Report Rabu/04 November 2026 (Sari)."
    assert lines[2] == "1. Andi (08:15):"
    assert lines[3] == "- Andi: form pengajuan ATK minggu ini sudah saya kirim"
    assert lines[4] == "2. Grup HRGA (10:00):"
    assert "jangan dihitung" not in text
    assert "Keluarga" not in text


def test_password_disamarkan():
    chats = {"Rina": [msg("09:00", "password wifi tamu: Tamu2026xyz tolong dicek")]}
    assert "Tamu2026xyz" not in build_report(chats, DAY)


def test_link_diringkas_jadi_nama_situs():
    chats = {"Rina": [msg("09:00", "ini link kabelnya https://www.shopee.co.id/CORDE-i.3677.a1b2c3?x=1%20y mba", out=True)]}
    text = build_report(chats, DAY)
    assert "- Saya: ini link kabelnya [link shopee.co.id] mba" in text


def test_report_kosong():
    assert "Tidak ada chat kerja" in build_report({}, DAY)


def test_report_bahasa_inggris():
    chats = {"Andi": [msg("08:15", "sudah saya kirim form pengajuan ATK", out=True)]}
    lines = build_report(chats, DAY, "Sari", lang="en").splitlines()
    assert lines[0] == "Daily Report Wednesday/04 November 2026 (Sari)."
    assert lines[3] == "- Me: sudah saya kirim form pengajuan ATK"
    assert "No work chats" in build_report({}, DAY, lang="en")


def test_pdf_dengan_kop(tmp_path):
    from app import asset
    from core.pdf import save_pdf

    text = build_report({"Andi": [msg("08:15", "form pengajuan ATK minggu ini sudah saya kirim")]}, DAY, "Sari")
    path = save_pdf(text, str(tmp_path / "r.pdf"), asset("logo-wide.png"))
    data = open(path, "rb").read()
    assert data.startswith(b"%PDF") and b"/Image" in data


def test_chat_diri_sendiri_dilewati():
    assert is_self_chat("+62 812-3456-7890 (You)", "")
    assert is_self_chat("+62 812-3456-7890", "081234567890")
    assert not is_self_chat("TCI Budi", "081234567890")


def test_nomor_wa():
    assert to_wa_number("0812-3456-7890") == "6281234567890"
    assert to_wa_number("+62 812 3456 7890") == "6281234567890"


def test_tanggal_dari_judul_report():
    from core.history import report_date
    assert report_date("Daily Report Selasa/03 November 2026 (Demo).\n\n1. ...") == date(2026, 11, 3)
    assert report_date("Daily Report Wednesday/04 November 2026 (Sari).") == date(2026, 11, 4)
    assert report_date("Daily Report Kamis/29 October 2026 (Demo).") == date(2026, 10, 29)
    assert report_date("ok siap") is None


def test_lima_hari_kerja_lewati_weekend():
    from core.history import workdays
    assert workdays(date(2026, 11, 4)) == [
        date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2), date(2026, 11, 3), date(2026, 11, 4)]


def test_riwayat_hanya_pesan_sendiri():
    from core.history import from_messages
    msgs = [
        msg("17:05", "Daily Report Selasa/03 November 2026 (Demo).\n1. ...", out=True, day="2026-11-03"),
        msg("17:10", "Daily Report Selasa/03 November 2026 (Sari).", out=False, day="2026-11-03"),
        msg("08:00", "Daily Report Jumat/30 Oktober 2026 (Demo).", out=True, day="2026-11-02"),
    ]
    assert from_messages(msgs) == {"2026-11-03": "2026-11-03T17:05", "2026-10-30": "2026-11-02T08:00"}


def test_versi_update():
    from core.updater import is_newer, parse_version
    assert parse_version("v1.2.10") == (1, 2, 10)
    assert is_newer("v1.0.1", "1.0.0") and not is_newer("v1.0.0", "1.0.0")


def test_grup_report_selalu_grup_team_hrga(tmp_path, monkeypatch):
    import json as _json
    from core import settings
    f = tmp_path / "settings.json"
    f.write_text(_json.dumps({"group": "Grup Lain"}), encoding="utf-8")
    monkeypatch.setattr(settings, "SETTINGS_FILE", str(f))
    assert settings.load()["group"] == "GRUP TEAM HRGA"
