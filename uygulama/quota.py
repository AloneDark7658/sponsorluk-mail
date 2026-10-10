"""Ortak gönderim bütçesi: tüm gönderim yolları aynı sınırları paylaşır.

İki sınır var:
  * Gmail genel sınırı (ayarlardaki 'Günlük alıcı limiti'): son 24 saatte gönderilenler + Google sunucusunda
    planlı bekleyenler birlikte sayılır. Uygulamadan gönderim, hatırlatma ve Google planı bu bütçeden düşer.
  * Google sunucusu (Apps Script) sınırı: takvim günü başına 100 alıcı; o gün Google'ın gönderdikleri ve
    planlı ilk mailler + hatırlatmalar birlikte sayılır.
CC adresleri her mailde ayrı alıcı sayılır.
"""
from datetime import datetime, timedelta

from database import TIME_FORMAT

SERVER_DAILY_RECIPIENTS = 100
SERVER_KINDS = ("server", "server_reminder")


def _parse(value):
    try:
        return datetime.strptime(value, TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def server_pending(db):
    """Google sunucusunda gönderilmeyi bekleyenler: [(zaman, alıcı sayısı)] (ilk mailler + hatırlatmalar)."""
    items = []
    for c in db.server_planned_contacts():
        when = _parse(c.get("scheduled_for"))
        if when:
            items.append((when, c.get("recipients") or 1))
    for c in db.reminder_planned_contacts():
        when = _parse(c.get("reminder_scheduled_for"))
        if when:
            items.append((when, c.get("reminder_recipients") or 1))
    return items


def reserved_next_24h(db):
    """Önümüzdeki 24 saat içinde (ya da saati geçmiş ama henüz işlenmemiş) Google'da planlı alıcı."""
    limit = datetime.now() + timedelta(hours=24)
    return sum(n for when, n in server_pending(db) if when <= limit)


def gmail_used(db):
    """(son 24 saatte gönderilen, Google'da planlı yaklaşan) alıcı sayısı."""
    return db.recipients_last_24h(), reserved_next_24h(db)


def gmail_room(db, daily_limit):
    used, reserved = gmail_used(db)
    return max(0, daily_limit - used - reserved)


def server_used_on(db, day):
    """O gün Google sunucusunun gönderdiği + o güne planlı alıcı."""
    planned = sum(n for when, n in server_pending(db) if when.date() == day)
    return db.recipients_on(day, SERVER_KINDS) + planned


def server_room(db, day, daily_limit):
    """O gün Google sunucusuna verilebilecek alıcı: hem Google'ın 100'ü hem Gmail genel sınırı aşılmaz."""
    google_room = max(0, SERVER_DAILY_RECIPIENTS - server_used_on(db, day))
    return min(google_room, gmail_room(db, daily_limit))
