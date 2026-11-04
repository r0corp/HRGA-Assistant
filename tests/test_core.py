from datetime import date

from app import to_wa_number
from core.reader import is_self_chat
from core.summary import build_report, is_meaningful, report_title


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


def test_report_dikelompokkan_per_jenis_pekerjaan():
    chats = {
        "TCI Rama": [
            msg("08:30", "masih ada issue di sharepointnya?", out=True),
            msg("08:41", "aman mas, udh gada notif storage full", sender="TCI Rama"),
        ],
        "TCI Deden": [
            msg("08:42", "ada issue lagi kah untuk sharepointnya?", out=True),
            msg("09:06", "sejauh ini sih aman mas", sender="TCI Deden"),
        ],
        "TCI Annisa": [
            msg("10:48", "mas printer kyoceranya bermasalah lagi", sender="TCI Annisa"),
            msg("10:56", "itu kaya error kertas habis", out=True),
        ],
    }
    lines = build_report(chats, DAY, "Sari", 6, 17).splitlines()

    assert lines[2] == "1. Penanganan storage SharePoint/OneDrive:"
    assert lines[3].startswith("- Rama: ") and lines[3].endswith("; selesai.")
    assert lines[4].startswith("- Deden: ") and lines[4].endswith("; selesai.")
    assert lines[5].startswith("2. Penanganan printer dan scan (Annisa): mas printer kyoceranya bermasalah lagi")


def test_report_hanya_jam_kerja():
    chats = {
        "Andi": [
            msg("05:30", "printer sebelum jam kerja jangan dihitung"),
            msg("08:15", "form pengajuan ATK minggu ini sudah saya kirim"),
            msg("17:30", "printer setelah jam kerja jangan dihitung juga"),
        ],
    }
    text = build_report(chats, DAY, "Sari", 6, 17)
    assert "jangan dihitung" not in text
    assert "(Andi): form pengajuan ATK minggu ini sudah saya kirim" in text


def test_chat_pribadi_dan_ucapan_duka_dibuang():
    chats = {
        "Keluarga": [msg("12:00", "nanti malam makan di rumah ya", sender="Ibu")],
        "TCI Tarisa": [msg("07:10", "innalillahi turut berduka cita ya mas", sender="TCI Tarisa")],
    }
    assert "Tidak ada chat kerja" in build_report(chats, DAY)


def test_item_rutin_diselipkan():
    routine = ["Cek rutin APAR lantai 1 dan 2."]
    chats = {"Andi": [msg("08:15", "form pengajuan ATK minggu ini sudah saya kirim")]}
    text = build_report(chats, DAY, routine=routine)
    assert "Cek rutin APAR lantai 1 dan 2." in text
    # Posisi acaknya tetap sama untuk tanggal yang sama.
    assert text == build_report(chats, DAY, routine=routine)


def test_password_disamarkan():
    chats = {"Rina": [msg("09:00", "password wifi tamu: Tamu2026xyz tolong dicek")]}
    assert "Tamu2026xyz" not in build_report(chats, DAY)


def test_link_diringkas_jadi_nama_situs():
    chats = {"Rina": [msg("09:00", "mba ini link kabel untuk pengajuan https://www.shopee.co.id/CORDE-i.3677?x=1 ya")]}
    assert "[link shopee.co.id]" in build_report(chats, DAY)


def test_report_kosong():
    assert "Tidak ada chat kerja" in build_report({}, DAY)


def test_report_bahasa_inggris():
    chats = {"Andi": [msg("08:15", "form pengajuan ATK sudah saya kirim")]}
    lines = build_report(chats, DAY, "Sari", lang="en").splitlines()
    assert lines[0] == "Daily Report Wednesday/04 November 2026 (Sari)."
    assert lines[2].startswith("1. Stationery and stock management (Andi): ")
    assert "No work chats" in build_report({}, DAY, lang="en")


def test_format_tanggal_report():
    from app import fmt_day, parse_day
    assert fmt_day(date(2026, 11, 3), "id") == "Selasa / 03-11-2026"
    assert parse_day("Selasa / 03-11-2026") == date(2026, 11, 3)
    assert parse_day("2026-11-03") == date(2026, 11, 3)
    assert parse_day("kemarin") is None


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


def test_prompt_claude_hanya_chat_jam_kerja_dan_tersamarkan():
    from core.claude_ai import build_prompt
    chats = {
        "TCI Budi": [
            msg("05:00", "sebelum jam kerja jangan masuk"),
            msg("08:10", "password wifi: Rahasia2026x tolong cek printer", sender="TCI Budi"),
            msg("08:20", "sudah saya cek, printer normal", out=True),
            msg("08:21", "Photo", sender="TCI Budi"),
            msg("08:22", "turut berduka cita ya", sender="TCI Budi"),
        ],
    }
    p = build_prompt(chats, DAY, "Sari", 6, 17, "id", ["Cek rutin APAR."])
    assert "Daily Report Rabu/04 November 2026 (Sari)." in p
    assert "[08:20] Saya: sudah saya cek, printer normal" in p
    assert "Rahasia2026x" not in p
    assert "sebelum jam kerja" not in p and "Photo" not in p and "berduka" not in p
    assert "Cek rutin APAR." in p


