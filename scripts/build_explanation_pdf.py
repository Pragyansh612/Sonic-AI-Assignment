#!/usr/bin/env python3
"""Build docs/explanation.pdf from docs/explanation.md (fpdf2)."""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "explanation.md"
OUT = ROOT / "docs" / "explanation.pdf"


class PDF(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, f"Page {self.page_no()}/{{nb}}", align="C")


def _clean(text: str) -> str:
    text = html.unescape(text)
    replacements = {
        "—": "-",
        "–": "-",
        "→": "->",
        "↔": "<->",
        "×": "x",
        "≈": "~",
        "≥": ">=",
        "≤": "<=",
        "\u202f": " ",
        " ": " ",
        "“": '"',
        "”": '"',
        "’": "'",
        "‘": "'",
        "…": "...",
        "•": "-",
        "\u00a0": " ",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def build() -> Path:
    if not SRC.is_file():
        raise SystemExit(f"Missing source: {SRC}")

    pdf = PDF(format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    pdf.set_left_margin(18)
    pdf.set_right_margin(18)
    pdf.set_x(18)

    for raw in SRC.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        if not line.strip():
            pdf.ln(3)
            continue

        text = _clean(line.strip())
        pdf.set_x(18)

        if line.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.multi_cell(0, 8, text[2:].strip() if text.startswith("# ") else text)
            pdf.ln(2)
        elif line.startswith("## "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 12)
            body = text[3:].strip() if text.startswith("## ") else text
            pdf.multi_cell(0, 7, body)
            pdf.ln(1)
        else:
            # Body / bullets / numbered — single width, no nested indent
            if line.lstrip().startswith("- "):
                text = "- " + _clean(line.lstrip()[2:])
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 5, text)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    return OUT


if __name__ == "__main__":
    path = build()
    print(f"Wrote {path}", file=sys.stderr)
