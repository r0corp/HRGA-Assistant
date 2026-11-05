"""Server web HRGA Report di PC server.

Melayani halaman web untuk HP (tim Android dan Fena) dan API untuk app laptop.
Hanya mendengarkan di 127.0.0.1; akses dari luar lewat Tailscale Funnel (HTTPS).
"""

import json
import logging
import mimetypes
import os
import threading
import time
from datetime import date, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from core import chat, claude_ai
from core.redact import redact
from core.summary import report_title
from core.team import RECAP_ROLES, AuthError, Team, parse_day, recap_text

log = logging.getLogger("server")

PORT = 8500
COOKIE = "hrga_session"
MAX_BODY = 64 * 1024
# Generate dan Chat dari laptop membawa isi chat WhatsApp sehari, jadi batasnya lebih besar.
MAX_BIG_BODY = 2 * 1024 * 1024
# Batas percobaan login gagal per alamat IP (selain kunci per akun).
IP_MAX_FAILS = 20
IP_WINDOW = 15 * 60
STATIC = {
    "/": "index.html",
    "/app.js": "app.js",
    "/style.css": "style.css",
    "/manifest.webmanifest": "manifest.webmanifest",
    "/icon.png": "../icon.png",
    "/logo.png": "../logo-wide.png",
}
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                               "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "Strict-Transport-Security": "max-age=31536000",
}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _default_tidy(cli, prompt, title):
    return claude_ai.generate(cli, prompt, title)


def _default_ask(cli, prompt):
    return chat.Session(cli).ask(prompt, lambda _part: None)


class ReportServer:
    def __init__(self, data_root, web_dir, cli=None, lang="id", port=PORT, host="127.0.0.1",
                 tidy_fn=None, ask_fn=None):
        self.team = Team(data_root)
        self.web_dir = web_dir
        self.cli = cli
        self.lang = lang
        self.port = port
        self.host = host
        self.tidy_fn = tidy_fn or _default_tidy
        self.ask_fn = ask_fn or _default_ask
        self.claude_slots = threading.Semaphore(2)
        self.ip_fails = {}
        self.httpd = None

    # ---------- jalankan ----------

    def start(self):
        handler = type("Handler", (_Handler,), {"app": self})
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        log.info("Server HRGA berjalan di http://%s:%d", self.host, self.port)
        return self

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

    @property
    def running(self):
        return self.httpd is not None

    # ---------- bantuan ----------

    def ip_blocked(self, ip):
        now = time.time()
        fails = [t for t in self.ip_fails.get(ip, []) if now - t < IP_WINDOW]
        self.ip_fails[ip] = fails
        return len(fails) >= IP_MAX_FAILS

    def ip_failed(self, ip):
        self.ip_fails.setdefault(ip, []).append(time.time())

    def claude(self, fn, *args):
        if not self.cli:
            raise HttpError(503, "Claude belum siap di PC server")
        if not self.claude_slots.acquire(timeout=120):
            raise HttpError(503, "Claude sedang sibuk, coba lagi sebentar")
        try:
            return fn(self.cli, *args)
        except HttpError:
            raise
        except Exception as e:
            log.warning("Claude gagal: %s", e)
            raise HttpError(502, "Claude gagal menyusun report, coba lagi")
        finally:
            self.claude_slots.release()

    def title(self, day, uid):
        return report_title(day, self.team.users[uid]["name"], self.lang)


