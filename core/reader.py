"""Membaca chat dan mengirim report lewat WhatsApp Web dengan Playwright."""

import logging
import os
import random
import re
import time

from playwright.sync_api import sync_playwright

from core.parse import detect_order, label_to_date, parse_pre, pre_date_text


WA_URL = "https://web.whatsapp.com/"

log = logging.getLogger(__name__)


# Ambil baris daftar chat yang sedang ter-render: nama + label waktu terakhir.
JS_VISIBLE_ROWS = """
() => [...document.querySelectorAll('#pane-side [role="row"], #pane-side [role="listitem"]')].map(r => {
  const titled = [...r.querySelectorAll('span[title]')].map(s => s.getAttribute('title')).filter(Boolean);
  const lines = r.innerText.split('\\n').map(s => s.trim()).filter(Boolean);
  const name = titled[0] || lines.find(l => l.length > 2) || lines[0] || '';
  const label = lines.find(l => /^(\\d{1,2}[:.]\\d{2}(\\s*[AaPp][Mm])?|Yesterday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|\\d{1,4}[\\/.-]\\d{1,2}[\\/.-]\\d{1,4})$/.test(l)) || '';
  return {name, label};
})
"""

JS_SCROLL_LIST = "(dy) => { const p = document.querySelector('#pane-side'); const before = p.scrollTop; p.scrollTop += dy; return p.scrollTop !== before; }"

JS_LIST_TOP = "() => { document.querySelector('#pane-side').scrollTop = 0; }"

# Cari baris chat berdasarkan nama, gulir ke tengah, kembalikan titik tengahnya.
JS_LOCATE_ROW = """
async (name) => {
  const p = document.querySelector('#pane-side');
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const rowName = r => {
    const t = r.querySelector('span[title]');
    return t ? t.getAttribute('title') : r.innerText.split('\\n')[0];
  };
  p.scrollTop = 0;
  for (let k = 0; k < 80; k++) {
    await sleep(250);
    const rows = [...p.querySelectorAll('[role="row"], [role="listitem"]')];
    const r = rows.find(r => rowName(r) === name);
    if (r) {
      r.scrollIntoView({block: 'center'});
      await sleep(400);
      const b = r.getBoundingClientRect();
      return {x: b.left + b.width / 2, y: b.top + b.height / 2};
    }
    const before = p.scrollTop;
    p.scrollTop += 400;
    if (p.scrollTop === before) break;
  }
  return null;
}
"""

JS_SYNCING = """
() => {
  const p = document.querySelector('#pane-side');
  const before = p.scrollTop;
  p.scrollTop = p.scrollHeight;
  const busy = /Loading\\u2026|Loading\\.\\.\\./.test(p.innerText);
  p.scrollTop = before;
  return busy;
}
"""

JS_HEADER = "() => (document.querySelector('#main header') || {}).innerText || ''"

# Gulir panel pesan ke atas satu langkah supaya pesan lama dimuat.
JS_SCROLL_MESSAGES_UP = """
() => {
  const m = document.querySelector('#main');
  const d = [...m.querySelectorAll('div')].find(d => d.scrollHeight > d.clientHeight + 20);
  if (!d) return false;
  d.scrollTop = 0;
  d.dispatchEvent(new Event('scroll'));
  return true;
}
"""

# Nama class WhatsApp Web diacak (".message-out" sudah tidak ada), jadi pesan
# sendiri dikenali dari posisinya: gelembungnya selalu di sisi kanan panel.
JS_IS_OUT = """
(el, m) => {
  const b = el.getBoundingClientRect(), p = m.getBoundingClientRect();
  return b.left + b.width / 2 > p.left + p.width / 2;
}
"""

# Pesan panjang bisa terpecah ke beberapa .selectable-text, jadi semuanya
# digabung. Kutipan pada pesan balasan berada di dalam [role=button] dan
# dilewati supaya pesan yang dikutip tidak terbaca ulang.
JS_MESSAGES = """
() => {
  const m = document.querySelector('#main');
  const isOut = """ + JS_IS_OUT + """;
  const out = [...m.querySelectorAll('[data-pre-plain-text]')]
    .filter(el => (el.getAttribute('data-pre-plain-text') || '').startsWith('['))
    .map(el => {
      const ts = [...el.querySelectorAll('.selectable-text')].filter(t => {
        const q = t.closest('[role=button]');
        return !(q && el.contains(q)) && !t.parentElement.closest('.selectable-text');
      });
      return {
        pre: el.getAttribute('data-pre-plain-text') || '',
        text: (ts.length ? ts.map(t => t.innerText).join('\\n') : el.innerText || '').trim(),
        out: isOut(el, m),
      };
    });
  return {
    messages: out,
    older_on_phone: /older messages from your phone/i.test(m.innerText),
  };
}
"""

