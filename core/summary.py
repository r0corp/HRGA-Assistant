"""Menyusun draf daily report dari chat tanpa AI.

Chat dikelompokkan per jenis pekerjaan berdasarkan kata kunci, lalu ditulis
dengan format daily report: satu poin per pekerjaan, sub-poin per orang,
dan status (selesai / dalam proses) dari pesan-pesan sesudahnya.
"""

import random
import re
from datetime import datetime

from core.i18n import DAYS, MONTHS, t
from core.redact import redact

# Kata basa-basi; pesan yang seluruh katanya dari daftar ini dibuang.
FILLER_WORD_RE = re.compile(
    r"(?i)^(ok|oke+|okey|okay|siap+|sip+|noted|thanks?|thank|you|thx|tq|tks|makasih|"
    r"terima|kasih|sama|iya+|ya+|y|yo+|baik|aman|mantap|done|beres|wkwk\w*|haha\w*|"
    r"hehe\w*|hihi\w*|alhamdulillah|pagi|siang|sore|malam|halo|hai+|p|pak|bu|mba|mbak|"
    r"mas|bang|kak|dek|deh|dong|nya|ok-ok|sama-sama)$"
)

# Penanda lampiran dari WhatsApp Web.
MEDIA_RE = re.compile(
    r"(?i)^(\d+\s+)?(photo|photos|image|video|videos|sticker|gif|audio|voice message|"
    r"document|foto|gambar|stiker|pesan suara)s?$"
)

# Pesan sosial yang bukan pekerjaan (ucapan duka, ulang tahun, dsb.).
SOCIAL_RE = re.compile(r"(?i)berduka|innalillahi|inna lillahi|ulang tahun|\bhbd\b|met milad|selamat menempuh")

# Tanda pekerjaan sudah beres, dicari di pesan sesudah permintaan.
DONE_RE = re.compile(
    r"(?i)\b(sudah|udah|udh|dah)\s+(bisa|aman|normal|beres|selesai|oke|ok|jalan|masuk|"
    r"terkirim|dikirim|diganti|diperbaiki|dibenerin|diinput|diproses|di ?update)\b|"
    r"\b(aman|beres|selesai|done|berhasil|normal kembali)\b"
)

URL_RE = re.compile(r"https?://([^/\s:]+)\S*")
MENTION_RE = re.compile(r"@\S+\s*")

MAX_CHARS = 120

# (kunci, judul Indonesia, judul Inggris, pola kata kunci). Urutan menentukan
# pemenang kalau skor sama.
TOPICS = [
    ("storage", "Penanganan storage SharePoint/OneDrive", "SharePoint/OneDrive storage support",
     r"sharepoint|onedrive|one drive|storage|free ?up|penyimpanan|space|sinkron|sync"),
    ("printer", "Penanganan printer dan scan", "Printer and scanner support",
     r"printer|\bprint|kyocera|\bscan|fotokopi|fotocopy|toner|tinta|kertas"),
    ("email", "Penanganan email", "Email support",
     r"\bemail|e-mail|outlook|mailbox|inbox"),
    ("network", "Penanganan jaringan dan internet", "Network and internet support",
     r"wifi|wi-fi|internet|jaringan|koneksi|\blan\b|router|indibiz|bandwidth|lemot"),
    ("device", "Penanganan laptop/PC", "Laptop/PC support",
     r"laptop|komputer|\bpc\b|windows|instal|speaker|keyboard|mouse|monitor|\bssd\b|\bram\b|"
     r"charger|baterai|layar|webcam"),
    ("atk", "Pengelolaan ATK dan stok", "Stationery and stock management",
     r"\batk\b|\bstok|\bstock|opname|pantry|alat tulis"),
    ("procurement", "Pengajuan dan pembelian", "Requests and purchasing",
     r"\bpr\b|\bpo\b|pengajuan|pembelian|\bbeli\b|quotation|penawaran|harga|invoice|tagihan|vendor"),
    ("vehicle", "Maintenance kendaraan", "Vehicle maintenance",
     r"mobil|motor|kendaraan|servis|service|bensin|\bbbm\b|forklift|\boli\b"),
    ("facility", "Fasilitas gedung dan kantor", "Building and office facilities",
     r"cctv|\bac\b|lampu|stop ?kontak|listrik|ruangan|gedung|kebersihan|\bapar\b|genset|toilet|bocor"),
    ("app", "Dukungan aplikasi dan akses", "Application and access support",
     r"aplikasi|\bapps?\b|sistem|\bakun|login|password|akses|\bmenu\b"),
    ("meeting", "Meeting dan koordinasi", "Meetings and coordination",
     r"meeting|rapat|zoom|\bteams\b|briefing|diskusi|\bbahas"),
    ("document", "Administrasi dokumen", "Document administration",
     r"\bsurat|dokumen|kontrak|\bform\b|formulir|tanda tangan|\bttd\b|arsip"),
    ("hr", "Administrasi SDM", "HR administration",
     r"\bcuti|\bizin|absen|lembur|\bgaji|karyawan|rekrut|interview|bpjs"),
]
TOPIC_RES = [(key, id_, en, re.compile(rf"(?i){pat}")) for key, id_, en, pat in TOPICS]
OTHER = ("other", "Koordinasi pekerjaan lainnya", "Other work coordination")


