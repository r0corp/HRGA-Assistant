"""HRGA WA Report: tarik chat WhatsApp lalu susun draf daily report."""

import json
import logging
import os
import queue
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

import sv_ttk

from core import autostart, history, settings, updater
from core.i18n import DAYS_SHORT, LANGS, t
from core.pdf import save_pdf
from core.reader import WhatsApp, is_self_chat
from core.summary import build_report, in_window


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


def to_wa_number(phone):
    """0812... -> 62812...; nomor yang sudah berawalan 62 dibiarkan."""
    d = "".join(c for c in phone if c.isdigit())
    return "62" + d[1:] if d.startswith("0") else d


# ---------- komponen ----------

class FlatButton(tk.Button):
    """Tombol datar: "primary" merah, "secondary" putih bergaris, "ghost" tanpa garis."""

    COLORS = {
        "primary": (RED, "white", RED_DARK),
        "secondary": (CARD, TEXT, "#f1f3f5"),
        "ghost": (None, RED, None),
    }

    def __init__(self, parent, text, command, kind="secondary", small=False, **kw):
        bg, fg, hover = self.COLORS[kind]
        bg = bg or parent["bg"]
        hover = hover or bg
        super().__init__(
            parent, text=text, command=command, bg=bg, fg=fg,
            activebackground=hover, activeforeground=fg, disabledforeground="#b0b4ba",
            relief="flat", bd=0, cursor="hand2",
            font=(FONT, 9 if small else 10, "bold" if kind == "primary" else "normal"),
            padx=10 if small else 14, pady=4 if small else 8,
            highlightthickness=1 if kind == "secondary" else 0,
            highlightbackground=BORDER, highlightcolor=BORDER, **kw,
        )
        self.bind("<Enter>", lambda e: str(self["state"]) != "disabled" and self.configure(bg=hover))
        self.bind("<Leave>", lambda e: self.configure(bg=bg))


def label(parent, text, size=9, color=TEXT, bold=False, **kw):
    kw.setdefault("bg", parent["bg"])
    return tk.Label(parent, text=text, fg=color, font=(FONT, size, "bold" if bold else "normal"), **kw)


