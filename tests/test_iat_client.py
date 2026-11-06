"""Klien App HRGA: alamat kantor dicoba dulu, lalu internet; profil report dari server diterapkan."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from core import client


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.headers.get("X-HRGA-Token") == "tok"
        body = json.dumps({"ok": ok, "username": "fara", "display_name": "Fara", "language": "id",
                           "profile": {"style": "list", "example": "", "routine": ["Cek kendaraan"]}}
                          if ok else {"ok": False, "error": "Token tidak valid"}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        ok = self.path == "/api/agent/login" and data.get("password") == "rahasia"
        body = json.dumps({"ok": True, "token": "tok", "username": data.get("username"), "display_name": "Fara",
                           "language": "id", "profile": {"style": "list", "example": "", "routine": []}}
                          if ok else {"ok": False, "error": "Username atau password salah"}).encode()
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_falls_back_from_unreachable_lan_to_internet():
    srv, url = _server()
    try:
        c = client.IatClient(url, "tok", timeout=5, lan_url="http://127.0.0.1:9")   # port 9: tidak ada server
        me = c.me()
        assert me["username"] == "fara" and c.url == url
    finally:
        srv.shutdown()


def test_lan_used_first_and_bad_token_is_not_retried_elsewhere():
    srv, url = _server()
    try:
        c = client.IatClient("http://127.0.0.1:9", "salah", timeout=5, lan_url=url)
        try:
            c.me()
            raise AssertionError("seharusnya ditolak")
        except client.ServerError as e:
            assert e.status == 401 and c.url == url
    finally:
        srv.shutdown()


def test_login_with_password_gets_token_then_me_works():
    srv, url = _server()
    try:
        c = client.IatClient(url, "", timeout=5)
        try:
            c.login("fara", "salah")
            raise AssertionError("password salah seharusnya ditolak")
        except client.ServerError as e:
            assert e.status == 401 and "salah" in str(e)
        data = c.login("fara", "rahasia", "HRGA Asisten - Fara")
        assert data["token"] == "tok" and c.token == "tok"
        assert c.me()["username"] == "fara"          # token hasil login langsung dipakai
    finally:
        srv.shutdown()
