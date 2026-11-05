import time
from datetime import date

import pytest

from core import team as T

DAY = date(2026, 11, 5)


def test_seed_and_pin(tmp_path):
    t = T.Team(str(tmp_path))
    names = [u["name"] for u in t.list_users()]
    assert names[:2] == ["Fena", "Rohman"] and "Taufik" in names and len(names) == 9
    assert t.public("fena")["role"] == "supervisor" and t.public("rohman")["role"] == "admin" and t.public("ari")["device"] == "android"
    # Belum ada PIN: tidak bisa login.
    with pytest.raises(T.AuthError):
        t.login("Ari", "123456")
    t.set_pin("ari", "123456")
    assert "123456" not in open(t.users_file, encoding="utf-8").read()
    token, uid = t.login("ari", "123456", "HP Ari")
    assert uid == "ari" and t.session_user(token) == "ari"
    # Data tetap ada setelah dibuka ulang.
    assert T.Team(str(tmp_path)).session_user(token) == "ari"


def test_pin_format_and_lockout(tmp_path):
    t = T.Team(str(tmp_path))
    with pytest.raises(ValueError):
        t.set_pin("ari", "12ab")
    t.set_pin("ari", "654321")
    for _ in range(4):
        with pytest.raises(T.AuthError, match="salah"):
            t.login("Ari", "000000")
    with pytest.raises(T.AuthError, match="terkunci"):
        t.login("Ari", "000000")
    # PIN benar pun ditolak selama terkunci.
    with pytest.raises(T.AuthError, match="terkunci"):
        t.login("Ari", "654321")
    t.users["ari"]["locked_until"] = time.time() - 1
    assert t.login("Ari", "654321")[1] == "ari"


def test_sessions_revoke_and_expire(tmp_path):
    t = T.Team(str(tmp_path))
    t.set_pin("roni", "111111")
    a, _ = t.login("Roni", "111111")
    b, _ = t.login("Roni", "111111")
    assert t.session_count("roni") == 2
    t.logout(a)
    assert t.session_user(a) is None and t.session_user(b) == "roni"
    # Reset PIN mencabut semua sesi.
    t.set_pin("roni", "222222")
    assert t.session_user(b) is None
    c, _ = t.login("Roni", "222222")
    t.sessions[T._token_hash(c)]["seen"] -= T.SESSION_IDLE + 1
    assert t.session_user(c) is None
    assert t.session_user("palsu") is None


def test_reports_and_recap(tmp_path):
    t = T.Team(str(tmp_path))
    t.save_report(DAY, "sadam", "Daily Report X (Sadam).\n\n1. Bersih", story="tadi bersih")
    rows = {r["id"]: r for r in t.recap(DAY)}
    assert rows["sadam"]["sent_at"] is None and rows["sadam"]["text"] == ""  # draf belum dikirim
    t.save_report(DAY, "sadam", "Daily Report X (Sadam).\n\n1. Bersih lantai 2", submit=True)
    t.save_report(DAY, "fara", "Daily Report X (Fara).\n\n1. Admin", source="laptop", submit=True)
    rows = {r["id"]: r for r in t.recap(DAY)}
    assert rows["sadam"]["sent_at"] and rows["fara"]["source"] == "laptop"
    assert t.get_report(DAY, "sadam")["story"] == "tadi bersih"
    text = T.recap_text(t.recap(DAY), DAY)
    assert "Bersih lantai 2" in text and "Belum report" in text and "Sadam," not in text


def test_add_remove_user(tmp_path):
    t = T.Team(str(tmp_path))
    uid = t.add_user("Budi Santoso", "Driver", "member", "android")
    assert uid == "budi-santoso" and t.find("budi santoso") == uid
    with pytest.raises(ValueError):
        t.add_user("Budi Santoso")
    t.remove_user(uid)
    assert t.find("Budi Santoso") is None


def test_roles_keep_one_admin(tmp_path):
    t = T.Team(str(tmp_path))
    with pytest.raises(ValueError, match="Administrator"):
        t.update_user("rohman", role="member")
    with pytest.raises(ValueError, match="Administrator"):
        t.remove_user("rohman")
    with pytest.raises(ValueError):
        t.update_user("ari", role="bos")
    t.update_user("fena", role="admin")
    t.update_user("rohman", role="member")
    assert t.public("rohman")["role"] == "member"
