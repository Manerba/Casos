"""
Casos - Mail-Service
SMTP-Versand, Template-Rendering, HTML-Layout.
"""

import logging
import html
import re
import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dashboard.database import get_db
from dashboard.crypto_utils import decrypt
from dashboard.user_utils import get_display_name
from dashboard.tls_utils import get_tls_config, get_tls_verify_config

logger = logging.getLogger(__name__)
ISSUE_MAIL_EVENTS = ('issue_assigned', 'status_change', 'new_update', 'deadline_reached', 'deadline_warning')


def get_app_url() -> str:
    """Baut die App-URL aus server_address (DB) und TLS-Config.
    Fallback: http://localhost:8514"""
    db = get_db()
    try:
        row = db.execute("SELECT server_address FROM app_config WHERE id = 1").fetchone()
        address = row["server_address"] if row else "localhost:8514"
    finally:
        db.close()

    tls = get_tls_config()
    protocol = "https" if tls and tls.get("enabled") else "http"
    return f"{protocol}://{address}"


def get_smtp_config() -> dict | None:
    """SMTP-Config aus DB laden. Gibt dict oder None zurueck."""
    db = get_db()
    try:
        row = db.execute("SELECT * FROM mail_config WHERE id = 1").fetchone()
        if not row:
            return None
        config = dict(row)
        # Passwort entschluesseln (at-rest Verschluesselung)
        if config.get("password"):
            config["password"] = decrypt(config["password"])
        return config
    finally:
        db.close()


def test_smtp_connection(config: dict) -> str | None:
    """Testet SMTP-Verbindung. Gibt None bei Erfolg, Fehlermeldung bei Fehler."""
    try:
        conn = _create_smtp_connection(config)
        conn.quit()
        return None
    except Exception as e:
        return str(e)


def _create_smtp_connection(config: dict):
    """Erstellt eine SMTP-Verbindung basierend auf der Konfiguration."""
    server = config["smtp_server"]
    port = config["smtp_port"]
    encryption = config.get("encryption", "starttls")

    verify_cfg = get_tls_verify_config()
    if verify_cfg["verify_smtp"]:
        # System-CAs verwenden (Zertifikat muss im Trust-Store sein)
        context = ssl.create_default_context()
    else:
        # Zertifikatsvalidierung deaktivieren (selbst-signierte Zertifikate)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

    if encryption == "ssl":
        conn = smtplib.SMTP_SSL(server, port, context=context, timeout=10)
    else:
        conn = smtplib.SMTP(server, port, timeout=10)
        if encryption == "starttls":
            conn.starttls(context=context)

    if config.get("auth_enabled"):
        conn.login(config["username"], config["password"])

    return conn


def send_mail(to_email: str, subject: str, html_body: str, text_body: str) -> str | None:
    """Sendet eine Mail. Gibt None bei Erfolg, Fehlermeldung bei Fehler."""
    config = get_smtp_config()
    if not config:
        return "Keine Mail-Konfiguration vorhanden"

    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{config['from_name']} <{config['from_address']}>"
        msg["To"] = to_email
        msg["Subject"] = subject

        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        conn = _create_smtp_connection(config)
        conn.sendmail(config["from_address"], [to_email], msg.as_string())
        conn.quit()
        return None
    except Exception as e:
        logger.error(f"Mail-Versand fehlgeschlagen an {to_email}: {e}")
        return str(e)


def render_template(event_type: str, placeholders: dict) -> tuple[str, str] | None:
    """Template aus DB laden, Platzhalter ersetzen.
    Gibt (subject, body_text) oder None zurueck."""
    db = get_db()
    try:
        row = db.execute(
            "SELECT subject, body_text FROM mail_templates WHERE event_type = ?",
            (event_type,),
        ).fetchone()
        if not row:
            return None

        subject = row["subject"]
        body_text = row["body_text"]

        # Substitute once: user text containing another placeholder stays literal.
        def substitute(match):
            value = placeholders.get(match.group(1), match.group(0))
            return '' if value is None else str(value)
        subject = re.sub(r'\{(\w+)\}', substitute, subject)
        body_text = re.sub(r'\{(\w+)\}', substitute, body_text)
        subject = subject.replace('\r', ' ').replace('\n', ' ')

        return subject, body_text
    finally:
        db.close()


def build_html_mail(content_text: str) -> str:
    """Baut einen HTML-Rahmen im Casos-Design um den Content-Text."""
    # Zeilenumbrueche zu <br> konvertieren
    content_html = html.escape(content_text).replace("\n", "<br>")

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#f5f5f5;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:20px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:8px;overflow:hidden;">
          <tr>
            <td style="background:#2c3e50;padding:16px 24px;color:#ffffff;font-size:18px;font-weight:600;">
              Casos
            </td>
          </tr>
          <tr>
            <td style="padding:24px;color:#333333;font-size:14px;line-height:1.6;">
              {content_html}
            </td>
          </tr>
          <tr>
            <td style="padding:16px 24px;background:#f8f9fa;color:#999999;font-size:12px;border-top:1px solid #e9ecef;">
              Diese Nachricht wurde automatisch von Casos gesendet.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def notify_event(event_type: str, recipient_user_id: int, placeholders: dict) -> str | None:
    """Prueft User-Prefs, rendert Template, versendet Mail.
    Gibt None bei Erfolg/Skip, Fehlermeldung bei Fehler."""
    db = get_db()
    try:
        # User laden
        user = db.execute(
            "SELECT id, username, vorname, nachname, email FROM users WHERE id = ? AND is_active = 1",
            (recipient_user_id,),
        ).fetchone()
        if not user or not user["email"]:
            return None  # Kein Empfaenger, kein Fehler

        # User-Prefs pruefen
        pref = db.execute(
            "SELECT enabled FROM user_mail_preferences WHERE user_id = ? AND event_type = ?",
            (recipient_user_id, event_type),
        ).fetchone()
        if pref and not pref["enabled"]:
            return None  # Deaktiviert

        # SMTP-Config pruefen
        config = db.execute("SELECT id FROM mail_config WHERE id = 1").fetchone()
        if not config:
            return None  # Kein Mail-Server konfiguriert
    finally:
        db.close()

    # Empfaenger-Name in Platzhalter einfuegen
    recipient_name = get_display_name(dict(user))
    placeholders = dict(placeholders)
    placeholders["recipient_name"] = recipient_name

    # App-URL automatisch einfuegen (Caller kann ueberschreiben)
    if "app_url" not in placeholders:
        placeholders["app_url"] = get_app_url()

    # Template rendern
    result = render_template(event_type, placeholders)
    if not result:
        return f"Template '{event_type}' nicht gefunden"

    subject, body_text = result
    html_body = build_html_mail(body_text)

    return send_mail(user["email"], subject, html_body, body_text)