def card(parent):
    return tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)


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

        # Umum: identitas, bahasa, autostart.
        box = self._group(body, tr("general"))
        self._field(box, tr("name"), ttk.Entry(box, textvariable=self.v_name, width=40))
        self._field(box, tr("language"), ttk.Combobox(box, textvariable=self.v_lang, values=list(LANGS.values()),
                                                      state="readonly", width=14))
        ttk.Checkbutton(box, text=tr("autostart"), variable=self.v_auto, style="Card.TCheckbutton").pack(
            anchor="w", pady=(6, 0))

        # WhatsApp: nomor, grup report, jam kerja, chat yang diabaikan.
        box = self._group(body, tr("whatsapp"))
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
        FlatButton(box, tr("relogin"), self._relogin, small=True).pack(anchor="w", pady=(8, 0))

        # Tentang: versi dan update.
        box = self._group(body, tr("about"))
        row = tk.Frame(box, bg=CARD)
        row.pack(fill="x")
        label(row, f"{settings.APP_NAME}  ·  " + tr("version", v=updater.VERSION), 9, MUTED).pack(side="left")
        FlatButton(row, tr("check_update"), lambda: app.on_check_update(), small=True).pack(side="right")
        label(box, tr("credit"), 9, MUTED).pack(anchor="w", pady=(6, 0))

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", padx=20, pady=(0, 16))
        FlatButton(foot, tr("save"), self._save, "primary").pack(side="right")
        FlatButton(foot, tr("cancel"), self.destroy).pack(side="right", padx=(0, 8))

        self.update_idletasks()
        x = app.root.winfo_rootx() + (app.root.winfo_width() - self.winfo_width()) // 2
        y = app.root.winfo_rooty() + 40
        self.geometry(f"+{x}+{y}")

    def _group(self, parent, title):
        label(parent, title.upper(), 8, MUTED, True).pack(anchor="w", pady=(6, 4))
        box = card(parent)
        box.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(box, bg=CARD)
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
        # Status koneksi WhatsApp: None belum dicek, "checking", True, atau False.
        self.wa_state = None
        self.history = history.load(settings.HISTORY_FILE)

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

        self.v_date = tk.StringVar(value=date.today().isoformat())
        self.status = tk.StringVar()

        self._build()
        self._load_saved(date.today())
        root.after(150, self._poll)
        # Saat app dibuka: cek koneksi WhatsApp (sekaligus riwayat report) dan versi baru.
        root.after(800, self.on_check_wa)
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
        s.configure("TProgressbar", thickness=4)
        s.configure("Chat.Treeview", rowheight=30, font=(FONT, 10), background=CARD, fieldbackground=CARD,
                    borderwidth=0)
        s.configure("Chat.Treeview.Heading", font=(FONT, 9, "bold"), foreground=MUTED)

    def refresh(self):
        """Bangun ulang jendela, mis. setelah bahasa atau pengaturan diganti."""
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
        self._build_statusbar(main)
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
        pill = card(inner)
        pill.configure(cursor="hand2")
        pill.pack(fill="x")
        self.wa_dot = tk.Canvas(pill, width=12, height=12, bg=CARD, highlightthickness=0)
        self.wa_dot.pack(side="left", padx=(12, 8), pady=10)
        self.wa_label = label(pill, "", 9, TEXT, bg=CARD)
        self.wa_label.pack(side="left")
        for w in (pill, self.wa_dot, self.wa_label):
            w.bind("<Button-1>", lambda e: self.on_check_wa())
        self.connect_slot = tk.Frame(inner, bg=SIDE)
        self.connect_slot.pack(fill="x")

        # Tanggal report dan dua tombol utama.
        label(inner, self.tr("report_date").upper(), 8, MUTED, True).pack(anchor="w", pady=(20, 4))
        ttk.Entry(inner, textvariable=self.v_date).pack(fill="x")
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

        # Bagian bawah sidebar: pengaturan, versi, banner update.
        foot = tk.Frame(inner, bg=SIDE)
        foot.pack(side="bottom", fill="x")
        self.update_slot = tk.Frame(foot, bg=SIDE)
        self.update_slot.pack(fill="x")
        gear = FlatButton(foot, "⚙  " + self.tr("open_settings"), self.on_settings, anchor="w")
        gear.pack(fill="x", pady=(8, 8))
        self.buttons.append(gear)
        label(foot, self.tr("version", v=updater.VERSION) + "  ·  IT Support", 8, MUTED).pack(anchor="w")

    def _build_topbar(self, main):
        top = tk.Frame(main, bg=BG)
        top.pack(fill="x", padx=24, pady=(20, 14))
        label(top, "HRGA Daily Report", 18, TEXT, True).pack(side="left")
        label(top, "PT Tradecorp Indonesia", 10, MUTED).pack(side="left", padx=(12, 0), pady=(8, 0))

    def _build_timeline(self, main):
        """Riwayat report ke grup untuk 5 hari kerja terakhir."""
        box = card(main)
        box.pack(fill="x", padx=24, pady=(0, 14))
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
        box = card(cols)
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        head = self._card_header(box, self.tr("chats_title"), self.tr("chats_hint"))
        FlatButton(head, self.tr("ignore"), self.on_ignore, "ghost", small=True).pack(side="right")
        self.table = ChatTable(box, (self.tr("col_chat"), self.tr("col_msgs"), self.tr("col_time")))
        self.table.pack(fill="both", expand=True, padx=1, pady=(0, 1))

    def _build_draft(self, cols):
        box = card(cols)
        box.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
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
        frame.pack(fill="both", expand=True)
        self.txt = tk.Text(frame, wrap="word", font=(FONT, 10), undo=True, relief="flat", bd=0,
                           bg=CARD, fg=TEXT, insertbackground=TEXT, selectbackground="#f6d5db",
                           selectforeground=TEXT, padx=18, pady=14, spacing1=2, spacing3=3,
                           highlightthickness=0)
        bar = ttk.Scrollbar(frame, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.txt.pack(side="left", fill="both", expand=True)

    def _build_statusbar(self, main):
        bar = tk.Frame(main, bg=BG)
        bar.pack(fill="x", side="bottom", padx=24, pady=(0, 10))
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=160)
        label(bar, "", 9, MUTED, textvariable=self.status).pack(side="left")

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
        """Banner di sidebar kalau ada versi baru."""
        for w in self.update_slot.winfo_children():
            w.destroy()
        if not self.update_info:
            return
        label(self.update_slot, self.tr("update_available", v=self.update_info["version"]), 9, RED, True).pack(
            anchor="w", pady=(0, 4))
        b = FlatButton(self.update_slot, self.tr("update_now"), self.on_update, "primary", small=True)
        b.pack(fill="x")
        self.buttons.append(b)

    # ---------- utilitas ----------

    def _set_day(self, back):
        self.v_date.set((date.today() - timedelta(days=back)).isoformat())

    def _set_busy(self, on):
        self.busy = on
        for b in self.buttons:
            if b.winfo_exists():
                b.configure(state="disabled" if on else "normal")
        if on:
            self.progress.pack(side="right")
            self.progress.start(12)
        else:
            self.progress.stop()
            self.progress.pack_forget()

    def _read_day(self):
        try:
            return date.fromisoformat(self.v_date.get().strip())
        except ValueError:
            messagebox.showerror(settings.APP_NAME, self.tr("err_form"))
            return None

    def _run(self, label_text, work):
        """Jalankan pekerjaan browser di thread lain supaya jendela tidak macet."""
        if self.busy:
            return
        self._set_busy(True)
        self.status.set(label_text)

        def target():
            try:
                work()
            except Exception as e:
                log.exception("Gagal: %s", label_text)
                self.events.put(("error", str(e)))
            finally:
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
        try:
            return date.fromisoformat(self.v_date.get().strip())
        except ValueError:
            return None

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
            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                ok = wa.wait_ready(timeout_s=40, sync_wait_s=20)
                self.events.put(("wa", ok))
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
            path = updater.download(info["url"], lambda p: self.events.put(("status", self.tr("downloading", p=p))))
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
                self.events.put(("status", self.tr("reading", i=i, n=n, name=name)))

            with WhatsApp(settings.PROFILE_DIR, headless=True) as wa:
                ok = wa.wait_ready()
                self.events.put(("wa", ok))
                if not ok:
                    raise RuntimeError(self.tr("not_logged_in"))
                self.events.put(("status", self.tr("listing")))
                # Grup report tidak ikut dibaca sebagai pekerjaan.
                names = [n for n in wa.list_chats(day, date.today())
                         if n not in exclude and n != group and not is_self_chat(n, phone)]
                chats = wa.read_chats(names, day, progress)
                self._scan_history(wa)

            chats = {n: m for n, m in chats.items() if m}
            settings.ensure_dirs()
            with open(raw_path(day), "w", encoding="utf-8") as f:
                json.dump(chats, f, ensure_ascii=False, indent=1)
            self.events.put(("chats", chats))
            self.events.put(("status", self.tr("pulled", n=len(chats))))

        self._run(self.tr("opening"), work)

    def on_generate(self):
        day = self._read_day()
        if day is None:
            return
        if not self.chats:
            messagebox.showinfo(settings.APP_NAME, self.tr("no_chats"))
            return

        picked = {n: self.chats[n] for n in self.table.checked()}
        text = build_report(picked, day, self.cfg["name"], self.cfg["start_hour"], self.cfg["end_hour"], self.lang)

        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", text)
        settings.ensure_dirs()
        with open(report_path(day), "w", encoding="utf-8") as f:
            f.write(text)
        self.status.set(self.tr("generated"))

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
