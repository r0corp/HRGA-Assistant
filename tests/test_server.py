import json
import os
import urllib.request
from datetime import date

import pytest

from core.client import Client, ServerError
from core.server import ReportServer

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "web")


@pytest.fixture
def srv(tmp_path):
    calls = []

    def tidy(cli, prompt, title):
        calls.append(prompt)
        return f"{title}\n\n1. Membersihkan ruang meeting lantai 2."

    def ask(cli, prompt):
        calls.append(prompt)
        return "Sudah diubah.\n[REPORT]\nDaily Report salah judul\n\n1. Membersihkan pantry.\n[/REPORT]"

    s = ReportServer(str(tmp_path), WEB, cli="fake", port=0, tidy_fn=tidy, ask_fn=ask).start()
    s.team.set_pin("sadam", "111111")
    s.team.set_pin("fena", "222222")
    s.calls = calls
    yield s
    s.stop()


def url(s):
    return f"http://127.0.0.1:{s.port}"


def test_android_flow_and_recap(srv):
    c = Client(url(srv))
    with pytest.raises(ServerError) as e:
        c.me()
    assert e.value.status == 401
    assert c.login("sadam", "111111")["name"] == "Sadam"

    res = c._call("POST", "/api/tidy", {"story": "tadi bersihin ruang meeting lt 2, password wifi abc123"})
    assert res["text"].startswith("Daily Report") and "(Sadam)." in res["text"]
    assert "Sadam" in srv.calls[-1]

    rev = c._call("POST", "/api/revise", {"text": res["text"], "instruction": "ganti jadi pantry"})
    assert rev["changed"] and "(Sadam)." in rev["text"].splitlines()[0] and "pantry" in rev["text"]

    # Anggota tidak boleh melihat Rekap Tim.
    with pytest.raises(ServerError) as e:
        c.team(date.today())
    assert e.value.status == 403
    c.submit(date.today(), rev["text"])
    assert c._call("GET", "/api/report")["sent_at"]

    fena = Client(url(srv))
    fena.login("Fena", "222222")
    rows = {r["id"]: r for r in fena.team(date.today())["rows"]}
    assert rows["sadam"]["sent_at"] and "pantry" in rows["sadam"]["text"]
    assert rows["ari"]["sent_at"] is None


def test_security(srv):
    c = Client(url(srv))
    # POST tanpa header X-HRGA ditolak.
    req = urllib.request.Request(url(srv) + "/api/login", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 403
    # Body terlalu besar.
    with pytest.raises(ServerError) as e2:
        c._call("POST", "/api/login", {"name": "x" * 70000, "pin": "1"})
    assert e2.value.status == 413
    with pytest.raises(ServerError):
        c.login("sadam", "999999")
    # Path di luar daftar file statis tidak bisa dibaca.
    for path in ("/../core/team.py", "/server/users.json", "/..%2f..%2fapp.py"):
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(url(srv) + path)


def test_static_and_headers(srv):
    with urllib.request.urlopen(url(srv) + "/") as r:
        assert r.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in r.headers["Content-Security-Policy"]
        assert b"<html" in r.read().lower()


def test_cookie_login(srv):
    req = urllib.request.Request(url(srv) + "/api/login", method="POST",
                                 data=json.dumps({"name": "sadam", "pin": "111111"}).encode(),
                                 headers={"X-HRGA": "1", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        cookie = r.headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Strict" in cookie
    me = urllib.request.Request(url(srv) + "/api/me", headers={"Cookie": cookie.split(";")[0]})
    with urllib.request.urlopen(me) as r:
        assert json.loads(r.read())["user"]["id"] == "sadam"


def test_generate_and_chat_for_laptop_without_claude(srv):
    srv.team.set_pin("winny", "333333")
    c = Client(url(srv))
    c.login("Winny", "333333")
    chats = {"TCI Fara": [{"time": f"{date.today().isoformat()}T09:00", "sender": "Fara", "out": False,
                           "text": "Win tolong terima paket vendor ATK di lobby ya"}]}
    text = c.generate(date.today(), chats, 6, 17, "id", ["Cek buku tamu"], ["Atur ruang meeting"], {"Fara": "mba"})
    assert "(Winny)." in text.splitlines()[0]
    prompt = srv.calls[-1]
    assert "paket vendor ATK" in prompt and "Cek buku tamu" in prompt and "Atur ruang meeting" in prompt
    reply = c.chat([("user", "halo"), ("assistant", "hai")], "poin 1 dari mana?", "konteks draf")
    assert "[REPORT]" in reply and "Penulis: halo" in srv.calls[-1] and "konteks draf" in srv.calls[-1]
    # Tanpa login ditolak.
    with pytest.raises(ServerError) as e:
        Client(url(srv)).chat([], "halo")
    assert e.value.status == 401


def test_supervisor_recap_admin_users(srv):
    srv.team.set_pin("rohman", "444444")
    fena = Client(url(srv))
    fena.login("Fena", "222222")
    assert fena.team(date.today())["rows"]
    # Supervisor tidak boleh kelola user.
    with pytest.raises(ServerError) as e:
        fena._call("GET", "/api/users")
    assert e.value.status == 403
    it = Client(url(srv))
    it.login("Rohman", "444444")
    users = {u["id"]: u for u in it._call("GET", "/api/users")["users"]}
    assert users["rohman"]["role"] == "admin" and users["fena"]["role"] == "supervisor"
    pin = it._call("POST", "/api/users", {"action": "pin", "id": "ari"})["pin"]
    assert Client(url(srv)).login("Ari", pin)["name"] == "Ari"
    with pytest.raises(ServerError) as e:
        it._call("POST", "/api/users", {"action": "update", "id": "rohman", "role": "member"})
    assert e.value.status == 400