class _Handler(BaseHTTPRequestHandler):
    app = None  # diisi ReportServer.start()
    server_version = "HRGA"
    sys_version = ""

    def log_message(self, fmt, *args):
        log.debug("%s %s", self.client_ip(), fmt % args)

    # ---------- request ----------

    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        return jar[COOKIE].value if COOKIE in jar else None

    def body(self, limit=MAX_BODY):
        length = int(self.headers.get("Content-Length") or 0)
        if length > limit:
            raise HttpError(413, "Data terlalu besar")
        raw = self.rfile.read(length) if length else b"{}"
        self._body_done = True
        try:
            data = json.loads(raw.decode("utf-8"))
        except ValueError:
            raise HttpError(400, "Format data salah")
        if not isinstance(data, dict):
            raise HttpError(400, "Format data salah")
        return data

    def user(self, admin=False, recap=False):
        uid = self.app.team.session_user(self.token())
        if not uid:
            raise HttpError(401, "Silakan login dulu")
        role = self.app.team.users[uid]["role"]
        if admin and role != "admin":
            raise HttpError(403, "Hanya untuk Administrator (IT Support)")
        if recap and role not in RECAP_ROLES:
            raise HttpError(403, "Hanya untuk Supervisor dan Administrator")
        return uid

    def day(self, value, uid):
        d = parse_day(value) if value else date.today()
        if d is None:
            raise HttpError(400, "Tanggal salah")
        # Anggota hanya boleh mengisi report sampai 31 hari ke belakang.
        if self.app.team.users[uid]["role"] not in RECAP_ROLES and not (
                date.today() - timedelta(days=31) <= d <= date.today()):
            raise HttpError(400, "Tanggal di luar batas")
        return d

    # ---------- respons ----------

    def send(self, status, payload=None, headers=None, raw=None, ctype="application/json; charset=utf-8"):
        data = raw if raw is not None else json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _drain(self):
        """Buang isi kiriman yang belum dibaca supaya penolakan (mis. 401) tidak memutus koneksi klien."""
        if getattr(self, "_body_done", False):
            return
        length = int(self.headers.get("Content-Length") or 0)
        if 0 < length <= MAX_BIG_BODY:
            self.rfile.read(length)
        elif length:
            self.close_connection = True

    def handle_api(self, method):
        self._body_done = False
        try:
            if method != "GET" and self.headers.get("X-HRGA") != "1":
                raise HttpError(403, "Permintaan ditolak")
            path = urlparse(self.path).path
            route = ROUTES.get((method, path))
            if not route:
                raise HttpError(404, "Tidak ditemukan")
            route(self)
        except HttpError as e:
            self._drain()
            self.send(e.status, {"error": str(e)})
        except Exception:
            log.exception("Error server: %s %s", method, self.path)
            self.send(500, {"error": "Terjadi kesalahan di server"})

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            return self.handle_api("GET")
        name = STATIC.get(path)
        if not name:
            return self.send(404, {"error": "Tidak ditemukan"})
        full = os.path.normpath(os.path.join(self.app.web_dir, name))
        try:
            with open(full, "rb") as f:
                data = f.read()
        except OSError:
            return self.send(404, {"error": "Tidak ditemukan"})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if name.endswith(".webmanifest"):
            ctype = "application/manifest+json"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self.send(200, raw=data, ctype=ctype)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.handle_api("POST")

    def do_PUT(self):
        self.handle_api("PUT")

    # ---------- rute ----------

    def api_login(self):
        app, ip = self.app, self.client_ip()
        if app.ip_blocked(ip):
            raise HttpError(429, "Terlalu banyak percobaan, coba lagi nanti")
        data = self.body()
        name = str(data.get("name", ""))[:60]
        try:
            token, uid = app.team.login(name, str(data.get("pin", ""))[:12],
                                        self.headers.get("User-Agent", "")[:80])
        except AuthError as e:
            app.ip_failed(ip)
            app.team.audit(f"login gagal: {e}", name, ip)
            raise HttpError(401, str(e))
        app.team.audit("login", uid, ip)
        cookie = f"{COOKIE}={token}; Path=/; Max-Age={30 * 24 * 3600}; HttpOnly; Secure; SameSite=Strict"
        self.send(200, {"user": app.team.public(uid), "token": token}, {"Set-Cookie": cookie})

    def api_logout(self):
        self.app.team.logout(self.token())
        self.send(200, {"ok": True}, {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict"})

    def api_me(self):
        uid = self.user()
        self.send(200, {"user": self.app.team.public(uid), "today": date.today().isoformat(),
                        "title": self.app.title(date.today(), uid)})

    def api_report_get(self):
        uid = self.user()
        q = parse_qs(urlparse(self.path).query)
        d = self.day(q.get("date", [""])[0], uid)
        rep = self.app.team.get_report(d, uid) or {}
        self.send(200, {"date": d.isoformat(), "title": self.app.title(d, uid), "text": rep.get("text", ""),
                        "story": rep.get("story", ""), "sent_at": rep.get("sent_at")})

    def api_report_put(self):
        uid = self.user()
        data = self.body()
        d = self.day(data.get("date"), uid)
        rep = self.app.team.save_report(d, uid, redact(str(data.get("text", ""))),
                                        story=str(data.get("story", "")), source=self._source(uid))
        self.send(200, {"ok": True, "sent_at": rep.get("sent_at")})

    def api_report_submit(self):
        uid = self.user()
        data = self.body()
        d = self.day(data.get("date"), uid)
        text = redact(str(data.get("text", ""))).strip()
        if not text:
            raise HttpError(400, "Report masih kosong")
        story = data.get("story")
        rep = self.app.team.save_report(d, uid, text, story=None if story is None else str(story),
                                        source=str(data.get("source") or self._source(uid))[:10], submit=True)
        self.app.team.audit(f"kirim report {d.isoformat()}", uid, self.client_ip())
        self.send(200, {"ok": True, "sent_at": rep["sent_at"]})

    def _source(self, uid):
        return self.app.team.users[uid]["device"]

    def api_tidy(self):
        uid = self.user()
        data = self.body()
        d = self.day(data.get("date"), uid)
        story = str(data.get("story", "")).strip()
        if not story:
            raise HttpError(400, "Ceritakan dulu pekerjaan hari ini")
        u = self.app.team.users[uid]
        prompt = claude_ai.build_story_prompt(story, d, u["name"], self.app.lang, u.get("routine", []))
        text = self.app.claude(self.app.tidy_fn, prompt, self.app.title(d, uid))
        self.app.team.save_report(d, uid, text, story=story, source=u["device"])
        self.send(200, {"text": text})

    def api_revise(self):
        uid = self.user()
        data = self.body()
        d = self.day(data.get("date"), uid)
        ask = str(data.get("instruction", "")).strip()
        draft = str(data.get("text", ""))
        if not ask:
            raise HttpError(400, "Tulis dulu apa yang mau diubah")
        u = self.app.team.users[uid]
        title = self.app.title(d, uid)
        context = chat.context_text(redact(draft), {}, d, 0, 24, u["name"], u.get("routine", []),
                                    [str(data.get("story", ""))], title)
        reply = self.app.claude(self.app.ask_fn, chat.build_prompt([], ask, context))
        report = chat.extract_report(reply)
        text = claude_ai.tidy(report, title) if report else draft
        if report:
            self.app.team.save_report(d, uid, text, source=u["device"])
        self.send(200, {"text": text, "changed": bool(report), "reply": chat.reply_only(reply)})

    def api_generate(self):
        """Generate Report untuk laptop tanpa Claude: prompt disusun di server dari chat yang dikirim."""
        uid = self.user()
        data = self.body(MAX_BIG_BODY)
        d = self.day(data.get("date"), uid)
        u = self.app.team.users[uid]
        lang = data.get("lang") if data.get("lang") in ("id", "en") else self.app.lang
        try:
            start, end = int(data.get("start_hour", 6)), int(data.get("end_hour", 17))
        except (TypeError, ValueError):
            raise HttpError(400, "Jam kerja salah")
        chats = data.get("chats") or {}
        if not isinstance(chats, dict):
            raise HttpError(400, "Format chat salah")
        strs = lambda key: [str(x) for x in (data.get(key) or [])][:50]
        nick = {str(k): str(v) for k, v in (data.get("nicknames") or {}).items()}
        prompt = claude_ai.build_prompt(chats, d, u["name"], start, end, lang, strs("routine"), strs("notes"), nick)
        title = report_title(d, u["name"], lang)
        text = self.app.claude(self.app.tidy_fn, prompt, title)
        self.app.team.audit(f"generate {d.isoformat()}", uid, self.client_ip())
        self.send(200, {"text": text})

    def api_chat(self):
        """Chat Claude untuk laptop tanpa Claude; riwayat dan konteks dikirim oleh app laptop."""
        uid = self.user()
        data = self.body(MAX_BIG_BODY)
        message = str(data.get("message", "")).strip()
        if not message:
            raise HttpError(400, "Pesan kosong")
        history = [(("user" if r == "user" else "assistant"), str(t)) for r, t in (data.get("history") or [])][-20:]
        prompt = chat.build_prompt(history, message, str(data.get("context", "")))
        reply = self.app.claude(self.app.ask_fn, prompt)
        self.app.team.audit("chat", uid, self.client_ip())
        self.send(200, {"text": reply})

    def api_history(self):
        uid = self.user()
        days = [date.today() - timedelta(days=i) for i in range(7)]
        self.send(200, {"items": self.app.team.history(uid, days)})

    def api_team(self):
        self.user(recap=True)
        q = parse_qs(urlparse(self.path).query)
        d = parse_day(q.get("date", [""])[0]) or date.today()
        rows = self.app.team.recap(d)
        self.send(200, {"date": d.isoformat(), "rows": rows, "text": recap_text(rows, d)})

    def api_users_get(self):
        self.user(admin=True)
        users = self.app.team.list_users()
        for u in users:
            u["sessions"] = self.app.team.session_count(u["id"])
        self.send(200, {"users": users})

    def api_users_post(self):
        admin = self.user(admin=True)
        data = self.body()
        team, action = self.app.team, data.get("action")
        uid = str(data.get("id", ""))
        result = {"ok": True}
        try:
            if action == "add":
                uid = team.add_user(str(data.get("name", "")), str(data.get("title", "")),
                                    str(data.get("role", "member")), str(data.get("device", "android")))
            elif uid not in team.users:
                raise HttpError(404, "User tidak ditemukan")
            elif action == "pin":
                # PIN baru hanya ditampilkan sekali ke admin.
                pin = str(data.get("pin") or team.new_pin())
                team.set_pin(uid, pin)
                result["pin"] = pin
            elif action == "revoke":
                result["revoked"] = team.revoke_sessions(uid)
            elif action == "update":
                team.update_user(uid, title=data.get("title"), role=data.get("role"),
                                 device=data.get("device"), routine=data.get("routine"))
            elif action == "remove":
                if uid == admin:
                    raise HttpError(400, "Tidak bisa menghapus akun sendiri")
                team.remove_user(uid)
            else:
                raise HttpError(400, "Aksi tidak dikenal")
        except ValueError as e:
            raise HttpError(400, str(e))
        team.audit(f"user {action} {uid}", admin, self.client_ip())
        self.send(200, result)


ROUTES = {
    ("POST", "/api/login"): _Handler.api_login,
    ("POST", "/api/logout"): _Handler.api_logout,
    ("GET", "/api/me"): _Handler.api_me,
    ("GET", "/api/report"): _Handler.api_report_get,
    ("PUT", "/api/report"): _Handler.api_report_put,
    ("POST", "/api/report/submit"): _Handler.api_report_submit,
    ("POST", "/api/tidy"): _Handler.api_tidy,
    ("POST", "/api/revise"): _Handler.api_revise,
    ("GET", "/api/history"): _Handler.api_history,
    ("POST", "/api/generate"): _Handler.api_generate,
    ("POST", "/api/chat"): _Handler.api_chat,
    ("GET", "/api/team"): _Handler.api_team,
    ("GET", "/api/users"): _Handler.api_users_get,
    ("POST", "/api/users"): _Handler.api_users_post,
}


def run_headless(argv, web_dir):
    """Mode layanan Windows (NSSM) di PC server: server saja, tanpa jendela.

    Opsi: --port 8500 (bawaan), --lang id/en. Folder data mengikuti HRGA_WA_DATA,
    dan lokasi Claude bisa dipaksa lewat HRGA_CLAUDE_CLI (mis. claude.exe bawaan paket npm).
    """
    import argparse

    from core import settings

    ap = argparse.ArgumentParser(prog="hrga-server")
    ap.add_argument("--server", action="store_true")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--lang", default="id", choices=("id", "en"))
    args, _ = ap.parse_known_args(argv)
    cli = os.environ.get("HRGA_CLAUDE_CLI") or claude_ai.find_cli()
    log.info("Mode server: port %d, data %s, Claude %s", args.port, settings.SERVER_DIR, cli or "-")
    srv = ReportServer(settings.SERVER_DIR, web_dir, cli=cli, lang=args.lang, port=args.port).start()
    stop = threading.Event()
    try:
        while not stop.wait(3600):
            pass
    finally:
        srv.stop()
