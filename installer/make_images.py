"""Buat gambar wizard installer (BMP) dari logo OruLabs."""

import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "..", "assets")
ORANGE = (240, 120, 40)
TEXT = (31, 35, 40)
MUTED = (107, 114, 128)
# Latar putih supaya logo OruLabs (latar transparan) tetap jelas.
PANEL = (255, 255, 255)


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    try:
        return ImageFont.truetype(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name), size)
    except OSError:
        return ImageFont.load_default()


def paste_center(img, logo, y):
    img.paste(logo, ((img.width - logo.width) // 2, y), logo)


def wizard_image(scale):
    """Panel kiri halaman Selamat Datang/Selesai (164x314 per skala): logo panjang di atas."""
    w, h = 164 * scale, 314 * scale
    img = Image.new("RGB", (w, h), PANEL)
    d = ImageDraw.Draw(img)

    logo = Image.open(os.path.join(ASSETS, "logo-wide.png")).convert("RGBA")
    # Lebar 140, tinggi mengikuti rasio logo supaya tidak gepeng.
    lw = 140 * scale
    logo = logo.resize((lw, round(logo.height * lw / logo.width)), Image.LANCZOS)
    paste_center(img, logo, 80 * scale)
    d.rectangle(((w - 40 * scale) // 2, 106 * scale, (w + 40 * scale) // 2, 108 * scale), fill=ORANGE)

    for text, size, bold, color, y in (
        ("HRGA", 24, True, TEXT, 140),
        ("Daily Report", 15, False, TEXT, 172),
        ("Report harian dari", 9, False, MUTED, 212),
        ("chat WhatsApp", 9, False, MUTED, 226),
    ):
        f = font(size * scale, bold)
        tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y * scale), text, font=f, fill=color)

    f = font(8 * scale)
    for text, y in (("Dibuat oleh", 278), ("OruLabs", 291)):
        d.text(((w - d.textlength(text, font=f)) / 2, y * scale), text, font=f, fill=MUTED)
    return img


def small_image(scale):
    """Ikon kecil di pojok kanan atas halaman wizard (55x55 per skala)."""
    s = 55 * scale
    img = Image.new("RGB", (s, s), (255, 255, 255))
    icon = Image.open(os.path.join(ASSETS, "icon.png")).convert("RGBA").resize((s - 6 * scale,) * 2, Image.LANCZOS)
    img.paste(icon, (3 * scale, 3 * scale), icon)
    return img


if __name__ == "__main__":
    for scale in (1, 2):
        wizard_image(scale).save(os.path.join(HERE, f"wizard-{scale}x.bmp"))
        small_image(scale).save(os.path.join(HERE, f"small-{scale}x.bmp"))
    print("ok")
