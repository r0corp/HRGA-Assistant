"""Lampiran tanpa teks (foto, dokumen, suara) ikut terbaca, dan label tanggal bahasa Indonesia dikenali."""

from datetime import date

from core.parse import label_to_date
from core.reader import build_messages

TODAY = date(2026, 11, 6)   # Jumat


def test_indonesian_labels():
    assert label_to_date("Kemarin", TODAY) == date(2026, 11, 5)
    assert label_to_date("Rabu", TODAY) == date(2026, 11, 4)
    assert label_to_date("Senin", TODAY) == date(2026, 11, 2)
    assert label_to_date("HARI INI", TODAY) == TODAY
    assert label_to_date("TODAY", TODAY) == TODAY
    assert label_to_date("Yesterday", TODAY) == date(2026, 11, 5)
    assert label_to_date("15.28", TODAY) == TODAY


def test_media_messages_get_date_time_and_sender():
    raw = [
        {"pre": "[09:10, 05/11/2026] Ari: ", "text": "kemarin", "out": False, "sep": "Kemarin"},
        {"pre": "", "media": "foto", "name": "", "time": "08:05", "out": False, "sep": "HARI INI"},
        {"pre": "[08:06, 06/11/2026] Ari: ", "text": "AC lantai 2 sudah dibersihkan", "out": False, "sep": "HARI INI"},
        {"pre": "", "media": "dokumen", "name": "Invoice AC.pdf", "time": "08:30", "out": True, "sep": "HARI INI"},
        {"pre": "", "media": "suara", "name": "", "time": "9:15 AM", "out": False, "sep": "HARI INI"},
    ]
    msgs = build_messages(raw, TODAY, "DMY", today=TODAY)
    assert [m["text"] for m in msgs] == ["[Foto]", "AC lantai 2 sudah dibersihkan", "[Dokumen: Invoice AC.pdf]", "[Pesan suara]"]
    assert msgs[0]["time"] == "2026-11-06T08:05" and msgs[0]["sender"] == "Ari"     # pengirim dari pesan teks sebelumnya
    assert msgs[3]["time"] == "2026-11-06T09:15"
    assert msgs[2]["out"] is True


def test_media_without_separator_uses_previous_text_date():
    raw = [
        {"pre": "[10:00, 06/11/2026] Topik: ", "text": "timbang besi", "out": False, "sep": ""},
        {"pre": "", "media": "foto", "name": "", "time": "10:01", "out": False, "sep": ""},
    ]
    msgs = build_messages(raw, TODAY, "DMY", today=TODAY)
    assert msgs[-1]["text"] == "[Foto]" and msgs[-1]["time"] == "2026-11-06T10:01"


def test_phone_numbers_kept_but_secrets_masked():
    from core.redact import redact
    assert redact("hubungi 081234567890 ya") == "hubungi 081234567890 ya"
    assert redact("wa 6281234567890") == "wa 6281234567890"
    assert "[disamarkan]" in redact("rek BCA 1234567890")
    assert redact("otp 123456") == "otp [disamarkan]"


def test_whole_day_by_default():
    from core import settings
    from core.summary import in_window
    assert (settings.DEFAULTS["start_hour"], settings.DEFAULTS["end_hour"]) == (0, 24)
    assert in_window({"time": "2026-11-06T23:40"}, date(2026, 11, 6), 0, 24)
    assert in_window({"time": "2026-11-06T00:15"}, date(2026, 11, 6), 0, 24)
