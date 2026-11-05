"""Bantuan Tailscale Funnel di PC server: alamat publik HTTPS untuk server HRGA."""

import json
import os
import shutil
import subprocess

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def find_cli():
    found = shutil.which("tailscale")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", "")):
        path = os.path.join(base, "Tailscale", "tailscale.exe")
        if base and os.path.exists(path):
            return path
    return None


def _run(cli, *args, timeout=30):
    return subprocess.run([cli, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=NO_WINDOW)


def public_url(cli):
    """https://nama-pc.tailnet.ts.net, atau None kalau Tailscale belum login."""
    try:
        data = json.loads(_run(cli, "status", "--json").stdout)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None
    if data.get("BackendState") != "Running":
        return None
    dns = (data.get("Self") or {}).get("DNSName", "").rstrip(".")
    return f"https://{dns}" if dns else None


def is_on(cli, port):
    """True kalau Funnel sudah meneruskan ke port server ini."""
    try:
        data = json.loads(_run(cli, "funnel", "status", "--json").stdout or "{}")
    except (ValueError, OSError, subprocess.SubprocessError):
        return False
    if not any((data.get("AllowFunnel") or {}).values()):
        return False
    return f"127.0.0.1:{port}" in json.dumps(data.get("Web") or {}) or f"localhost:{port}" in json.dumps(
        data.get("Web") or {})


def enable(cli, port):
    """Nyalakan Funnel di latar; kembalikan (ok, pesan). Pesan berisi link admin kalau Funnel belum diizinkan."""
    try:
        r = _run(cli, "funnel", "--bg", f"http://127.0.0.1:{port}", timeout=60)
    except subprocess.TimeoutExpired:
        return False, "Tailscale tidak menjawab. Funnel mungkin perlu diizinkan dulu di admin console."
    out = (r.stdout + "\n" + r.stderr).strip()
    return r.returncode == 0, out


def disable(cli):
    r = _run(cli, "funnel", "reset")
    return r.returncode == 0, (r.stdout + r.stderr).strip()
