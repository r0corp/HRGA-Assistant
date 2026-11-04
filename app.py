"""HRGA WA Report: tarik chat WhatsApp lalu susun draf daily report."""

import json
import logging
import os
import calendar
import queue
import re
import shutil
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import font as tkfont, messagebox, ttk

import sv_ttk

import time

from core import autostart, claude_ai, history, settings, updater
from core.i18n import DAYS, DAYS_SHORT, LANGS, MONTHS, t
from core.pdf import save_pdf
from core.reader import WhatsApp, is_self_chat
from core.summary import build_report, in_window, report_title


log = logging.getLogger("app")

# Warna: sidebar abu-abu muda dan kartu putih (gaya RustDesk), aksen merah Tradecorp.
RED = "#c8102e"
RED_DARK = "#a50d26"
GREEN = "#1a9f4b"
AMBER = "#e0a100"
SIDE = "#eef0f3"
BG = "#f7f8fa"
CARD = "#ffffff"
BORDER = "#e1e4e8"
TEXT = "#1f2328"
MUTED = "#6b7280"
FONT = "Segoe UI"


def asset(name):
    """Lokasi file di folder assets, juga saat berjalan sebagai .exe PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def raw_path(day):
    return os.path.join(settings.RAW_DIR, f"{day.isoformat()}.json")


def report_path(day, ext="txt"):
    return os.path.join(settings.REPORTS_DIR, f"{day.isoformat()}.{ext}")


def fmt_day(d, lang):
    """date -> "Selasa / 03-11-2026"."""
    return f"{DAYS[lang][d.weekday()]} / {d:%d-%m-%Y}"


def parse_day(text):
    """ "Selasa / 03-11-2026", "03-11-2026", atau "2026-11-03" -> date; None kalau tidak valid."""
    text = text.strip()
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", text)
    try:
        if m:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        return date.fromisoformat(text)
    except ValueError:
        return None


def to_wa_number(phone):
    """0812... -> 62812...; nomor yang sudah berawalan 62 dibiarkan."""
    d = "".join(c for c in phone if c.isdigit())
    return "62" + d[1:] if d.startswith("0") else d


# ---------- komponen ----------

def rounded_rect(canvas, x1, y1, x2, y2, r, **kw):
    """Persegi panjang bersudut bulat di canvas (poligon smooth)."""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


class FlatButton(tk.Canvas):
    """Tombol bersudut bulat: "primary" merah, "secondary" putih bergaris, "ghost" tanpa garis.

    Digambar di canvas karena tk.Button tidak bisa bersudut bulat. Mendukung
    configure(state="disabled"/"normal") seperti tombol biasa.
    """

    COLORS = {
        # (isi, teks, isi saat hover, garis tepi)
        "primary": (RED, "white", RED_DARK, RED),
        "secondary": (CARD, TEXT, "#f1f3f5", BORDER),
        "ghost": (None, RED, None, None),
    }

    def __init__(self, parent, text, command, kind="secondary", small=False, anchor="center", **kw):
        self.fill, self.fg, self.hover_fill, self.edge = self.COLORS[kind]
        self.fill = self.fill or parent["bg"]
        self.hover_fill = self.hover_fill or self.fill
        self.edge = self.edge or self.fill
        self.text, self.command, self.anchor = text, command, anchor
        self.font = tkfont.Font(family=FONT, size=9 if small else 10, weight="bold" if kind == "primary" else "normal")
        self.padx = 10 if small else 14
        height = self.font.metrics("linespace") + (10 if small else 18)
        width = self.font.measure(text) + 2 * self.padx
        super().__init__(parent, width=width, height=height, bg=parent["bg"],
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.state_ = "normal"
        self.hovered = False
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))
        self.bind("<ButtonRelease-1>", self._click)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4 or h < 4:
            return
        disabled = self.state_ == "disabled"
        fill = self.hover_fill if self.hovered and not disabled else self.fill
        rounded_rect(self, 1, 1, w - 2, h - 2, 9, fill=fill, outline=self.edge, width=1)
        fg = "#b0b4ba" if disabled and self.fg != "white" else self.fg
        if disabled and self.fg == "white":
            fg = "#f3c3cb"
        x = self.padx if self.anchor == "w" else w / 2
        self.create_text(x, h / 2, text=self.text, fill=fg, font=self.font,
                         anchor="w" if self.anchor == "w" else "center")

    def _hover(self, on):
        self.hovered = on
        self._draw()

    def _click(self, e):
        inside = 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height()
        if self.state_ != "disabled" and inside and self.command:
            self.command()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self.state_ = str(kw.pop("state"))
            super().configure(cursor="arrow" if self.state_ == "disabled" else "hand2")
            self._draw()
        if cnf or kw:
            return super().configure(cnf, **kw)

    config = configure


def label(parent, text, size=9, color=TEXT, bold=False, **kw):
    kw.setdefault("bg", parent["bg"])
    return tk.Label(parent, text=text, fg=color, font=(FONT, size, "bold" if bold else "normal"), **kw)


class ProgressBar(tk.Canvas):
    """Bar progres bersudut bulat: merah saat berjalan, hijau saat selesai."""

    def __init__(self, parent, height=8):
        super().__init__(parent, height=height, bg=parent["bg"], highlightthickness=0, bd=0)
        self.value = 0
        self.color = RED
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, value, color=RED):
        self.value, self.color = max(0, min(100, value)), color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        rounded_rect(self, 0, 0, w - 1, h - 1, h / 2, fill=BORDER, outline=BORDER)
        filled = (w - 1) * self.value / 100
        if filled >= h:
            rounded_rect(self, 0, 0, filled, h - 1, h / 2, fill=self.color, outline=self.color)


class RoundCard(tk.Canvas):
    """Kartu putih bersudut membulat dengan garis tepi tipis.

    Isi kartu ditaruh di .body. Kartu yang tidak di-expand mengikuti tinggi
    isinya; kartu yang di-expand mengikuti ukuran dari layout.
    """

    def __init__(self, parent, radius=12, expand=False, **kw):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, bd=0, height=40, **kw)
        self.radius = radius
        self.expand = expand
        self.inset = max(3, radius // 3)
        self.body = tk.Frame(self, bg=CARD)
        self._win = self.create_window(self.inset, self.inset, window=self.body, anchor="nw")
        self.bind("<Configure>", self._redraw)
        if not expand:
            self.body.bind("<Configure>", self._fit)

    def _fit(self, _e=None):
        h = self.body.winfo_reqheight() + 2 * self.inset
        if int(self["height"]) != h:
            self.configure(height=h)

    def _redraw(self, e):
        w, h = e.width, e.height
        self.delete("bg")
        rounded_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=CARD, outline=BORDER, width=1, tags="bg")
        self.tag_lower("bg")
        self.itemconfigure(self._win, width=max(w - 2 * self.inset, 1))
        if self.expand:
            self.itemconfigure(self._win, height=max(h - 2 * self.inset, 1))


class ChatTable(tk.Frame):
    """Tabel chat: kolom centang, nama chat, jumlah pesan, dan rentang jam."""

    ON, OFF = "☑", "☐"

    def __init__(self, parent, headings):
        super().__init__(parent, bg=CARD)
        self.tree = ttk.Treeview(self, columns=("pick", "chat", "msgs", "time"), show="headings",
                                 selectmode="none", style="Chat.Treeview")
        for col, text, width, anchor, stretch in (
            ("pick", self.ON, 40, "center", False),
            ("chat", headings[0], 100, "w", True),
            ("msgs", headings[1], 64, "center", False),
            ("time", headings[2], 96, "center", False),
        ):
            self.tree.heading(col, text=text, anchor=anchor)
            self.tree.column(col, width=width, minwidth=width if not stretch else 100,
                             anchor=anchor, stretch=stretch)
        self.tree.heading("pick", command=self.toggle_all)
        self.tree.tag_configure("odd", background="#fafbfc")
        self.tree.tag_configure("off", foreground="#a0a4aa")
        bar = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<Button-1>", self._click)
        self.picked = {}
        self.empty = label(self, "", 10, MUTED, bg=CARD)

    def set_rows(self, rows, checked=None, empty_text=""):
        """rows: [(nama, jumlah_pesan, rentang_jam)]."""
        self.tree.delete(*self.tree.get_children())
        self.picked = {}
        for i, (name, count, span) in enumerate(rows):
            on = checked is None or name in checked
            self.picked[name] = on
            self.tree.insert("", "end", iid=name, values=(self.ON if on else self.OFF, name, count, span),
                             tags=self._tags(i, on))
        if rows:
            self.empty.place_forget()
        else:
            self.empty.configure(text=empty_text)
            self.empty.place(relx=0.5, rely=0.45, anchor="center")

    def _tags(self, i, on):
        return tuple(t for t in ("odd" if i % 2 else "", "" if on else "off") if t)

    def _set(self, name, on):
        self.picked[name] = on
        i = self.tree.index(name)
        self.tree.set(name, "pick", self.ON if on else self.OFF)
        self.tree.item(name, tags=self._tags(i, on))

    def _click(self, e):
        if self.tree.identify_region(e.x, e.y) != "cell":
            return
        row = self.tree.identify_row(e.y)
        if row:
            self._set(row, not self.picked[row])

    def toggle_all(self):
        on = not all(self.picked.values())
        for name in self.picked:
            self._set(name, on)

    def checked(self):
        return [n for n, on in self.picked.items() if on]

    def unchecked(self):
        return [n for n, on in self.picked.items() if not on]


class CalendarPopup(tk.Toplevel):
    """Kalender dropdown di bawah kolom tanggal; klik tanggal untuk memilih."""

    def __init__(self, anchor, selected, lang, on_pick):
        super().__init__(anchor, bg=BORDER)
        self.overrideredirect(True)
        self.lang, self.on_pick = lang, on_pick
        self.selected = selected or date.today()
        self.month = self.selected.replace(day=1)

        self.body = tk.Frame(self, bg=CARD, padx=10, pady=10)
        self.body.pack(padx=1, pady=1)
        self._draw()

        anchor.update_idletasks()
        self.geometry(f"+{anchor.winfo_rootx()}+{anchor.winfo_rooty() + anchor.winfo_height() + 4}")
        # Selalu di atas jendela utama. Dulu kalender ditutup saat kehilangan
        # fokus, tapi di Windows fokus langsung kembali ke jendela utama saat
        # mouse dilepas sehingga kalender tertutup sebelum terlihat.
        self.transient(anchor.winfo_toplevel())
        self.attributes("-topmost", True)
        self.lift()
        self.bind("<Escape>", lambda e: self.destroy())

    def _shift(self, months):
        y, m = divmod(self.month.month - 1 + months, 12)
        self.month = date(self.month.year + y, m + 1, 1)
        self._draw()

    def _draw(self):
        for w in self.body.winfo_children():
            w.destroy()

        head = tk.Frame(self.body, bg=CARD)
        head.grid(row=0, column=0, columnspan=7, sticky="we", pady=(0, 6))
        nav = dict(bg=CARD, fg=TEXT, font=(FONT, 12), cursor="hand2", padx=6)
        prev = tk.Label(head, text="\u2039", **nav)
        prev.pack(side="left")
        prev.bind("<Button-1>", lambda e: self._shift(-1))
        nxt = tk.Label(head, text="\u203a", **nav)
        nxt.pack(side="right")
        nxt.bind("<Button-1>", lambda e: self._shift(1))
        tk.Label(head, text=f"{MONTHS[self.lang][self.month.month - 1]} {self.month.year}",
                 bg=CARD, fg=TEXT, font=(FONT, 10, "bold")).pack()

        for col, name in enumerate(DAYS_SHORT[self.lang]):
            tk.Label(self.body, text=name, bg=CARD, fg=RED if col >= 5 else MUTED, font=(FONT, 8, "bold"),
                     width=4).grid(row=1, column=col, pady=(0, 2))

        today = date.today()
        weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(self.month.year, self.month.month)
        for row, week in enumerate(weeks, start=2):
            for col, d in enumerate(week):
                picked = d == self.selected
                bg = RED if picked else CARD
                fg = "white" if picked else (TEXT if d.month == self.month.month else "#c0c4ca")
                cell = tk.Label(self.body, text=str(d.day), bg=bg, fg=fg, width=4, pady=4, cursor="hand2",
                                font=(FONT, 9, "bold" if d == today or picked else "normal"))
                if d == today and not picked:
                    cell.configure(fg=RED)
                cell.grid(row=row, column=col, padx=1, pady=1)
                cell.bind("<Button-1>", lambda e, d=d: self._pick(d))
                if not picked:
                    cell.bind("<Enter>", lambda e, c=cell: c.configure(bg="#f6d5db"))
                    cell.bind("<Leave>", lambda e, c=cell: c.configure(bg=CARD))

    def _pick(self, d):
        self.on_pick(d)
        self.destroy()


# ---------- jendela pengaturan ----------

class SettingsDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root, bg=BG)
        self.app = app
        tr = app.tr
        self.title(tr("settings_title"))
        self.transient(app.root)
        self.resizable(False, False)
        self.grab_set()

        cfg = app.cfg
        self.v_name = tk.StringVar(value=cfg["name"])
        self.v_phone = tk.StringVar(value=cfg["phone"])
        self.v_start = tk.IntVar(value=cfg["start_hour"])
        self.v_end = tk.IntVar(value=cfg["end_hour"])
        self.v_lang = tk.StringVar(value=LANGS.get(cfg["lang"], LANGS["id"]))
        self.v_auto = tk.BooleanVar(value=autostart.is_enabled())

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=20, pady=16)
        left = tk.Frame(body, bg=BG, width=330)
        left.pack(side="left", fill="y", anchor="n")
        right = tk.Frame(body, bg=BG, width=330)
        right.pack(side="left", fill="y", anchor="n", padx=(16, 0))

        # Umum: identitas, bahasa, autostart.
        box = self._group(left, tr("general"))
        self._field(box, tr("name"), ttk.Entry(box, textvariable=self.v_name, width=40))
        self._field(box, tr("language"), ttk.Combobox(box, textvariable=self.v_lang, values=list(LANGS.values()),
                                                      state="readonly", width=14))
        ttk.Checkbutton(box, text=tr("autostart"), variable=self.v_auto, style="Card.TCheckbutton").pack(
            anchor="w", pady=(6, 0))

        # WhatsApp: nomor, grup report, jam kerja, chat yang diabaikan.
        box = self._group(right, tr("whatsapp"))
        self._account_row(box, app.wa_state is True, tr("wa_on"), tr("wa_off"), tr("wa_login"), self._relogin)
        self._field(box, tr("phone"), ttk.Entry(box, textvariable=self.v_phone, width=40))
        self._field(box, tr("group"), label(box, settings.REPORT_GROUP, 10, TEXT, True), tr("group_hint"))
        row = tk.Frame(box, bg=CARD)
        ttk.Spinbox(row, from_=0, to=23, textvariable=self.v_start, width=5).pack(side="left")
        label(row, tr("to"), 9, MUTED).pack(side="left", padx=8)
        ttk.Spinbox(row, from_=1, to=24, textvariable=self.v_end, width=5).pack(side="left")
        self._field(box, tr("work_hours"), row)
        self.exclude = tk.Text(box, height=3, width=40, font=(FONT, 9), relief="flat", bd=0,
                               highlightthickness=1, highlightbackground=BORDER, highlightcolor=RED,
                               padx=6, pady=4, wrap="word")
        self.exclude.insert("1.0", "; ".join(cfg["exclude"]))
        self._field(box, tr("advanced"), self.exclude)
        self.routine = tk.Text(box, height=3, width=40, font=(FONT, 9), relief="flat", bd=0,
                               highlightthickness=1, highlightbackground=BORDER, highlightcolor=RED,
                               padx=6, pady=4, wrap="word")
        self.routine.insert("1.0", "\n".join(cfg["routine"]))
        self._field(box, tr("routine"), self.routine, tr("routine_hint"))

        # Claude AI: status login akun Claude di laptop ini.
        box = self._group(left, tr("claude_section"))
        if app.claude_state == "missing":
            label(box, tr("claude_missing"), 9, MUTED).pack(anchor="w")
            label(box, tr("claude_install_hint"), 8, MUTED, wraplength=280, justify="left").pack(anchor="w", pady=(4, 0))
        else:
            self._account_row(box, app.claude_state == "on", tr("claude_on"), tr("claude_off"),
                              tr("claude_login"), self._claude_login)
            label(box, tr("claude_hint"), 8, MUTED, wraplength=280, justify="left").pack(anchor="w", pady=(8, 0))

        # Tentang: versi dan update.
        box = self._group(left, tr("about"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        label(row, f"{settings.APP_NAME}  ·  " + tr("version", v=updater.VERSION), 9, MUTED).pack(side="left")
        FlatButton(row, tr("check_update"), lambda: app.on_check_update(), small=True).pack(side="right")
        label(box, tr("credit"), 9, MUTED).pack(anchor="w", pady=(6, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=20, pady=(0, 16))
        FlatButton(foot, "\u23fb  " + tr("logout_all"), self._logout_all, "ghost").pack(side="left")
        FlatButton(foot, tr("save"), self._save, "primary").pack(side="right")
        FlatButton(foot, tr("cancel"), self.destroy).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + 40
        self.geometry(f"+{x}+{y}")

    def _group(self, parent, title):
        label(parent, title.upper(), 8, MUTED, True).pack(anchor="w", pady=(6, 4))
        box = RoundCard(parent)
        box.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(box.body, bg=CARD)
        inner.pack(fill="x", padx=14, pady=12)
        return inner

    def _field(self, parent, text, widget, hint=None):
        label(parent, text).pack(anchor="w", pady=(4, 2))
        widget.pack(in_=parent, anchor="w", fill="x" if isinstance(widget, (ttk.Entry, tk.Text)) else None)
        if hint:
            label(parent, hint, 8, MUTED).pack(anchor="w")

    def _read(self):
        try:
            start, end = int(self.v_start.get()), int(self.v_end.get())
        except (ValueError, tk.TclError):
            start, end = -1, -1
        if not 0 <= start < end <= 24:
            messagebox.showerror(settings.APP_NAME, self.app.tr("err_hours"), parent=self)
            return False
        lang = next(k for k, v in LANGS.items() if v == self.v_lang.get())
        self.app.cfg.update(
            name=self.v_name.get().strip(),
            phone=self.v_phone.get().strip(),
            start_hour=start,
            end_hour=end,
            exclude=[s.strip() for s in self.exclude.get("1.0", "end").split(";") if s.strip()],
            routine=[s.strip() for s in self.routine.get("1.0", "end").splitlines() if s.strip()],
            lang=lang,
        )
        settings.save(self.app.cfg)
        try:
            if self.v_auto.get() != autostart.is_enabled():
                autostart.set_enabled(self.v_auto.get())
        except OSError as e:
            messagebox.showerror(settings.APP_NAME, str(e), parent=self)
        return True

    def _save(self):
        if self._read():
            self.destroy()
            self.app.refresh()

    def _account_row(self, box, on, on_text, off_text, login_text, login_cmd):
        """Baris status akun (titik hijau/merah) dengan tombol Login."""
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x", pady=(0, 8))
        dot = tk.Canvas(row, width=10, height=10, bg=CARD, highlightthickness=0)
        dot.pack(side="left", padx=(0, 6))
        color = GREEN if on else RED
        dot.create_oval(1, 1, 9, 9, fill=color, outline=color)
        label(row, on_text if on else off_text, 9, TEXT).pack(side="left")
        FlatButton(row, login_text, login_cmd, "primary" if not on else "secondary", small=True).pack(side="right")

    def _logout_all(self):
        if self.app.busy:
            return
        if messagebox.askyesno(settings.APP_NAME, self.app.tr("confirm_logout_all"), parent=self):
            self.destroy()
            self.app.on_logout_all()

    def _claude_login(self):
        if self._read():
            self.destroy()
            self.app.refresh()
            self.app._claude_login(then=None)

    def _relogin(self):
        if self._read():
            self.destroy()
            self.app.refresh()
            self.app.on_login()


# ---------- jendela utama ----------

class App:
    def __init__(self, root):
        self.root = root
        self.cfg = settings.load()
        self.chats = {}
        self.events = queue.Queue()
        self.busy = False
        self.update_info = None
        self.update_dismissed = None
        # Status koneksi WhatsApp: None belum dicek, "checking", True, atau False.
        self.wa_state = None
        # Status Claude: None belum dicek, "on", "off" (belum login), "missing" (tidak terpasang).
        self.claude_state = None
        self.claude_cli = None
        self.history = history.load(settings.HISTORY_FILE)
        # Panel progres: None (belum ada proses) atau (persen, judul, keterangan, status).
        self.prog_state = None

        root.title(settings.APP_NAME)
        root.geometry("1220x780")
        root.minsize(1040, 640)
        sv_ttk.set_theme("light")
        # sv_ttk mewarnai ulang semua widget tk (tk_setPalette) saat event
        # <<ThemeChanged>>; tunggu event itu selesai supaya warna kartu,
        # sidebar, dan tombol merah di bawah tidak tertimpa.
        root.update()
        root.bind_class("Tk", "<<ThemeChanged>>", "")
        self._styles()
        try:
            self.icon = tk.PhotoImage(file=asset("icon.png"))
            root.iconphoto(True, self.icon)
            # Logo kop diperkecil dari 300x100 jadi 150x50.
            self.logo = tk.PhotoImage(file=asset("logo-wide.png")).subsample(2, 2)
        except tk.TclError:
            self.icon = self.logo = None

        self.v_date = tk.StringVar(value=fmt_day(date.today(), self.cfg["lang"]))
        self.status = tk.StringVar()
        # Pesan status (mis. "Report disalin") tampil di panel progres saat tidak ada proses berjalan.
        self.status.trace_add("write", lambda *_: self._status_to_panel())

        self._build()
        self._load_saved(date.today())
        root.after(150, self._poll)
        root.bind_all("<Button-1>", self._click_anywhere, add="+")
        # Kalender ikut tertutup kalau jendela utama dipindah atau diperkecil.
        root.bind("<Configure>", lambda e: e.widget is root and self._close_calendar(), add="+")
        # Saat app dibuka: cek koneksi WhatsApp (sekaligus riwayat report) dan versi baru.
        root.after(800, self.on_check_wa)
        root.after(1000, self.check_claude)
        root.after(1500, lambda: self.on_check_update(silent=True))

    @property
    def lang(self):
        return self.cfg["lang"]

    def tr(self, key, **kw):
        return t(self.lang, key, **kw)

    # ---------- tampilan ----------

    def _styles(self):
        s = ttk.Style()
        s.configure("Card.TCheckbutton", background=CARD, font=(FONT, 9))
        s.configure("Chat.Treeview", rowheight=30, font=(FONT, 10), background=CARD, fieldbackground=CARD,
                    borderwidth=0)
        s.configure("Chat.Treeview.Heading", font=(FONT, 9, "bold"), foreground=MUTED)

    def refresh(self):
        """Bangun ulang jendela, mis. setelah bahasa atau pengaturan diganti."""
        day = parse_day(self.v_date.get())
        if day:
            self.v_date.set(fmt_day(day, self.lang))
        self._build()

    def _build(self):
        draft = self.txt.get("1.0", "end-1c") if hasattr(self, "txt") else ""
        checked = set(self.table.checked()) if hasattr(self, "table") else None
        for w in self.root.winfo_children():
            if not isinstance(w, tk.Toplevel):
                w.destroy()
        self.root.configure(bg=BG)
        self.buttons = []

        self._build_sidebar()
        main = tk.Frame(self.root, bg=BG)
        main.pack(side="left", fill="both", expand=True)
        self._build_topbar(main)
        self._build_timeline(main)

        cols = tk.Frame(main, bg=BG)
        cols.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        cols.columnconfigure(0, weight=2, uniform="c")
        cols.columnconfigure(1, weight=3, uniform="c")
        cols.rowconfigure(0, weight=1)
        self._build_chats(cols)
        self._build_draft(cols)

        self.status.set(self.tr("ready"))
        self._show_chats(self.chats, checked)
        self.txt.insert("1.0", draft)
        self._show_wa_state()
        self._show_update()
        self._set_busy(self.busy)

    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=SIDE, width=270)
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Frame(self.root, bg=BORDER, width=1).pack(side="left", fill="y")
        inner = tk.Frame(side, bg=SIDE)
        inner.pack(fill="both", expand=True, padx=22, pady=20)

        # Kop: logo Tradecorp dengan garis merah di bawahnya.
        if self.logo:
            tk.Label(inner, image=self.logo, bg=SIDE).pack(anchor="w")
        tk.Frame(inner, bg=RED, height=3, width=56).pack(anchor="w", pady=(10, 18))

        # Status WhatsApp; klik untuk cek ulang.
        card_ = RoundCard(inner, radius=10)
        card_.pack(fill="x")
        pill = card_.body
        pill.configure(cursor="hand2")
        self.wa_dot = tk.Canvas(pill, width=12, height=12, bg=CARD, highlightthickness=0)
        self.wa_dot.pack(side="left", padx=(12, 8), pady=10)
        self.wa_label = label(pill, "", 9, TEXT, bg=CARD)
        self.wa_label.pack(side="left")
        for w in (card_, pill, self.wa_dot, self.wa_label):
            w.bind("<Button-1>", lambda e: self.on_check_wa())
        self.connect_slot = tk.Frame(inner, bg=SIDE)
        self.connect_slot.pack(fill="x")

        card_ = RoundCard(inner, radius=10)
        card_.pack(fill="x", pady=(8, 0))
        pill = card_.body
        pill.configure(cursor="hand2")
        self.ai_dot = tk.Canvas(pill, width=12, height=12, bg=CARD, highlightthickness=0)
        self.ai_dot.pack(side="left", padx=(12, 8), pady=10)
        self.ai_label = label(pill, "", 9, TEXT, bg=CARD)
        self.ai_label.pack(side="left")
        for w in (card_, pill, self.ai_dot, self.ai_label):
            w.bind("<Button-1>", lambda e: self.on_claude_click())
        self._show_claude_state()

        # Tanggal report dan dua tombol utama.
        label(inner, self.tr("report_date").upper(), 8, MUTED, True).pack(anchor="w", pady=(20, 4))
        # Kolom tanggal: klik untuk membuka kalender dropdown.
        entry = ttk.Entry(inner, textvariable=self.v_date, state="readonly", cursor="hand2")
        entry.pack(fill="x")
        entry.bind("<Button-1>", lambda e: self._open_calendar(entry))
        row = tk.Frame(inner, bg=SIDE)
        row.pack(fill="x", pady=(6, 0))
        FlatButton(row, self.tr("today"), lambda: self._set_day(0), small=True).pack(side="left", fill="x", expand=True)
        FlatButton(row, self.tr("yesterday"), lambda: self._set_day(1), small=True).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

        pull = FlatButton(inner, "↻  " + self.tr("pull"), self.on_pull)
        pull.pack(fill="x", pady=(20, 6))
        gen = FlatButton(inner, "✨  " + self.tr("generate"), self.on_generate, "primary")
        gen.pack(fill="x")
        self.buttons += [pull, gen]

        # Panel progres: nama proses, persentase, lalu "Complete" saat selesai.
        box = RoundCard(inner)
        box.pack(fill="x", pady=(16, 0))
        body = box.body
        row = tk.Frame(body, bg=CARD)
        row.pack(fill="x", padx=12, pady=(10, 0))
        self.prog_text = label(row, "", 9, TEXT, anchor="w", wraplength=105, justify="left")
        self.prog_text.pack(side="left", fill="x", expand=True)
        self.prog_pct = label(row, "", 9, TEXT, True)
        self.prog_pct.pack(side="right")
        self.prog_bar = ProgressBar(body)
        self.prog_bar.pack(fill="x", padx=12, pady=(6, 0))
        self.prog_note = label(body, "", 8, MUTED, anchor="w", wraplength=200, justify="left")
        self.prog_note.pack(fill="x", padx=12, pady=(4, 10))
        self._show_progress(self.prog_state)

        # Bagian bawah sidebar: pengaturan, versi, banner update.
        foot = tk.Frame(inner, bg=SIDE)
        foot.pack(side="bottom", fill="x")
        gear = FlatButton(foot, "⚙  " + self.tr("open_settings"), self.on_settings, anchor="w")
        gear.pack(fill="x", pady=(8, 8))
        self.buttons.append(gear)
        label(foot, self.tr("version", v=updater.VERSION) + "  ·  IT Support", 8, MUTED).pack(anchor="w")

    def _build_topbar(self, main):
        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", padx=24, pady=(20, 14))
        label(top, "HRGA Daily Report", 18, TEXT, True).pack(side="left")
        label(top, "PT Tradecorp Indonesia", 10, MUTED).pack(side="left", padx=(12, 0), pady=(8, 0))
        # Tempat banner "versi baru tersedia" di kanan atas.
        self.update_slot = tk.Frame(top, bg=BG)
        self.update_slot.pack(side="right")

    def _build_timeline(self, main):
        """Riwayat report ke grup untuk 5 hari kerja terakhir."""
        card_ = RoundCard(main)
        card_.pack(fill="x", padx=24, pady=(0, 14))
        box = card_.body
        label(box, self.tr("timeline_title"), 10, TEXT, True, bg=CARD).pack(anchor="w", padx=16, pady=(12, 0))
        self.timeline = tk.Canvas(box, height=78, bg=CARD, highlightthickness=0)
        self.timeline.pack(fill="x", padx=10, pady=(0, 6))
        self.timeline.bind("<Configure>", lambda e: self._draw_timeline())

    def _draw_timeline(self):
        c = self.timeline
        if not c.winfo_exists():
            return
        c.delete("all")
        w = max(c.winfo_width(), 500)
        if not self.cfg["group"]:
            c.create_text(w / 2, 38, text=self.tr("tl_nogroup"), fill=MUTED, font=(FONT, 10))
            return

        today = date.today()
        days = history.workdays(today)
        gap = w / len(days)
        xs = [gap * (i + 0.5) for i in range(len(days))]
        y, r = 26, 13
        for i in range(len(days) - 1):
            c.create_line(xs[i] + r + 6, y, xs[i + 1] - r - 6, y, fill=BORDER, width=2)

        for x, d in zip(xs, days):
            sent = self.history.get(d.isoformat())
            if sent:
                when = datetime.fromisoformat(sent)
                stamp = when.strftime("%H:%M") if when.date() == d else when.strftime("%d/%m %H:%M")
                color, mark, note = GREEN, "✓", self.tr("tl_sent", t=stamp)
            elif d == today:
                color, mark, note = AMBER, "•", self.tr("tl_today")
            else:
                color, mark, note = RED, "✕", self.tr("tl_missing")
            c.create_oval(x - r, y - r, x + r, y + r, fill=color, outline=color)
            c.create_text(x, y, text=mark, fill="white", font=(FONT, 10, "bold"))
            c.create_text(x, y + r + 12, text=f"{DAYS_SHORT[self.lang][d.weekday()]} {d:%d/%m}",
                          fill=TEXT, font=(FONT, 9, "bold"))
            c.create_text(x, y + r + 28, text=note, fill=color if not sent else MUTED, font=(FONT, 8))

    def _card_header(self, box, title, hint):
        head = tk.Frame(box, bg=CARD)
        head.pack(fill="x", padx=16, pady=(12, 0))
        label(head, title, 12, TEXT, True).pack(side="left")
        label(box, hint, 9, MUTED, bg=CARD).pack(anchor="w", padx=16, pady=(2, 10))
        return head

    def _build_chats(self, cols):
        card_ = RoundCard(cols, expand=True)
        card_.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        box = card_.body
        head = self._card_header(box, self.tr("chats_title"), self.tr("chats_hint"))
        FlatButton(head, self.tr("ignore"), self.on_ignore, "ghost", small=True).pack(side="right")
        self.table = ChatTable(box, (self.tr("col_chat"), self.tr("col_msgs"), self.tr("col_time")))
        self.table.pack(fill="both", expand=True, padx=6, pady=(0, 8))

    def _build_draft(self, cols):
        card_ = RoundCard(cols, expand=True)
        card_.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        box = card_.body
        head = self._card_header(box, self.tr("draft_title"), self.tr("draft_hint"))
        has_group = bool(self.cfg["group"])
        send = FlatButton(head, self.tr("send_group" if has_group else "send"),
                          self.on_send_group if has_group else self.on_send, "primary", small=True)
        send.pack(side="right")
        pdf = FlatButton(head, self.tr("pdf"), self.on_pdf, small=True)
        pdf.pack(side="right", padx=(0, 6))
        copy = FlatButton(head, self.tr("copy"), self.on_copy, small=True)
        copy.pack(side="right", padx=(0, 6))
        self.buttons += [send, pdf, copy]

        tk.Frame(box, bg=BORDER, height=1).pack(fill="x")
        frame = tk.Frame(box, bg=CARD)
        frame.pack(fill="both", expand=True, padx=(0, 6), pady=(0, 8))
        self.txt = tk.Text(frame, wrap="word", font=(FONT, 10), undo=True, relief="flat", bd=0,
                           bg=CARD, fg=TEXT, insertbackground=TEXT, selectbackground="#f6d5db",
                           selectforeground=TEXT, padx=18, pady=14, spacing1=2, spacing3=3,
                           highlightthickness=0)
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    def _show_claude_state(self):
        color, key = {
            "on": (GREEN, "claude_on"),
            "off": (AMBER, "claude_off"),
            "missing": ("#a0a4aa", "claude_missing"),
        }.get(self.claude_state, ("#a0a4aa", "claude_checking"))
        self.ai_dot.delete("all")
        self.ai_dot.create_oval(1, 1, 11, 11, fill=color, outline=color)
        self.ai_label.configure(text=self.tr(key))

    def _show_wa_state(self):
        color, key = {
            True: (GREEN, "wa_on"),
            False: (RED, "wa_off"),
            "checking": (AMBER, "wa_checking"),
        }.get(self.wa_state, ("#a0a4aa", "wa_unknown"))
        self.wa_dot.delete("all")
        self.wa_dot.create_oval(1, 1, 11, 11, fill=color, outline=color)
        self.wa_label.configure(text=self.tr(key))

        # Tombol hubungkan hanya muncul kalau WhatsApp belum login.
        for w in self.connect_slot.winfo_children():
            w.destroy()
        if self.wa_state is False:
            b = FlatButton(self.connect_slot, self.tr("connect_wa"), self.on_login, "primary", small=True)
            b.pack(fill="x", pady=(8, 0))
            self.buttons.append(b)

    def _show_update(self):
        """Banner di bar atas kalau ada versi baru di GitHub; bisa ditutup dengan x."""
        for w in self.update_slot.winfo_children():
            w.destroy()
        if not self.update_info or self.update_dismissed == self.update_info["version"]:
            return
        banner = RoundCard(self.update_slot, radius=10)
        banner.pack()
        body = banner.body
        label(body, "\u2b06", 11, RED, True, bg=CARD).pack(side="left", padx=(12, 6), pady=6)
        label(body, self.tr("update_available", v=self.update_info["version"]), 9, TEXT, True, bg=CARD).pack(side="left")
        close = label(body, "\u2715", 9, MUTED, bg=CARD, cursor="hand2")
        close.pack(side="right", padx=(8, 12))
        close.bind("<Button-1>", lambda e: self._dismiss_update())
        b = FlatButton(body, self.tr("update_now"), self.on_update, "primary", small=True)
        b.pack(side="right", padx=(12, 0), pady=6)
        self.buttons.append(b)

    def _dismiss_update(self):
        # Ditutup sampai app dibuka lagi; versi baru tetap bisa dipasang lewat Pengaturan > Cek update.
        self.update_dismissed = self.update_info["version"]
        self._show_update()

    # ---------- utilitas ----------

    def _status_to_panel(self):
        if not self.busy and hasattr(self, "prog_note") and self.prog_note.winfo_exists():
            text = self.status.get()
            # "Siap." sudah tampil sebagai judul panel saat belum ada proses.
            self.prog_note.configure(text="" if text == self.tr("ready") else text)

    def _show_progress(self, state):
        """state: None, atau (persen, judul, keterangan, "run"/"done"/"error")."""
        self.prog_state = state
        if not state:
            self.prog_text.configure(text=self.tr("ready"))
            self.prog_pct.configure(text="")
            self.prog_note.configure(text="")
            self.prog_bar.set(0)
            return
        pct, title, note, kind = state
        color = {"done": GREEN, "error": RED}.get(kind, TEXT)
        text = {"done": "Complete \u2713", "error": self.tr("failed").rstrip(": ")}.get(kind, f"{pct}%")
        self.prog_text.configure(text=title)
        self.prog_pct.configure(text=text, fg=color)
        self.prog_note.configure(text=note)
        self.prog_bar.set(pct, GREEN if kind == "done" else RED)

    def _progress(self, pct, note=""):
        """Dipanggil dari thread kerja: perbarui persentase panel progres."""
        self.events.put(("progress", (int(pct), note)))

    def _open_calendar(self, entry):
        if self._close_calendar():
            return
        self.calendar = CalendarPopup(entry, parse_day(self.v_date.get()), self.lang,
                                      lambda d: self.v_date.set(fmt_day(d, self.lang)))
        self.calendar_entry = entry
        return "break"

    def _close_calendar(self):
        cal = getattr(self, "calendar", None)
        if cal is not None and cal.winfo_exists():
            cal.destroy()
            return True
        return False

    def _click_anywhere(self, e):
        """Klik di luar kalender (dan bukan di kolom tanggal) menutup kalender."""
        cal = getattr(self, "calendar", None)
        if cal is None or not cal.winfo_exists():
            return
        w = e.widget
        if isinstance(w, str) or w is getattr(self, "calendar_entry", None):
            return
        if str(w).startswith(str(cal)):
            return
        cal.destroy()

    def _set_day(self, back):
        self.v_date.set(fmt_day(date.today() - timedelta(days=back), self.lang))

    def _set_busy(self, on):
        self.busy = on
        for b in self.buttons:
            if b.winfo_exists():
                b.configure(state="disabled" if on else "normal")


    def _read_day(self):
        day = parse_day(self.v_date.get())
        if day is None:
            messagebox.showerror(settings.APP_NAME, self.tr("err_form"))
            return None
        # Tampilkan ulang lengkap dengan nama harinya.
        self.v_date.set(fmt_day(day, self.lang))
        return day

    def _run(self, label_text, work):
        """Jalankan pekerjaan browser di thread lain supaya jendela tidak macet."""
        if self.busy:
            return
        self._set_busy(True)
        self.status.set(label_text)
        self._show_progress((0, label_text, "", "run"))

        def target():
            ok = False
            try:
                work()
                ok = True
            except Exception as e:
                log.exception("Gagal: %s", label_text)
                self.events.put(("error", str(e)))
            finally:
                self.events.put(("finish", ok))
                self.events.put(("done", None))

        threading.Thread(target=target, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "status":
                    self.status.set(value)
                elif kind == "chats":
                    self._show_chats(value)
                elif kind == "info":
                    self.status.set(value)
                    messagebox.showinfo(settings.APP_NAME, value)
                elif kind == "error":
                    self.status.set(self.tr("failed") + value)
                    messagebox.showerror(settings.APP_NAME, value)
                elif kind == "claude":
                    self.claude_state = value
                    self._show_claude_state()
                elif kind == "draft":
                    day, text, note = value
                    self._set_draft(day, text)
                    self.status.set(note)
                    if note != self.tr("generated"):
                        messagebox.showinfo(settings.APP_NAME, note)
                elif kind == "wa":
                    self.wa_state = value
                    self._show_wa_state()
                elif kind == "history":
                    self.history = value
                    self._draw_timeline()
                elif kind == "update":
                    self.update_info = value
                    self._show_update()
                elif kind == "quit":
                    self.root.destroy()
                    return
                elif kind == "progress":
                    pct, note = value
                    if self.prog_state:
                        self._show_progress((pct, self.prog_state[1], note or self.prog_state[2], "run"))
                elif kind == "finish":
                    if self.prog_state:
                        pct, title, note, _ = self.prog_state
                        self._show_progress((100, title, self.status.get(), "done") if value
                                            else (pct, title, note, "error"))
                elif kind == "done":
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.root.after(150, self._poll)

    def _show_chats(self, chats, checked=None):
        self.chats = chats
        day = self._read_day_quiet()
        rows = []
        for name, msgs in chats.items():
            inside = [m for m in msgs if day and in_window(m, day, self.cfg["start_hour"], self.cfg["end_hour"])]
            span = f"{inside[0]['time'][11:16]}–{inside[-1]['time'][11:16]}" if inside else "-"
            rows.append((name, len(inside), span))
        self.table.set_rows(rows, checked, self.tr("no_chats_yet"))

    def _read_day_quiet(self):
        return parse_day(self.v_date.get())

    def _load_saved(self, day):
        try:
            with open(raw_path(day), encoding="utf-8") as f:
                self._show_chats(json.load(f))
        except (OSError, ValueError):
            pass
        try:
            with open(report_path(day), encoding="utf-8") as f:
                self.txt.insert("1.0", f.read())
        except OSError:
            pass

    def _report_text(self):
        return self.txt.get("1.0", "end").strip()

    def _scan_history(self, wa):
        """Baca grup report dan perbarui riwayat (dipanggil di thread browser)."""
        group = self.cfg["group"]
        if not group:
            return
        self.events.put(("status", self.tr("history_checking")))
        since = history.workdays(date.today())[0]
        found = history.from_messages(wa.report_messages(group, since))
        self.events.put(("history", history.merge(settings.HISTORY_FILE, found)))

    # ---------- aksi ----------

    def on_settings(self):
        SettingsDialog(self)

    def on_check_wa(self):
        """Cek apakah sesi WhatsApp Web masih login, sekaligus riwayat report di grup."""
        if self.busy:
            return

        def work():
            self._progress(10)
            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                self._progress(30)
                ok = wa.wait_ready(timeout_s=40, sync_wait_s=20)
                self.events.put(("wa", ok))
                self._progress(70)
                if ok:
                    self._scan_history(wa)
            self.events.put(("status", self.tr("wa_on" if ok else "wa_off")))

        self.wa_state = "checking"
        self._show_wa_state()
        self._run(self.tr("wa_checking"), work)

    def on_check_update(self, silent=False):
        """Cek rilis terbaru di GitHub; tidak memakai browser, jadi jalan terpisah."""
        if not silent:
            self.status.set(self.tr("checking"))

        def target():
            try:
                info = updater.check()
            except Exception as e:
                log.warning("Cek update gagal: %s", e)
                if not silent:
                    self.events.put(("error", self.tr("update_failed") + str(e)))
                return
            if not silent:
                self.update_dismissed = None
            self.events.put(("update", info))
            if info is None and not silent:
                self.events.put(("info", self.tr("up_to_date", v=updater.VERSION)))

        threading.Thread(target=target, daemon=True).start()

    def on_update(self):
        info = self.update_info
        if not info:
            return
        if not updater.can_self_update():
            messagebox.showinfo(settings.APP_NAME, self.tr("update_dev", v=info["version"]))
            return
        if not messagebox.askyesno(settings.APP_NAME, self.tr("confirm_update", v=info["version"])):
            return

        def work():
            path = updater.download(info["url"], lambda p: self._progress(p * 0.95, self.tr("downloading", p=p)))
            updater.install(path)
            self.events.put(("quit", None))

        self._run(self.tr("downloading", p=0), work)

    def on_ignore(self):
        """Chat yang tidak dicentang masuk daftar abaikan dan tidak dibaca lagi."""
        names = self.table.unchecked()
        if not names:
            return
        self.cfg["exclude"] = self.cfg["exclude"] + [n for n in names if n not in self.cfg["exclude"]]
        settings.save(self.cfg)
        self._show_chats({n: m for n, m in self.chats.items() if n not in names})
        self.status.set(self.tr("ignored", n=len(names)))

    def on_login(self):
        def work():
            self.events.put(("status", self.tr("scan_qr")))
            self._progress(20, self.tr("scan_qr"))
            with WhatsApp(settings.PROFILE_DIR, headless=False) as wa:
                ok = wa.wait_ready(timeout_s=300)
                self.events.put(("wa", ok))
                if not ok:
                    raise RuntimeError(self.tr("qr_timeout"))
                self._scan_history(wa)
            self.events.put(("info", self.tr("logged_in")))

        self._run(self.tr("opening"), work)

    def on_pull(self):
        day = self._read_day()
        if day is None:
            return
        exclude = set(self.cfg["exclude"])
        phone, group = self.cfg["phone"], self.cfg["group"]

        def work():
            def progress(i, n, name):
                text = self.tr("reading", i=i, n=n, name=name)
                self.events.put(("status", text))
                # Membaca chat mengisi 20% sampai 90%.
                self._progress(20 + 70 * (i - 1) / max(n, 1), text)

            self._progress(5)
            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                self._progress(10)
                ok = wa.wait_ready()
                self.events.put(("wa", ok))
                if not ok:
                    raise RuntimeError(self.tr("not_logged_in"))
                self.events.put(("status", self.tr("listing")))
                self._progress(15, self.tr("listing"))
                # Grup report tidak ikut dibaca sebagai pekerjaan.
                names = [n for n in wa.list_chats(day, date.today())
                         if n not in exclude and n != group and not is_self_chat(n, phone)]
                chats = wa.read_chats(names, day, progress)
                self._progress(92, self.tr("history_checking"))
                self._scan_history(wa)

            chats = {n: m for n, m in chats.items() if m}
            settings.ensure_dirs()
            with open(raw_path(day), "w", encoding="utf-8") as f:
                json.dump(chats, f, ensure_ascii=False, indent=1)
            self.events.put(("chats", chats))
            self.events.put(("status", self.tr("pulled", n=len(chats))))

        self._run(self.tr("opening"), work)

    def check_claude(self):
        """Cek Claude Code di laptop ini dan status loginnya (tanpa membuka jendela)."""
        def target():
            cli = claude_ai.find_cli()
            if not cli:
                self.events.put(("claude", "missing"))
                return
            self.claude_cli = cli
            try:
                ok = claude_ai.status(cli).get("loggedIn")
            except Exception as e:
                log.warning("Cek status Claude gagal: %s", e)
                ok = False
            self.events.put(("claude", "on" if ok else "off"))

        threading.Thread(target=target, daemon=True).start()

    def on_logout_all(self):
        """Logout WhatsApp (hapus profil browser app) dan akun Claude sekaligus."""
        # Sesi WhatsApp Web tersimpan di profil browser app; menghapusnya = logout dari app ini.
        shutil.rmtree(settings.PROFILE_DIR, ignore_errors=True)
        self.wa_state = False
        self._show_wa_state()
        if self.claude_cli and self.claude_state == "on":
            try:
                claude_ai.logout(self.claude_cli)
            except Exception as e:
                log.warning("Logout Claude gagal: %s", e)
            self.claude_state = "off"
            self._show_claude_state()
        self._show_progress((100, self.tr("logout_all"), "", "done"))
        self.status.set(self.tr("logged_out_all"))
        messagebox.showinfo(settings.APP_NAME, self.tr("logged_out_all"))

    def on_claude_click(self):
        if self.claude_state == "off" and not self.busy:
            self._claude_login(then=None)
        else:
            self.check_claude()

    def _claude_login(self, then):
        """Buka login akun Claude, tunggu sampai selesai, lalu jalankan then() kalau ada."""
        claude_ai.login(self.claude_cli)

        def work():
            self._progress(10, self.tr("claude_waiting_login"))
            for i in range(90):
                time.sleep(2)
                if claude_ai.status(self.claude_cli).get("loggedIn"):
                    self.events.put(("claude", "on"))
                    if then:
                        then()
                    return
                self._progress(10 + i * 0.4, self.tr("claude_waiting_login"))
            raise RuntimeError(self.tr("claude_login_timeout"))

        self._run(self.tr("claude_waiting_login"), work)

    def _set_draft(self, day, text):
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        settings.ensure_dirs()
        with open(report_path(day), "w", encoding="utf-8") as f:
            f.write(text)

    def on_generate(self):
        day = self._read_day()
        if day is None:
            return
        if not self.chats:
            messagebox.showinfo(settings.APP_NAME, self.tr("no_chats"))
            return

        picked = {n: self.chats[n] for n in self.table.checked()}
        args = (picked, day, self.cfg["name"], self.cfg["start_hour"], self.cfg["end_hour"], self.lang,
                self.cfg["routine"])

        def fallback(reason):
            text = build_report(*args)
            note = self.tr("claude_fallback", e=reason) if reason else self.tr("generated")
            return day, text, note

        # Tanpa Claude: langsung susun draf tanpa AI.
        if self.claude_state == "missing" or not self.claude_cli:
            day_, text, _ = fallback(None)
            self._set_draft(day_, text)
            self.status.set(self.tr("generated"))
            return

        def with_claude():
            self._progress(15, self.tr("preparing"))
            prompt = claude_ai.build_prompt(*args)
            title = report_title(day, self.cfg["name"], self.lang)

            # Claude butuh waktu 20-90 detik; progres dinaikkan pelan sampai 90%.
            done = threading.Event()

            def tick():
                pct = 25
                while not done.wait(2) and pct < 90:
                    pct += 3
                    self._progress(pct, self.tr("claude_writing"))

            threading.Thread(target=tick, daemon=True).start()
            try:
                text = claude_ai.generate(self.claude_cli, prompt, title)
                result = (day, text, self.tr("generated"))
            except Exception as e:
                log.warning("Claude gagal: %s", e)
                result = fallback(str(e)[:160])
            finally:
                done.set()
            self.events.put(("draft", result))

        if self.claude_state == "off":
            # Belum login: tawarkan login sekali; kalau ditolak, pakai draf tanpa AI.
            if messagebox.askyesno(settings.APP_NAME, self.tr("claude_ask_login")):
                self._claude_login(then=with_claude)
            else:
                day_, text, _ = fallback(None)
                self._set_draft(day_, text)
                self.status.set(self.tr("generated"))
            return

        self._run(self.tr("claude_writing"), with_claude)

    def on_copy(self):
        text = self._report_text()
        if not text:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set(self.tr("copied"))

    def on_pdf(self):
        day = self._read_day()
        if day is None:
            return
        text = self._report_text()
        if not text:
            messagebox.showinfo(settings.APP_NAME, self.tr("empty_draft"))
            return
        settings.ensure_dirs()
        path = save_pdf(text, report_path(day, "pdf"), asset("logo-wide.png"))
        self.status.set(self.tr("pdf_saved", path=path))
        os.startfile(path)

    def _prepare_send(self, question):
        day = self._read_day()
        text = self._report_text()
        if day is None:
            return None
        if not text:
            messagebox.showinfo(settings.APP_NAME, self.tr("empty_draft"))
            return None
        if not messagebox.askyesno(settings.APP_NAME, question):
            return None
        # Simpan hasil edit supaya tidak hilang.
        settings.ensure_dirs()
        with open(report_path(day), "w", encoding="utf-8") as f:
            f.write(text)
        return day, text

    def on_send(self):
        phone = self.cfg["phone"]
        if not phone:
            messagebox.showinfo(settings.APP_NAME, self.tr("need_phone"))
            return
        prepared = self._prepare_send(self.tr("confirm_send"))
        if not prepared:
            return
        _, text = prepared

        def work():
            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                ok = wa.wait_ready()
                self.events.put(("wa", ok))
                if not ok:
                    raise RuntimeError(self.tr("not_logged_in"))
                self.events.put(("status", self.tr("sending")))
                self._progress(60, self.tr("sending"))
                if not wa.send_to_self(to_wa_number(phone), text):
                    raise RuntimeError(self.tr("send_unsure"))
            self.events.put(("info", self.tr("sent")))

        self._run(self.tr("opening"), work)

    def on_send_group(self):
        group = self.cfg["group"]
        prepared = self._prepare_send(self.tr("confirm_send_group", g=group))
        if not prepared:
            return
        day, text = prepared

        def work():
            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                ok = wa.wait_ready()
                self.events.put(("wa", ok))
                if not ok:
                    raise RuntimeError(self.tr("not_logged_in"))
                self.events.put(("status", self.tr("sending")))
                self._progress(60, self.tr("sending"))
                if not wa.send_to_chat(group, text):
                    raise RuntimeError(self.tr("send_unsure"))
            self.events.put(("history", history.mark_sent(settings.HISTORY_FILE, day)))
            self.events.put(("info", self.tr("sent_group", g=group)))

        self._run(self.tr("opening"), work)


def main():
    settings.ensure_dirs()
    logging.basicConfig(
        filename=settings.LOG_FILE,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        encoding="utf-8",
    )
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