def test_jawaban_claude_dirapikan():
    from core.claude_ai import tidy
    title = "Daily Report Rabu/04 November 2026 (Sari)."
    raw = "Berikut report-nya:\n\n**Daily Report Rabu/4 Nov 2026**\n\n1. **Penanganan printer**: normal."
    assert tidy(raw, title) == title + "\n\n1. Penanganan printer: normal."


def test_catatan_manual_masuk_report():
    chats = {"Andi": [msg("08:15", "form pengajuan ATK minggu ini sudah saya kirim")]}
    text = build_report(chats, DAY, manual=["Ganti lampu ruang meeting lantai 2\nsudah menyala normal"])
    assert "Ganti lampu ruang meeting lantai 2" in text
    assert "- sudah menyala normal" in text


def test_catatan_manual_ada_di_prompt_claude():
    from core.claude_ai import build_prompt
    p = build_prompt({}, DAY, "Sari", manual=["Ganti lampu ruang meeting lantai 2"])
    assert "Catatan manual" in p and "- Ganti lampu ruang meeting lantai 2" in p


def test_deepl_rebuild_keeps_layout_and_honorifics():
    from datetime import date
    from core import deepl
    src = "Daily Report Rabu/04 November 2026 (Budi).\n1. Perbaikan laptop pak Andi.\n   - Sudah normal.\n\n2. Cek email mba Sari."
    lines = [l.strip() for l in src.splitlines() if l.strip() and not deepl.TITLE_RE.match(l)]
    out = "1. Repaired Mr. Andi\u2019s laptop.\n\n- It\u2019s working normally.\n\n2. Checked Ms. Sari\u2019s email."
    got = deepl.rebuild(src, deepl.align(lines, out), deepl.english_title(date(2026, 11, 4), "Budi"))
    got = deepl.fix_honorifics(src, got)
    assert got.splitlines() == [
        "Daily Report Rabu/04 November 2026 (Budi).",
        "",
        "1. Repaired pak Andi's laptop.",
        "   - It's working normally.",
        "2. Checked mba Sari's email.",
    ]


def test_deepl_chunks_respect_limit():
    from core import deepl
    parts = deepl.chunks(["a" * 600, "b" * 600, "c" * 600], limit=1300)
    assert [len(p) for p in parts] == [2, 1]


def test_tidy_removes_blank_lines_between_items():
    from core.claude_ai import tidy
    raw = "Daily Report X.\n\n1. Satu.\n\n- detail\n\n2. Dua.\n\n\n3. Tiga."
    assert tidy(raw, "Daily Report Rabu/04 November 2026 (Budi).") == (
        "Daily Report Rabu/04 November 2026 (Budi).\n\n1. Satu.\n- detail\n2. Dua.\n3. Tiga.")


def test_nicknames_parse_and_apply():
    from core.summary import parse_nicknames, with_nickname
    nick = parse_nicknames("Juproni = pak\nSaefudin = pak Udin\nrusak tanpa sama dengan\n")
    assert nick == {"Juproni": "pak", "Saefudin": "pak Udin"}
    assert with_nickname("Juproni", nick) == "pak Juproni"
    assert with_nickname("Saefudin", nick) == "pak Udin"
    assert with_nickname("Annisa Porta", nick) == "Annisa Porta"


def test_prompt_contains_nicknames_and_rules():
    from core.claude_ai import build_prompt
    p = build_prompt({}, DAY, "Sari", nicknames={"Juproni": "pak", "Saefudin": "pak Udin"})
    assert "Juproni: pak Juproni" in p and "Saefudin: pak Udin" in p
    assert "pembelian barang" in p


def test_chat_prompt_and_report_block():
    from core import chat
    ctx = chat.context_text("Daily Report X.\n\n1. Tes", {"TCI Andi": [msg("09:00", "printer lantai 2 macet tolong cek")]},
                            DAY, 6, 17, "Rohman")
    assert "printer lantai 2" in ctx and "1. Tes" in ctx
    prompt = chat.build_prompt([("user", "halo"), ("assistant", "hai")], "poin 1 dari mana?", ctx)
    assert "Penulis: halo" in prompt and "Claude: hai" in prompt and prompt.endswith("poin 1 dari mana?")
    reply = "Sudah saya hapus.\n[REPORT]\nDaily Report X.\n\n1. A\n[/REPORT]\nSilakan cek."
    assert chat.extract_report(reply) == "Daily Report X.\n\n1. A"
    assert "[REPORT]" not in chat.display_text(reply)
    assert chat.extract_report("tanpa blok") is None