def ensure_default_prefs(user_id: int):
    """Stellt sicher, dass Default-Mail-Preferences fuer einen User existieren."""
    db = get_db()
    try:
        for et in ISSUE_MAIL_EVENTS:
            db.execute(
                """INSERT OR IGNORE INTO user_mail_preferences (user_id, event_type, enabled, days_before)
                   VALUES (?, ?, 1, 2)""",
                (user_id, et),
            )
        db.commit()
    finally:
        db.close()


def notify_issue_event(issue_id, event_type, actor_id=None, *, changes=None, update_id=None, days_before=None):
    """Best-effort postcommit delivery; failures never undo an Issue mutation.

    Current active creator/assignee only, respecting event preferences. Duplicate
    mailboxes and the actor's own mailbox are excluded. No SMTP occurs in a write
    transaction. Delivery errors are logged; this is not a durable mail queue.
    """
    try:
        if event_type not in ISSUE_MAIL_EVENTS:
            raise ValueError('Unsupported Issue mail event')
        db = get_db()
        try:
            db.execute('BEGIN')
            if not db.execute('SELECT 1 FROM mail_config WHERE id=1').fetchone():
                return 0
            row = db.execute('SELECT * FROM issues WHERE id=?', (issue_id,)).fetchone()
            if row is None:
                return 0
            issue = dict(row)
            if event_type.startswith('deadline_') and issue['status'] not in ('offen', 'in_arbeit'):
                return 0
            actor = db.execute('SELECT * FROM users WHERE id=?', (actor_id,)).fetchone()
            actor_name = get_display_name(dict(actor)) if actor else ''
            actor_email = (actor['email'] or '').strip().casefold() if actor else ''
            recipients = []
            seen = {actor_email} if actor_email else set()
            for uid in dict.fromkeys((issue['created_by'], issue['assigned_to'])):
                if uid is None or uid == actor_id:
                    continue
                recipient = db.execute('SELECT * FROM users WHERE id=? AND is_active=1', (uid,)).fetchone()
                if recipient is None or not (recipient['email'] or '').strip():
                    continue
                pref = db.execute('SELECT enabled,days_before FROM user_mail_preferences WHERE user_id=? AND event_type=?',
                                  (uid, event_type)).fetchone()
                if pref and not pref['enabled']:
                    continue
                if event_type == 'deadline_warning' and days_before != (pref['days_before'] if pref else 2):
                    continue
                email = (recipient['email'] or '').strip().casefold()
                if email in seen:
                    continue
                seen.add(email)
                recipients.append(uid)
        finally:
            db.close()
        change = changes or {}
        issue_url = f'{get_app_url()}/issues/{issue_id}'
        placeholders = {'issue_id': issue_id, 'issue_title': issue['title'], 'issue_url': issue_url,
                        'actor_name': actor_name, 'deadline': issue['deadline'] or '', 'priority': issue['priority'],
                        'old_status': change.get('old', ''), 'new_status': change.get('new', issue['status']),
                        'old_assignee': change.get('old_label') or 'Nicht zugewiesen',
                        'new_assignee': change.get('new_label') or 'Nicht zugewiesen',
                        'update_id': update_id or '',
                        'update_url': f'{issue_url}?update={update_id}' if update_id else issue_url,
                        'days_before': days_before if days_before is not None else ''}
        sent = 0
        for uid in recipients:
            try:
                error = notify_event(event_type, uid, placeholders)
                if error:
                    logger.warning('Issue notification failed: issue=%s event=%s recipient=%s: %s', issue_id, event_type, uid, error)
                else:
                    sent += 1
            except Exception:
                logger.exception('Issue notification failed: issue=%s event=%s recipient=%s', issue_id, event_type, uid)
        return sent
    except Exception:
        logger.exception('Issue notification preparation failed: issue=%s event=%s', issue_id, event_type)
        return 0


def notify_due_issues(today=None):
    """One daily scheduler pass, using local calendar dates and per-user warnings."""
    today = today or date.today()
    if type(today) is not date:
        raise ValueError('today must be a date')
    db = get_db()
    try:
        rows = db.execute("SELECT id,deadline FROM issues WHERE status IN ('offen','in_arbeit') AND deadline>=?",
                          (today.isoformat(),)).fetchall()
    finally:
        db.close()
    counts = {'deadline_reached': 0, 'deadline_warning': 0}
    for row in rows:
        remaining = (date.fromisoformat(row['deadline']) - today).days
        if remaining == 0:
            counts['deadline_reached'] += notify_issue_event(row['id'], 'deadline_reached')
        elif remaining <= 365:
            counts['deadline_warning'] += notify_issue_event(row['id'], 'deadline_warning', days_before=remaining)
    return counts
