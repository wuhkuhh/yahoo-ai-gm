"""
scripts/send_report_email.py

Send the daily report email with:
  - Plain text summary in body
  - HTML formatted report inline
  - PDF attachment

Usage:
  python3 scripts/send_report_email.py
  python3 scripts/send_report_email.py --week 3
"""
from __future__ import annotations

import argparse
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


REPORTS_DIR = Path("data/reports")
SMTP_HOST   = "smtp.gmail.com"
SMTP_PORT   = 587


def _env(key: str) -> str:
    val = os.environ.get(key, "").strip()
    if not val:
        raise SystemExit(f"Missing required env var: {key}")
    return val


def _md_to_html(md: str) -> str:
    """Minimal markdown -> HTML converter for email body."""
    lines = md.splitlines()
    html_lines = []
    in_ul = False

    for line in lines:
        # Close list if needed
        if in_ul and not line.startswith("- "):
            html_lines.append("</ul>")
            in_ul = False

        if line.startswith("# "):
            html_lines.append(f'<h1 style="color:#1a2744;border-bottom:2px solid #2563eb;padding-bottom:6px">{line[2:]}</h1>')
        elif line.startswith("## "):
            html_lines.append(f'<h2 style="color:#2563eb;margin-top:20px">{line[3:]}</h2>')
        elif line.startswith("### "):
            html_lines.append(f'<h3 style="color:#1a2744;margin-top:12px">{line[4:]}</h3>')
        elif line.startswith("_") and line.endswith("_"):
            html_lines.append(f'<p style="color:#94a3b8;font-style:italic;margin:2px 0">{line[1:-1]}</p>')
        elif line.startswith("- "):
            if not in_ul:
                html_lines.append('<ul style="margin:4px 0;padding-left:20px">')
                in_ul = True
            text = line[2:]
            # Color severity tags
            text = text.replace("[HIGH]", '<span style="color:#dc2626;font-weight:bold">[HIGH]</span>')
            text = text.replace("[MED]",  '<span style="color:#d97706;font-weight:bold">[MED]</span>')
            text = text.replace("[LOW]",  '<span style="color:#16a34a;font-weight:bold">[LOW]</span>')
            # Bold
            text = re.sub(r"\*\*(.+?)\*\*", r"<b></b>", text)
            text = re.sub(r"`(.+?)`", r'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px"></code>', text)
            html_lines.append(f'<li style="margin:3px 0">{text}</li>')
        elif line.startswith("|"):
            # Skip markdown tables in email — too complex, PDF has them
            pass
        elif line.strip() == "":
            html_lines.append('<br>')
        else:
            text = re.sub(r"\*\*(.+?)\*\*", r"<b></b>", line)
            html_lines.append(f'<p style="margin:4px 0">{text}</p>')

    if in_ul:
        html_lines.append("</ul>")

    body = "\n".join(html_lines)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
             max-width:700px;margin:0 auto;padding:20px;color:#1e293b;font-size:14px">
{body}
<hr style="margin-top:30px;border:none;border-top:1px solid #e2e8f0">
<p style="color:#94a3b8;font-size:11px">Yahoo AI GM — automated report</p>
</body>
</html>"""


def _plain_summary(md: str) -> str:
    """Extract key lines for plain text email body."""
    lines = []
    for line in md.splitlines():
        # Skip table rows and blank lines
        if line.startswith("|") or not line.strip():
            continue
        # Strip markdown formatting
        line = re.sub(r"\*\*(.+?)\*\*", r"", line)
        line = re.sub(r"`(.+?)`", r"", line)
        line = re.sub(r"_(.+?)_", r"", line)
        line = re.sub(r"^#+\s*", "", line)
        lines.append(line)
    return "\n".join(lines)


def send_report(
    md_path: Path,
    pdf_path: Path,
    mail_from: str,
    mail_to: str,
    app_password: str,
    week: int,
) -> None:
    if not md_path.exists():
        raise SystemExit(f"Markdown report not found: {md_path}")
    if not pdf_path.exists():
        raise SystemExit(f"PDF report not found: {pdf_path}. Run generate_pdf_report.py first.")

    md_text = md_path.read_text(encoding="utf-8")
    now = datetime.now(timezone.utc).astimezone()
    date_str = now.strftime("%a %b %-d, %Y")

    # Build message
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"⚾ Yahoo AI GM — Week {week} Report ({date_str})"
    msg["From"]    = f"Yahoo AI GM <{mail_from}>"
    msg["To"]      = mail_to

    # Attach alternative text/html
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(_plain_summary(md_text), "plain", "utf-8"))
    alt.attach(MIMEText(_md_to_html(md_text),    "html",  "utf-8"))
    msg.attach(alt)

    # Attach PDF
    pdf_bytes = pdf_path.read_bytes()
    pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_part.add_header(
        "Content-Disposition", "attachment",
        filename=f"yahoo_ai_gm_week_{week}.pdf"
    )
    msg.attach(pdf_part)

    # Send
    context = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls(context=context)
        server.login(mail_from, app_password)
        server.sendmail(mail_from, mail_to, msg.as_string())

    print(f"Email sent -> {mail_to}  (PDF: {len(pdf_bytes):,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--md",   default=str(REPORTS_DIR / "latest.md"))
    ap.add_argument("--pdf",  default=str(REPORTS_DIR / "latest.pdf"))
    args = ap.parse_args()

    mail_from    = _env("MAIL_FROM")
    mail_to      = _env("MAIL_TO")
    app_password = _env("MAIL_APP_PASSWORD")

    # Determine week from filename if not specified
    week = args.week
    if week is None:
        md_path = Path(args.md)
        m = re.search(r"week_(\d+)", md_path.stem)
        week = int(m.group(1)) if m else 1

    send_report(
        md_path=Path(args.md),
        pdf_path=Path(args.pdf),
        mail_from=mail_from,
        mail_to=mail_to,
        app_password=app_password,
        week=week,
    )


if __name__ == "__main__":
    main()
