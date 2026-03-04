"""
scripts/generate_pdf_report.py

Convert the latest markdown report to a styled PDF using reportlab.
Can be imported or run standalone.

Usage:
  python3 scripts/generate_pdf_report.py
  python3 scripts/generate_pdf_report.py --input data/reports/latest.md --output data/reports/latest.pdf
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER

REPORTS_DIR = Path("data/reports")

# ── Colour palette ──────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1a2744")
BLUE    = colors.HexColor("#2563eb")
GREEN   = colors.HexColor("#16a34a")
RED     = colors.HexColor("#dc2626")
AMBER   = colors.HexColor("#d97706")
LGRAY   = colors.HexColor("#f1f5f9")
MGRAY   = colors.HexColor("#94a3b8")
WHITE   = colors.white


def _styles():
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, parent=base["Normal"], **kw)
    return {
        "h1":      s("h1",  fontSize=20, textColor=NAVY,  spaceAfter=4,  spaceBefore=0,  leading=24, fontName="Helvetica-Bold"),
        "h2":      s("h2",  fontSize=14, textColor=BLUE,  spaceAfter=4,  spaceBefore=14, leading=18, fontName="Helvetica-Bold"),
        "h3":      s("h3",  fontSize=11, textColor=NAVY,  spaceAfter=2,  spaceBefore=8,  leading=14, fontName="Helvetica-Bold"),
        "body":    s("body",fontSize=9,  textColor=colors.black, spaceAfter=3, leading=13),
        "meta":    s("meta",fontSize=8,  textColor=MGRAY, spaceAfter=6,  leading=11, fontName="Helvetica-Oblique"),
        "bullet":  s("bul", fontSize=9,  textColor=colors.black, spaceAfter=2, leading=12, leftIndent=12, bulletIndent=0),
        "tag_high":s("th",  fontSize=8,  textColor=RED,   fontName="Helvetica-Bold"),
        "tag_med": s("tm",  fontSize=8,  textColor=AMBER, fontName="Helvetica-Bold"),
        "tag_low": s("tl",  fontSize=8,  textColor=GREEN, fontName="Helvetica-Bold"),
    }


def _severity_color(line: str) -> colors.Color:
    if "[HIGH]" in line: return RED
    if "[MED]"  in line: return AMBER
    return GREEN


# Emoji -> PDF-safe text label map
_EMOJI_MAP = {
    "🏆": "[TOP6]",
    "🔴": "[IL]",
    "🟡": "[DTD]",
    "🟢": "[OK]",
    "🟠": "[HIGH]",
    "✅": "[WIN]",
    "❌": "[LOSS]",
    "⚖️": "[TOSS]",
    "🎯": "[SWING]",
    "🚨": "[ALERT]",
    "⚠️": "[WARN]",
    "📈": "[UP]",
}

def _strip_emoji(text: str) -> str:
    for emoji, label in _EMOJI_MAP.items():
        text = text.replace(emoji, label)
    # Drop any remaining non-latin-1 chars reportlab cannot render
    return text.encode("latin-1", errors="ignore").decode("latin-1")

def _clean(text: str) -> str:
    """Strip markdown formatting for reportlab paragraphs."""
    text = _strip_emoji(text)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: "<b>" + m.group(1) + "</b>", text)
    text = re.sub(r"`(.+?)`", lambda m: "<font name=\'Courier\'>" + m.group(1) + "</font>", text)
    text = re.sub(r"_(.+?)_", lambda m: "<i>" + m.group(1) + "</i>", text)
    return text
def _parse_table(lines: list[str]) -> list[list[str]]:
    """Parse a markdown pipe table into list of rows."""
    rows = []
    for line in lines:
        if re.match(r"^\s*\|[-| ]+\|\s*$", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells:
            rows.append(cells)
    return rows


def _table_flowable(rows: list[list[str]], styles) -> Table:
    if not rows:
        return Spacer(1, 0)
    col_count = max(len(r) for r in rows)
    # Pad short rows
    padded = [r + [""] * (col_count - len(r)) for r in rows]
    # Convert first row to bold header paragraphs
    header = [Paragraph(f"<b>{c}</b>", styles["body"]) for c in padded[0]]
    data = [header] + [
        [Paragraph(_clean(c), styles["body"]) for c in row]
        for row in padded[1:]
    ]
    col_width = (6.5 * inch) / col_count
    t = Table(data, colWidths=[col_width] * col_count, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0),  NAVY),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",        (0, 0), (-1, -1), 0.3, MGRAY),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0,0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
    ]))
    return t


def markdown_to_pdf(md_text: str, out_path: Path) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=LETTER,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.75*inch,  bottomMargin=0.75*inch,
    )

    story = []
    lines = md_text.splitlines()
    i = 0

    while i < len(lines):
        line = lines[i]

        # H1
        if line.startswith("# "):
            story.append(Paragraph(_clean(line[2:]), styles["h1"]))
            story.append(HRFlowable(width="100%", thickness=1.5, color=NAVY, spaceAfter=2))
            i += 1

        # H2
        elif line.startswith("## "):
            story.append(Paragraph(_clean(line[3:]), styles["h2"]))
            story.append(HRFlowable(width="100%", thickness=0.5, color=BLUE, spaceAfter=2))
            i += 1

        # H3
        elif line.startswith("### "):
            story.append(Paragraph(_clean(line[4:]), styles["h3"]))
            i += 1

        # Italic meta line (team/week header)
        elif line.startswith("_") and line.endswith("_"):
            story.append(Paragraph(_clean(line), styles["meta"]))
            i += 1

        # Bullet point
        elif line.startswith("- "):
            text = _clean(line[2:])
            sev = _severity_color(line)
            para = Paragraph(f"• {text}", styles["bullet"])
            story.append(para)
            i += 1

        # Markdown table
        elif line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].startswith("|"):
                table_lines.append(lines[i])
                i += 1
            rows = _parse_table(table_lines)
            if rows:
                story.append(_table_flowable(rows, styles))
                story.append(Spacer(1, 6))

        # Blank line
        elif line.strip() == "":
            story.append(Spacer(1, 4))
            i += 1

        # Plain paragraph
        else:
            story.append(Paragraph(_clean(line), styles["body"]))
            i += 1

    doc.build(story)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input",  default=str(REPORTS_DIR / "latest.md"))
    ap.add_argument("--output", default=str(REPORTS_DIR / "latest.pdf"))
    args = ap.parse_args()

    in_path  = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        raise SystemExit(f"Input not found: {in_path}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    md_text = in_path.read_text(encoding="utf-8")
    markdown_to_pdf(md_text, out_path)
    print(f"PDF written -> {out_path}  ({out_path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
