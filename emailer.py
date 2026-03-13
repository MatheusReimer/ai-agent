import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

GMAIL_USER     = os.getenv("GMAIL_USER")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
EMAIL_TO       = os.getenv("EMAIL_TO", GMAIL_USER)  # defaults to sender if not set


def send_report(html_content: str, performance_summary: str, bets_placed: list):
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("⚠️  Email skipped: GMAIL_USER or GMAIL_APP_PASSWORD not set.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "🤖 Polymarket Bot — Daily Report"
    msg["From"]    = GMAIL_USER
    msg["To"]      = EMAIL_TO

    # Plain-text body: performance summary + bets placed
    lines = ["=== TODAY'S BETS ==="]
    if bets_placed:
        for b in bets_placed:
            lines.append(f"  • ${b.get('amount'):.2f} on {b.get('outcome')} | {b.get('market_question', '')[:60]}")
    else:
        lines.append("  No bets placed today.")
    lines += ["", "=== PERFORMANCE SUMMARY ===", performance_summary]
    text_body = "\n".join(lines)

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASSWORD)
            server.sendmail(GMAIL_USER, EMAIL_TO, msg.as_string())
        print(f"📧 Report emailed to {EMAIL_TO}")
    except Exception as e:
        print(f"⚠️  Email failed: {e}")
