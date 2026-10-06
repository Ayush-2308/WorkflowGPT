"""Render DOCUMENTATION.md to a printable PDF (Latin text)."""

from __future__ import annotations

import re
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "DOCUMENTATION.md"
OUT = ROOT / "docs" / "WorkflowGPT-Documentation.pdf"
FONT = Path(r"C:\Windows\Fonts\calibri.ttf")
FONT_B = Path(r"C:\Windows\Fonts\calibrib.ttf")


class DocPDF(FPDF):
    def footer(self) -> None:
        self.set_y(-14)
        self.set_font("Calibri", size=9)
        self.set_text_color(90, 90, 90)
        self.cell(0, 8, f"WorkflowGPT documentation  |  page {self.page_no()}", align="C")


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf = DocPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("Calibri", fname=str(FONT))
    if FONT_B.exists():
        pdf.add_font("Calibri", style="B", fname=str(FONT_B))
    pdf.add_page()
    pdf.set_title("WorkflowGPT Complete Documentation")

    text = SRC.read_text(encoding="utf-8")
    in_code = False
    for raw in text.splitlines():
        line = raw.rstrip()
        pdf.set_x(pdf.l_margin)
        if line.startswith("```"):
            in_code = not in_code
            continue
        if line.startswith("|") and set(line.replace("|", "").replace(" ", "").replace("-", "")) == set():
            continue
        if in_code:
            pdf.set_font("Calibri", size=8)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 4, _clean(line) or " ")
            continue
        if line.startswith("# "):
            pdf.set_font("Calibri", style="B" if FONT_B.exists() else "", size=18)
            pdf.set_text_color(13, 107, 84)
            pdf.ln(4)
            pdf.multi_cell(0, 8, _clean(line[2:]))
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.set_font("Calibri", style="B" if FONT_B.exists() else "", size=14)
            pdf.set_text_color(13, 107, 84)
            pdf.ln(3)
            pdf.multi_cell(0, 7, _clean(line[3:]))
            pdf.ln(1)
        elif line.startswith("### "):
            pdf.set_font("Calibri", style="B" if FONT_B.exists() else "", size=12)
            pdf.set_text_color(40, 40, 40)
            pdf.ln(2)
            pdf.multi_cell(0, 6, _clean(line[4:]))
        elif line.startswith("|") and "---" not in line:
            pdf.set_font("Calibri", size=9)
            pdf.set_text_color(20, 20, 20)
            cells = [c.strip() for c in line.strip("|").split("|")]
            pdf.multi_cell(0, 5, "  |  ".join(_clean(c) for c in cells))
        elif line.startswith("- "):
            pdf.set_font("Calibri", size=10)
            pdf.set_text_color(20, 20, 20)
            pdf.multi_cell(0, 5, "•  " + _clean(line[2:]))
        elif not line.strip():
            pdf.ln(2)
        else:
            pdf.set_font("Calibri", size=10)
            pdf.set_text_color(20, 20, 20)
            pdf.multi_cell(0, 5, _clean(line))
    pdf.output(str(OUT))
    print(OUT, OUT.stat().st_size)


def _clean(text: str) -> str:
    text = re.sub(r"[`*_]+", "", text)
    return text.replace("\t", "    ")


if __name__ == "__main__":
    main()