def report_title(day, name, lang="id"):
    who = f" ({name})" if name else ""
    return f"Daily Report {DAYS[lang][day.weekday()]}/{day.day:02d} {MONTHS[lang][day.month - 1]} {day.year}{who}."


def clean(text):
    """Link diringkas jadi nama situsnya saja, mis. "[link shopee.co.id]"."""
    return URL_RE.sub(lambda m: f"[link {m.group(1).removeprefix('www.')}]", text or "").strip()


def is_meaningful(text):
    # Link tidak dihitung sebagai kata: pesan berisi link saja tidak menjelaskan pekerjaan.
    text = URL_RE.sub("", text or "").strip()
    if not text or MEDIA_RE.match(text) or SOCIAL_RE.search(text):
        return False
    words = [w for w in re.split(r"[\s,.!?]+", text) if w]
    # Emoji/tanda baca saja, atau seluruhnya basa-basi.
    if not re.search(r"\w", text) or all(FILLER_WORD_RE.match(w) for w in words):
        return False
    return len(words) >= 3


def in_window(msg, day, start_hour, end_hour):
    dt = datetime.fromisoformat(msg["time"])
    return dt.date() == day and start_hour <= dt.hour < end_hour


def shorten(text):
    text = " ".join(text.split())
    if len(text) <= MAX_CHARS:
        return text
    return text[:MAX_CHARS].rsplit(" ", 1)[0] + "..."


def person(chat):
    """Nama chat tanpa awalan "TCI ", mis. "TCI Annisa Porta" -> "Annisa Porta"."""
    return re.sub(r"(?i)^tci\s+", "", chat).strip()


def classify(messages):
    """Topik dengan kata kunci terbanyak di pesan-pesan chat, atau None."""
    text = " ".join(m["text"] for m in messages)
    best, best_score = None, 0
    for topic in TOPIC_RES:
        score = len(topic[3].findall(text))
        if score > best_score:
            best, best_score = topic, score
    return best


def describe(chat, messages, topic, lang):
    """Satu baris "Orang: isi pekerjaan; status." untuk satu chat."""
    pattern = topic[3] if topic else None

    def score(m):
        hits = len(pattern.findall(m["text"])) if pattern else 0
        # Permintaan dari orang lain lebih menjelaskan pekerjaan daripada jawaban sendiri.
        return (hits, not m["out"], len(m["text"]))

    main = max(messages, key=score)
    # Selesai kalau pesan itu sendiri atau pesan sesudahnya menyebut beres/aman/sudah bisa.
    done = any(DONE_RE.search(m["text"]) for m in messages if m["time"] >= main["time"])

    who = person(main["sender"]) if not main["out"] else person(chat)
    detail = shorten(redact(clean(MENTION_RE.sub("", main["text"])))).rstrip(" .")
    status = t(lang, "status_done" if done else "status_progress")
    return main["time"], who, f"{detail}; {status}."


def build_report(chats, day, name="", start_hour=6, end_hour=17, lang="id", routine=(), manual=()):
    """chats: {nama_chat: [pesan]} -> teks draf report format daily report."""
    groups = {}  # kunci topik -> {"title", "first", "lines"}

    for chat, messages in chats.items():
        window = [m for m in messages if in_window(m, day, start_hour, end_hour)
                  and not SOCIAL_RE.search(m["text"] or "")]
        msgs = [m for m in window if is_meaningful(m["text"])]
        if not msgs:
            continue
        # Topik dihitung dari semua pesan, termasuk yang pendek seperti
        # "untuk sharepointnya", supaya konteks pekerjaan tidak hilang.
        topic = classify(window)
        if topic is None:
            # Chat tanpa kata kunci pekerjaan hanya dimasukkan kalau berupa
            # percakapan dua arah, supaya obrolan lepas tidak ikut.
            if not (any(m["out"] for m in msgs) and any(not m["out"] for m in msgs)):
                continue
            key, title = OTHER[0], OTHER[1] if lang == "id" else OTHER[2]
        else:
            key, title = topic[0], topic[1] if lang == "id" else topic[2]

        first, who, line = describe(chat, msgs, topic, lang)
        g = groups.setdefault(key, {"title": title, "first": first, "lines": []})
        g["first"] = min(g["first"], first)
        g["lines"].append((who, line))

    items = []
    for g in sorted(groups.values(), key=lambda g: g["first"]):
        if len(g["lines"]) == 1:
            who, line = g["lines"][0]
            items.append([f"{g['title']} ({who}): {line}"])
        else:
            items.append([f"{g['title']}:"] + [f"- {who}: {line}" for who, line in g["lines"]])

    # Catatan manual (pekerjaan yang tidak ada di chat) masuk sebagai poin sendiri.
    for text in manual:
        lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
        if lines:
            items.append([lines[0]] + [l if l.startswith("-") else f"- {l}" for l in lines[1:]])

    # Item rutin diselipkan di posisi acak, tetap sama untuk tanggal yang sama.
    rng = random.Random(day.toordinal())
    for text in routine:
        items.insert(rng.randint(0, len(items)), [text])

    out = [report_title(day, name, lang), ""]
    if not items:
        out.append(t(lang, "empty_report", start=start_hour, end=end_hour))
    for i, lines in enumerate(items, 1):
        out.append(f"{i}. {lines[0]}")
        out.extend(lines[1:])

    return "\n".join(out)