COMPOSE = "footer div[contenteditable='true']"

# Tempel teks lewat event paste: kalau diketik, WhatsApp mengubah "1." dan "-"
# jadi list otomatis dan Enter langsung mengirim baris pertama.
JS_PASTE = """
(el, text) => {
  el.focus();
  const dt = new DataTransfer();
  dt.setData('text/plain', text);
  el.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
}
"""

JS_OUT_COUNT = """
() => {
  const m = document.querySelector('#main');
  const isOut = """ + JS_IS_OUT + """;
  return [...m.querySelectorAll('[data-pre-plain-text]')].filter(el => isOut(el, m)).length;
}
"""


def _pause(lo=1.0, hi=3.0):
    time.sleep(random.uniform(lo, hi))


def digits(text):
    return re.sub(r"\D", "", text or "")


def is_self_chat(name, phone):
    """Chat "Message yourself" (tempat report dikirim) tidak ikut dibaca."""
    if name.endswith("(You)") or name in ("You", "Anda"):
        return True
    d = digits(phone)
    return bool(d) and digits(name).endswith(d[-9:]) and len(digits(name)) >= 9


def launch(pw, profile_dir, headless):
    """Pakai Edge bawaan Windows; kalau gagal, coba Google Chrome."""
    last = None
    # HRGA_WA_BROWSER=chrome memaksa Chrome dipakai lebih dulu.
    channels = ("chrome", "msedge") if os.environ.get("HRGA_WA_BROWSER") == "chrome" else ("msedge", "chrome")
    for channel in channels:
        try:
            return pw.chromium.launch_persistent_context(
                profile_dir,
                channel=channel,
                headless=headless,
                viewport={"width": 1366, "height": 900},
            )
        except Exception as e:
            last = e
            log.warning("Browser %s tidak bisa dibuka: %s", channel, e)
    raise RuntimeError("Microsoft Edge atau Google Chrome tidak ditemukan.") from last


