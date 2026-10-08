"""Email notifications over direct SMTP (settings and encrypted password from the Settings page)."""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Tuple

from sqlalchemy.orm import Session as DBSession

from app.services import timefmt
from app.services.app_settings import get_config, get_secret

SIGNATURE = '-- RePlexOn\n"Previously on your Plex server..."'


def _message(from_addr: str, to_addr: str, subject: str, text: str) -> MIMEMultipart:
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.attach(MIMEText(text, "plain"))
    return msg


def _send(db: DBSession, subject: str, text: str) -> Tuple[bool, str]:
    """Send one message to the configured recipient and log the attempt."""
    cfg = get_config(db)
    recipient = cfg["email_recipient"]
    if not recipient:
        return False, "Email recipient is not configured"
    host = cfg["smtp_host"]
    if not host:
        return False, "SMTP host is not configured"
    try:
        port = int(cfg["smtp_port"] or "587")
    except ValueError:
        return False, "SMTP port must be a number"

    msg = _message(cfg["smtp_from"] or recipient, recipient, subject, text)
    password = get_secret(db, "smtp_password")
    try:
        if cfg["smtp_tls"] == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=15, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(host, port, timeout=15)
            if cfg["smtp_tls"] == "starttls":
                server.starttls(context=ssl.create_default_context())
        try:
            if cfg["smtp_user"]:
                server.login(cfg["smtp_user"], password)
            server.sendmail(msg["From"], [recipient], msg.as_string())
        finally:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass
        ok, message = True, f"Email sent to {recipient}"
    except smtplib.SMTPAuthenticationError:
        ok, message = False, "SMTP login failed (check user and password)"
    except smtplib.SMTPSenderRefused:
        ok, message = False, "SMTP server refused the sender (does it need a login?)"
    except smtplib.SMTPException as e:
        ok, message = False, f"SMTP error: {e.__class__.__name__}"
    except OSError as e:
        ok, message = False, f"Connection error: {e.strerror or e.__class__.__name__}"

    _log_email(db, recipient, subject, ok, "smtp", None if ok else message)
    return ok, message


def _log_email(db: DBSession, recipient: str, subject: str, success: bool, method: str, error: str = None):
    from app.models.email_log import EmailLog
    db.add(EmailLog(recipient=recipient, subject=subject, success=success, method=method, error_message=error))
    db.commit()


def send_test_email(db: DBSession) -> Tuple[bool, str]:
    return _send(
        db,
        "RePlexOn - Test Notification",
        "This is a test email from RePlexOn.\n\n"
        "If you received this, your email settings are configured correctly.\n\n" + SIGNATURE,
    )


def notify_backup_result(db: DBSession, run) -> None:
    """Email a finished run if the notify setting asks for it."""
    notify_on = get_config(db)["notify_on"]
    failed = run.status != "success"
    if notify_on == "never" or (notify_on == "failure" and not failed) or (notify_on == "success" and failed):
        return
    if not get_config(db)["email_recipient"]:
        return

    tz = timefmt.zone(db)
    kind = run.backup_type.replace("_", " ")
    if failed:
        subject = f"Plex Backup FAILED - {kind}"
    else:
        subject = f"Plex Backup OK - {kind}, {run.size_display}, {run.duration_display}"
    lines = [
        f"Status:      {'FAILED' if failed else 'OK'}",
        f"Type:        {kind} ({run.triggered_by})",
        f"Started:     {timefmt.fmt_datetime(run.started_at)} ({timefmt.zone_name(tz)})",
        f"Duration:    {run.duration_display}",
        f"Total size:  {run.size_display}",
    ]
    if run.backup_type != "cleanup":
        lines.append("DB safety:   " + ("consistent copy" if run.db_safe else "FAILED - databases not backed up"))
    if failed:
        lines.append(f"Error:       {run.error_message or 'unknown'}")
        tail = "\n".join((run.raw_log or "").splitlines()[-15:])
        if tail:
            lines += ["", "Last log lines:", tail]
    ok, _ = _send(db, subject, "\n".join(lines) + "\n\n" + SIGNATURE)
    if ok:
        run.email_sent = True
        db.commit()


def get_recent_email_logs(db: DBSession, limit: int = 10) -> list:
    from app.models.email_log import EmailLog
    return db.query(EmailLog).order_by(EmailLog.sent_at.desc()).limit(limit).all()
