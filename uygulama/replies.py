"""Cevap takibi: gönderilen maillerin Gmail konuşmalarına bakıp cevap gelip gelmediğini bulur.

Bilgi Gmail'de durduğu için uygulamanın sürekli açık olması gerekmez; her açılışta
kapalıyken gelen cevaplar da bulunur.
"""
import logging
from datetime import datetime, timedelta
from email.utils import parseaddr

from database import (ERROR, REPLY_AUTO, REPLY_BOUNCED, REPLY_NONE, REPLY_YES, SENT, TIME_FORMAT, now_str)
from gmail_client import GmailError

log = logging.getLogger(__name__)

BOUNCE_SENDERS = ("mailer-daemon@", "postmaster@")
AUTO_SUBJECT_HINTS = (
    "otomatik yanıt", "otomatik cevap", "automatic reply", "auto reply", "auto-reply", "autoreply",
    "out of office", "out of the office", "ofis dışında", "ofis disinda", "izindeyim",
)


def _is_auto_reply(headers):
    auto_submitted = headers.get("auto-submitted", "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return True
    if "x-autoreply" in headers or "x-autorespond" in headers:
        return True
    if headers.get("precedence", "").strip().lower() == "auto_reply":
        return True
    subject = headers.get("subject", "").lower()
    return any(hint in subject for hint in AUTO_SUBJECT_HINTS)


def classify_thread(messages, my_email, internal_addresses):
    """Konuşmanın durumunu bulur: (durum, cevap zamanı, cevaplayan adres).

    Kendi maillerimiz ve CC'deki ekip adresleri cevap sayılmaz. Öncelik: gerçek cevap >
    ulaşmadı > otomatik yanıt > cevap yok.
    """
    ignored = {a.lower() for a in internal_addresses} | {(my_email or "").lower()}
    found = {}
    for message in sorted(messages, key=lambda m: m["internal_date"]):
        if "SENT" in message["labels"]:
            continue
        sender = parseaddr(message["headers"].get("from", ""))[1].lower()
        if not sender or sender in ignored:
            continue
        if sender.startswith(BOUNCE_SENDERS):
            kind = REPLY_BOUNCED
        elif _is_auto_reply(message["headers"]):
            kind = REPLY_AUTO
        else:
            kind = REPLY_YES
        found.setdefault(kind, (message["internal_date"], sender))

    for kind in (REPLY_YES, REPLY_BOUNCED, REPLY_AUTO):
        if kind in found:
            millis, sender = found[kind]
            return kind, datetime.fromtimestamp(millis / 1000).strftime(TIME_FORMAT), sender
    return REPLY_NONE, None, None


def refresh_contact(db, gmail, contact, internal_addresses):
    """Tek firmanın konuşmasını kontrol edip sonucu kaydeder. Yeni durumu döner (konuşma yoksa None)."""
    messages = gmail.get_thread_messages(contact["thread_id"])
    if messages is None:
        log.warning("Konuşma bulunamadı: %s (%s)", contact["email"], contact["thread_id"])
        return None
    status, reply_at, reply_from = classify_thread(messages, gmail.email, internal_addresses)
    if status != contact.get("reply_status") or reply_at != contact.get("reply_at"):
        db.update_reply(contact["id"], status, reply_at, reply_from)
    return status


def check_replies(db, gmail, internal_addresses):
    """Cevabı kesinleşmemiş tüm firmaları kontrol eder. Özet sözlük döner."""
    result = {"checked": 0, "new_replies": [], "new_bounces": [], "missing": 0}
    for contact in db.contacts_to_check():
        try:
            status = refresh_contact(db, gmail, contact, internal_addresses)
        except GmailError as exc:
            if exc.fatal:
                raise
            log.warning("Cevap kontrolü atlandı (%s): %s", contact["email"], exc.message)
            continue
        result["checked"] += 1
        if status is None:
            result["missing"] += 1
        elif status == REPLY_YES:
            result["new_replies"].append(contact["firma"] or contact["email"])
        elif status == REPLY_BOUNCED:
            result["new_bounces"].append(contact["firma"] or contact["email"])
    db.set_setting("last_reply_check", now_str())
    log.info("Cevap kontrolü: %d firma, %d yeni cevap, %d ulaşmadı",
             result["checked"], len(result["new_replies"]), len(result["new_bounces"]))
    return result


def has_reply(contact):
    return bool(contact.get("manual_reply")) or contact.get("reply_status") == REPLY_YES


def awaiting_reply(contact):
    """Gönderilmiş, ulaşmış ve henüz cevap gelmemiş mi?"""
    return (contact["status"] == SENT and not has_reply(contact)
            and contact.get("reply_status") != REPLY_BOUNCED)


def due_for_reminder(contacts, days, max_reminders, now=None):
    """Hatırlatma zamanı gelmiş firmalar: cevap yok, hatırlatma hakkı var, son mailden 'days' gün geçmiş."""
    now = now or datetime.now()
    due = []
    for c in contacts:
        if not awaiting_reply(c) or not c.get("thread_id") or c.get("reminder_draft_id"):
            continue
        if (c.get("reminder_count") or 0) >= max_reminders:
            continue
        last = c.get("last_reminder_at") or c.get("sent_at")
        try:
            last_time = datetime.strptime(last, TIME_FORMAT)
        except (TypeError, ValueError):
            continue
        if now - last_time >= timedelta(days=days):
            due.append(c)
    return due


def reply_counts(contacts):
    counts = {"sent": 0, "replied": 0, "waiting": 0, "auto": 0, "bounced": 0, "reminded": 0, "error": 0}
    for c in contacts:
        if c["status"] == ERROR:
            counts["error"] += 1
        if c["status"] != SENT:
            continue
        counts["sent"] += 1
        if has_reply(c):
            counts["replied"] += 1
        elif c.get("reply_status") == REPLY_BOUNCED:
            counts["bounced"] += 1
        else:
            counts["waiting"] += 1
            if c.get("reply_status") == REPLY_AUTO:
                counts["auto"] += 1
        if c.get("reminder_count"):
            counts["reminded"] += 1
    return counts
