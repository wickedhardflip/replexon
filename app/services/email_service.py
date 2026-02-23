"""Send email notifications.

Strategy:
- If msmtp is installed, use it (it has stored credentials).
- Otherwise, try direct SMTP from app_settings (works for servers
  that don't require auth, e.g. internal relays).
"""

import shutil
import smtplib
import subprocess
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Tuple

from sqlalchemy.orm import Session as DBSession

from app.models.setting import AppSetting


def _get_setting(db: DBSession, key: str, default: str = "") -> str:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else default


def _get_recipient(db: DBSession) -> str:
    return _get_setting(db, "email_recipient")


def _build_test_message(from_addr: str, to_addr: str) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "RePlexOn - Test Notification"
    msg["From"] = from_addr
    msg["To"] = to_addr

    text = (
        "This is a test email from RePlexOn.\n\n"
        "If you received this, your email settings are configured correctly.\n\n"
        "-- RePlexOn\n"
        '"Previously on your Plex server..."'
    )
    html = (
        "<h2>RePlexOn Test Notification</h2>"
        "<p>If you received this, your email settings are configured correctly.</p>"
        "<hr>"
        '<p style="color: #888; font-size: 12px;">'
        '<em>"Previously on your Plex server..."</em></p>'
    )

    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_via_msmtp(to_addr: str, msg: MIMEMultipart) -> Tuple[bool, str]:
    """Send email using msmtp (uses system-stored credentials)."""
    try:
        result = subprocess.run(
            ["msmtp", "-t"],
            input=msg.as_string(),
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0:
            return True, "Test email sent via msmtp"
        return False, f"msmtp error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, "msmtp timed out"
    except FileNotFoundError:
        return False, "msmtp not found"


def _send_via_smtp(db: DBSession, to_addr: str, msg: MIMEMultipart) -> Tuple[bool, str]:
    """Send email using direct SMTP (no auth - for internal relays)."""
    host = _get_setting(db, "smtp_host")
    port = int(_get_setting(db, "smtp_port", "587") or "587")
    tls = _get_setting(db, "smtp_tls", "on") == "on"

    if not host:
        return False, "SMTP host is not configured"

    try:
        server = smtplib.SMTP(host, port, timeout=15)
        if tls:
            server.starttls()
        server.sendmail(msg["From"], [to_addr], msg.as_string())
        server.quit()
        return True, "Test email sent via SMTP"
    except smtplib.SMTPSenderRefused:
        return False, "SMTP server requires authentication (configure msmtp on the server)"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"
    except OSError as e:
        return False, f"Connection error: {e}"


def send_test_email(db: DBSession) -> Tuple[bool, str]:
    """Send a test email. Uses msmtp if available, else direct SMTP."""
    recipient = _get_recipient(db)
    if not recipient:
        return False, "Email recipient is not configured"

    from_addr = _get_setting(db, "smtp_from") or recipient
    msg = _build_test_message(from_addr, recipient)

    # Prefer msmtp if installed (has stored credentials)
    if shutil.which("msmtp"):
        return _send_via_msmtp(recipient, msg)

    # Fall back to direct SMTP
    return _send_via_smtp(db, recipient, msg)
