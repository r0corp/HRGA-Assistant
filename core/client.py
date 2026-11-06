"""Klien server HRGA untuk app laptop: login, kirim report ke Fena, ambil Rekap Tim."""

import json
import urllib.error
import urllib.request


class ServerError(Exception):
    def __init__(self, message, status=0):
        super().__init__(message)
        self.status = status


def normalize(url):
    url = (url or "").strip().rstrip("/")
    if url and "://" not in url:
        url = "https://" + url
    return url


class IatClient:
    """Klien App HRGA (Internal Asset Tracker): kirim report dengan token pribadi dari halaman HRGA Asisten."""

    def __init__(self, url, token, timeout=30):
        self.url = normalize(url)
        self.token = (token or "").strip()
        self.timeout = timeout

    def _call(self, method, path, data=None):
        if not self.url:
            raise ServerError("Alamat App HRGA belum diisi di Pengaturan")
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(self.url + path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-HRGA-Token", self.token)
        req.add_header("User-Agent", "HRGA Asisten")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except ValueError:
                msg = None
            raise ServerError(msg or f"App HRGA menjawab {e.code}", e.code)
        except (urllib.error.URLError, OSError) as e:
            raise ServerError(f"App HRGA tidak bisa dihubungi: {getattr(e, 'reason', e)}")

    def me(self):
        return self._call("GET", "/api/agent/me")

    def submit(self, day, text):
        return self._call("POST", "/api/agent/report", {"date": day.isoformat(), "text": text, "submit": True})


class Client:
    def __init__(self, url, token=None, timeout=30):
        self.url = normalize(url)
        self.token = token
        self.timeout = timeout

    def _call(self, method, path, data=None, timeout=None):
        if not self.url:
            raise ServerError("Alamat server belum diisi di Pengaturan")
        body = json.dumps(data or {}).encode("utf-8") if method != "GET" else None
        req = urllib.request.Request(self.url + path, data=body, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-HRGA", "1")
        req.add_header("User-Agent", "HRGA WA Report (laptop)")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read().decode("utf-8")).get("error")
            except ValueError:
                msg = None
            raise ServerError(msg or f"Server menjawab {e.code}", e.code)
        except (urllib.error.URLError, OSError) as e:
            raise ServerError(f"Server tidak bisa dihubungi: {getattr(e, 'reason', e)}")

    def login(self, name, pin):
        res = self._call("POST", "/api/login", {"name": name, "pin": pin})
        self.token = res["token"]
        return res["user"]

    def logout(self):
        try:
            self._call("POST", "/api/logout")
        finally:
            self.token = None

    def me(self):
        return self._call("GET", "/api/me")["user"]

    def submit(self, day, text):
        return self._call("POST", "/api/report/submit",
                          {"date": day.isoformat(), "text": text, "source": "laptop"})

    def generate(self, day, chats, start_hour, end_hour, lang, routine, notes, nicknames):
        """Generate Report memakai Claude di PC server (untuk laptop tanpa Claude)."""
        return self._call("POST", "/api/generate", {
            "date": day.isoformat(), "chats": chats, "start_hour": start_hour, "end_hour": end_hour,
            "lang": lang, "routine": list(routine), "notes": list(notes), "nicknames": nicknames,
        }, timeout=330)["text"]

    def translate(self, day, text):
        """Terjemahkan draf ke Inggris memakai Claude di PC server."""
        return self._call("POST", "/api/translate", {"date": day.isoformat(), "text": text}, timeout=330)["text"]

    def chat(self, history, message, context=""):
        return self._call("POST", "/api/chat", {"history": history, "message": message, "context": context},
                          timeout=330)["text"]

    def team(self, day):
        return self._call("GET", f"/api/team?date={day.isoformat()}")
