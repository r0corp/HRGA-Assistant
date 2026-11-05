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

    def team(self, day):
        return self._call("GET", f"/api/team?date={day.isoformat()}")