class WhatsApp:
    def __init__(self, profile_dir, headless=True, date_order="DMY", pre_date_order="DMY"):
        self.profile_dir = profile_dir
        self.headless = headless
        # Urutan tanggal hanya dipakai kalau ambigu (hari <= 12); selebihnya
        # dideteksi otomatis dari contoh tanggal.
        self.date_order = date_order
        self.pre_date_order = pre_date_order
        self._pw = None
        self.context = None
        self.page = None

    def __enter__(self):
        self._pw = sync_playwright().start()
        try:
            self.context = launch(self._pw, self.profile_dir, self.headless)
        except Exception:
            self._pw.stop()
            raise
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(WA_URL)
        return self

    def __exit__(self, *exc):
        try:
            self.context.close()
        finally:
            self._pw.stop()

    def wait_ready(self, timeout_s=60, sync_wait_s=180):
        """Tunggu daftar chat muncul. False kalau masih di halaman QR."""
        try:
            self.page.wait_for_selector("#pane-side", timeout=timeout_s * 1000)
        except Exception:
            return False

        # Setelah login baru, WhatsApp Web masih menyinkronkan chat.
        deadline = time.time() + sync_wait_s
        time.sleep(3)
        while time.time() < deadline:
            if not self.page.evaluate(JS_SYNCING):
                break
            time.sleep(5)
        else:
            log.warning("Sinkronisasi WhatsApp Web belum selesai; daftar chat mungkin belum lengkap.")

        return True

    def list_chats(self, since, today):
        """Daftar chat yang aktivitas terakhirnya >= since, berurutan dari terbaru."""
        self.page.evaluate(JS_LIST_TOP)
        seen = {}
        stale = 0

        while True:
            time.sleep(0.5)
            for row in self.page.evaluate(JS_VISIBLE_ROWS):
                if row["name"] and row["name"] not in seen:
                    seen[row["name"]] = label_to_date(row["label"], today, self.date_order)

            # Daftar chat urut dari terbaru; berhenti kalau 5 chat terakhir sudah
            # lebih lama dari since (chat terpin di atas bisa saja lama).
            tail = [d for d in list(seen.values())[-5:] if d]
            if len(tail) == 5 and all(d < since for d in tail):
                break

            if self.page.evaluate(JS_SCROLL_LIST, 400):
                stale = 0
                continue

            # Mentok di bawah. WhatsApp Web memuat daftar chat bertahap, jadi
            # tunggu dulu barisan berikutnya (sampai ~10 detik) sebelum
            # menganggap daftar sudah habis; dulu chat lama sempat terlewat.
            stale += 1
            if stale >= 8:
                break
            time.sleep(1.2)

        return [name for name, d in seen.items() if d and d >= since]

    def open_chat(self, name):
        pos = self.page.evaluate(JS_LOCATE_ROW, name)
        if not pos:
            return False

        self.page.mouse.click(pos["x"], pos["y"])

        for _ in range(12):
            time.sleep(0.5)
            if name in self.page.evaluate(JS_HEADER):
                return True
        return False

    def read_messages(self, since):
        """Pesan chat yang sedang terbuka sejak tanggal since."""
        data = None
        last_count = -1
        stale = 0
        order = self.pre_date_order

        for _ in range(30):
            data = self.page.evaluate(JS_MESSAGES)
            texts = [t for t in (pre_date_text(m["pre"]) for m in data["messages"]) if t]
            order = detect_order(texts, self.pre_date_order)
            parsed = [parse_pre(m["pre"], order) for m in data["messages"]]
            dates = [p[0].date() for p in parsed if p]

            if (dates and min(dates) < since) or data["older_on_phone"]:
                break

            count = len(data["messages"])
            stale = stale + 1 if count == last_count else 0
            if stale >= 3:
                break
            last_count = count

            self.page.evaluate(JS_SCROLL_MESSAGES_UP)
            time.sleep(1.2)

        messages = []
        for m in data["messages"]:
            parsed = parse_pre(m["pre"], order)
            if not parsed:
                continue
            dt, sender = parsed
            if dt.date() < since:
                continue
            messages.append({
                "time": dt.isoformat(timespec="minutes"),
                "sender": sender,
                "out": m["out"],
                "text": m["text"],
            })

        return messages

    def read_chats(self, names, since, progress=None):
        """Buka tiap chat dan ambil pesannya. Hasil: {nama: [pesan]}."""
        result = {}

        for i, name in enumerate(names, 1):
            if progress:
                progress(i, len(names), name)
            if not self.open_chat(name):
                log.warning("Chat tidak bisa dibuka: %s", name)
                continue

            result[name] = self.read_messages(since)
            log.info("%s: %d pesan", name, len(result[name]))

            _pause()

        return result

    def report_messages(self, group, since):
        """Pesan di grup report sejak since, untuk mengecek report yang sudah dikirim."""
        if not self.open_chat(group):
            log.warning("Grup report tidak ditemukan: %s", group)
            return []
        return self.read_messages(since)

    def send_to_self(self, phone, text):
        """Kirim teks ke chat nomor sendiri ("Message yourself")."""
        self.page.goto(f"{WA_URL}send?phone={digits(phone)}")
        return self._paste_send(text)

    def send_to_chat(self, name, text):
        """Kirim teks ke chat/grup berdasarkan nama di daftar chat."""
        if not self.open_chat(name):
            raise RuntimeError(f"Chat '{name}' tidak ditemukan di WhatsApp.")
        return self._paste_send(text)

    def _paste_send(self, text):
        box = self.page.wait_for_selector(COMPOSE, timeout=60_000)
        time.sleep(2)
        before = self.page.evaluate(JS_OUT_COUNT)

        box.evaluate(JS_PASTE, text)
        time.sleep(1)
        self.page.keyboard.press("Enter")

        # Tunggu pesan baru muncul sebelum browser ditutup.
        for _ in range(30):
            time.sleep(0.5)
            if self.page.evaluate(JS_OUT_COUNT) > before:
                time.sleep(2)
                return True
        return False
