"""Simpan report ke PDF dengan kop logo OruLabs."""

import os

from fpdf import FPDF


# Oranye OruLabs dari logo, untuk garis kop.
ORANGE = (240, 120, 40)

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")


class ReportPDF(FPDF):
    def __init__(self, logo):
        super().__init__(format="A4")
        self.logo = logo
        self.set_margins(20, 15, 20)
        self.set_auto_page_break(True, margin=18)

        # Arial bawaan Windows supaya huruf non-Latin tetap tampil.
        regular = os.path.join(FONT_DIR, "arial.ttf")
        bold = os.path.join(FONT_DIR, "arialbd.ttf")
        if os.path.exists(regular) and os.path.exists(bold):
            self.add_font("Body", "", regular)
            self.add_font("Body", "B", bold)
            self.font_name = "Body"
        else:
            self.font_name = "Helvetica"

    def header(self):
        # Kop: logo di kiri, keterangan dokumen di kanan, garis merah di bawah.
        if self.logo and os.path.exists(self.logo):
            self.image(self.logo, x=20, y=14, w=60)
        self.set_font(self.font_name, "B", 13)
        self.set_xy(100, 12)
        self.cell(90, 7, "HRGA Daily Report", align="R")
        self.set_font(self.font_name, "", 9)
        self.set_text_color(90, 90, 90)
        self.set_xy(100, 19)
        self.cell(90, 5, "OruLabs", align="R")
        self.set_text_color(0, 0, 0)

        self.set_draw_color(*ORANGE)
        self.set_line_width(0.8)
        self.line(20, 30, 190, 30)
        self.set_line_width(0.2)
        self.line(20, 31.2, 190, 31.2)
        self.set_y(37)

    def footer(self):
        self.set_y(-12)
        self.set_font(self.font_name, "", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 5, str(self.page_no()), align="C")


def _safe(pdf, text):
    """Font Helvetica cadangan hanya kenal latin-1; karakter lain diganti '?'."""
    if pdf.font_name == "Helvetica":
        return text.encode("latin-1", "replace").decode("latin-1")
    return text


def save_pdf(text, path, logo):
    pdf = ReportPDF(logo)
    pdf.add_page()
    lines = text.splitlines()

    # Baris pertama (judul report) dicetak tebal.
    if lines:
        pdf.set_font(pdf.font_name, "B", 12)
        pdf.multi_cell(0, 7, _safe(pdf, lines[0]), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        lines = lines[1:]

    pdf.set_font(pdf.font_name, "", 10.5)
    for line in lines:
        if not line.strip():
            pdf.ln(3)
            continue
        if line.startswith("-"):
            # Sub-poin menjorok ke dalam.
            pdf.set_x(28)
            pdf.multi_cell(0, 5.5, _safe(pdf, line), new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font(pdf.font_name, "B", 10.5)
            pdf.multi_cell(0, 6, _safe(pdf, line), new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(pdf.font_name, "", 10.5)

    pdf.output(path)
    return path
