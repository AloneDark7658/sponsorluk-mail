"""SQLite veri katmanı: firmalar, şablonlar, ayarlar ve gönderim kaydı."""
import json
import sqlite3
import threading
from datetime import datetime, timedelta

PENDING = "Bekliyor"
SENT = "Gönderildi"
ERROR = "Hata"
SERVER = "Google'da planlı"  # taslak Gmail'de, Google sunucusu belirlenen saatte gönderecek

# Cevap takibi durumları (contacts.reply_status)
REPLY_NONE = "none"        # kontrol edildi, cevap yok
REPLY_YES = "replied"      # firmadan cevap geldi
REPLY_AUTO = "auto"        # sadece otomatik yanıt (ofis dışında vb.)
REPLY_BOUNCED = "bounced"  # mail adrese ulaşmadı

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# Sonradan eklenen sütunlar: eski veritabanlarına otomatik eklenir, veriler korunur.
CONTACT_MIGRATIONS = {
    "message_id": "TEXT",        # Gmail API mesaj kimliği
    "thread_id": "TEXT",         # Gmail konuşma kimliği (cevap takibi ve link için)
    "sent_subject": "TEXT",      # gönderilen (doldurulmuş) konu, hatırlatmada 'Re:' için
    "rfc_message_id": "TEXT",    # Message-ID başlığı, hatırlatmayı aynı konuşmaya bağlamak için
    "reply_status": "TEXT",
    "reply_at": "TEXT",
    "reply_from": "TEXT",
    "reminder_count": "INTEGER NOT NULL DEFAULT 0",
    "last_reminder_at": "TEXT",
    "manual_reply": "INTEGER NOT NULL DEFAULT 0",  # kullanıcı 'cevap alındı' diye işaretledi
    "draft_id": "TEXT",          # Google sunucusuyla planlananlarda Gmail taslak kimliği
    "scheduled_for": "TEXT",     # Google sunucusunun göndereceği zaman
    "recipients": "INTEGER",     # bu mail kaç alıcı sayılıyor (firma + CC)
    "sent_template": "TEXT",     # hangi şablonla gönderildi / planlandı
}


def now_str():
    return datetime.now().strftime(TIME_FORMAT)


def display_time(value):
    """'2026-09-29 14:03:00' -> '29.09.2026 14:03'"""
    if not value:
        return ""
    try:
        return datetime.strptime(value, TIME_FORMAT).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


class Database:
    def __init__(self, path):
        # Gönderim ayrı thread'de çalıştığı için bağlantı paylaşılıyor, erişim kilitle korunuyor.
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    firma TEXT NOT NULL DEFAULT '',
                    yetkili TEXT NOT NULL DEFAULT '',
                    extra TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL,
                    sent_at TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS templates (
                    name TEXT PRIMARY KEY,
                    subject TEXT NOT NULL DEFAULT '',
                    body TEXT NOT NULL DEFAULT '',
                    attachment TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                CREATE TABLE IF NOT EXISTS send_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sent_at TEXT NOT NULL,
                    recipients INTEGER NOT NULL,
                    to_email TEXT,
                    kind TEXT NOT NULL
                );
                """
            )
            existing = {row[1] for row in self._conn.execute("PRAGMA table_info(contacts)")}
            for column, declaration in CONTACT_MIGRATIONS.items():
                if column not in existing:
                    self._conn.execute(f"ALTER TABLE contacts ADD COLUMN {column} {declaration}")
            self._conn.commit()

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def _query(self, sql, params=()):
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    @staticmethod
    def _contact(row):
        if row is None:
            return None
        contact = dict(row)
        try:
            contact["extra"] = json.loads(contact["extra"] or "{}")
        except ValueError:
            contact["extra"] = {}
        return contact

    # ---------- Firmalar ----------

    def add_contacts(self, rows):
        """rows: [{'email', 'firma', 'yetkili', 'extra'}]. (eklenen sayısı, zaten var olan adresler) döner."""
        added = 0
        duplicates = []
        with self._lock:
            existing = {r[0].lower() for r in self._conn.execute("SELECT email FROM contacts")}
            for row in rows:
                key = row["email"].lower()
                if key in existing:
                    duplicates.append(row["email"])
                    continue
                self._conn.execute(
                    "INSERT INTO contacts (email, firma, yetkili, extra, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        row["email"],
                        row["firma"],
                        row["yetkili"],
                        json.dumps(row.get("extra", {}), ensure_ascii=False),
                        PENDING,
                        now_str(),
                    ),
                )
                existing.add(key)
                added += 1
            self._conn.commit()
        return added, duplicates

    def find_by_email(self, email, exclude_id=None):
        """Bu email başka bir firmada kayıtlıysa o firmayı döner (tekrar kontrolü için)."""
        rows = self._query(
            "SELECT * FROM contacts WHERE email = ? COLLATE NOCASE AND id != ?", (email, exclude_id or -1)
        )
        return self._contact(rows[0]) if rows else None

    def update_contact(self, contact_id, email, firma, yetkili, extra):
        self._execute(
            "UPDATE contacts SET email = ?, firma = ?, yetkili = ?, extra = ? WHERE id = ?",
            (email, firma, yetkili, json.dumps(extra, ensure_ascii=False), contact_id),
        )

    def list_contacts(self):
        return [self._contact(r) for r in self._query("SELECT * FROM contacts ORDER BY id")]

    def get_contact(self, contact_id):
        rows = self._query("SELECT * FROM contacts WHERE id = ?", (contact_id,))
        return self._contact(rows[0]) if rows else None

    def pending_contacts(self):
        return [
            self._contact(r)
            for r in self._query("SELECT * FROM contacts WHERE status = ? ORDER BY id", (PENDING,))
        ]

    def counts(self):
        result = {PENDING: 0, SERVER: 0, SENT: 0, ERROR: 0}
        for row in self._query("SELECT status, COUNT(*) FROM contacts GROUP BY status"):
            result[row[0]] = row[1]
        result["total"] = sum(result.values())
        return result

    def extra_field_names(self):
        """Listedeki ek sütun adları (ilk görülme sırasıyla)."""
        names = []
        for row in self._query("SELECT extra FROM contacts ORDER BY id"):
            try:
                keys = json.loads(row[0] or "{}").keys()
            except ValueError:
                continue
            for key in keys:
                if key not in names:
                    names.append(key)
        return names

    def mark_sent(self, contact_id, message_id=None, thread_id=None, subject=None, sent_at=None, template=None):
        self._execute(
            "UPDATE contacts SET status = ?, sent_at = ?, error = NULL, message_id = ?, thread_id = ?, "
            "sent_subject = ?, reply_status = ?, draft_id = NULL, scheduled_for = NULL, "
            "sent_template = COALESCE(?, sent_template) WHERE id = ?",
            (SENT, sent_at or now_str(), message_id, thread_id, subject, REPLY_NONE if thread_id else None, template,
             contact_id),
        )

    # ---------- Google sunucusuyla planlananlar ----------

    def mark_server_planned(self, contact_id, draft_id, message_id, thread_id, subject, scheduled_for, recipients,
                            template=None):
        self._execute(
            "UPDATE contacts SET status = ?, error = NULL, draft_id = ?, message_id = ?, thread_id = ?, "
            "sent_subject = ?, scheduled_for = ?, recipients = ?, sent_template = ? WHERE id = ?",
            (SERVER, draft_id, message_id, thread_id, subject, scheduled_for, recipients, template, contact_id),
        )

    def server_planned_contacts(self):
        return [self._contact(r) for r in self._query("SELECT * FROM contacts WHERE status = ? ORDER BY id", (SERVER,))]

    def unplan_server(self, contact_id):
        """Google planı iptal edildi: firma tekrar 'Bekliyor'."""
        self._execute(
            "UPDATE contacts SET status = ?, draft_id = NULL, message_id = NULL, thread_id = NULL, "
            "sent_subject = NULL, scheduled_for = NULL, recipients = NULL WHERE id = ?",
            (PENDING, contact_id),
        )

    def mark_error(self, contact_id, message):
        self._execute(
            "UPDATE contacts SET status = ?, error = ? WHERE id = ?", (ERROR, message, contact_id)
        )

    def set_pending(self, contact_ids):
        with self._lock:
            # Tekrar gönderilecekse eski konuşmanın takip bilgileri de sıfırlanır.
            self._conn.executemany(
                "UPDATE contacts SET status = ?, error = NULL, sent_at = NULL, message_id = NULL, "
                "thread_id = NULL, sent_subject = NULL, rfc_message_id = NULL, reply_status = NULL, "
                "reply_at = NULL, reply_from = NULL, reminder_count = 0, last_reminder_at = NULL, "
                "manual_reply = 0, sent_template = NULL WHERE id = ?",
                [(PENDING, cid) for cid in contact_ids],
            )
            self._conn.commit()

    # ---------- Cevap takibi ve hatırlatma ----------

    def contacts_to_check(self):
        """Cevabı henüz kesinleşmemiş (cevap yok / otomatik yanıt / hiç bakılmamış) gönderilmiş firmalar."""
        return [
            self._contact(r) for r in self._query(
                "SELECT * FROM contacts WHERE status = ? AND thread_id IS NOT NULL AND manual_reply = 0 "
                "AND COALESCE(reply_status, '') NOT IN (?, ?) ORDER BY id",
                (SENT, REPLY_YES, REPLY_BOUNCED),
            )
        ]

    def update_reply(self, contact_id, status, reply_at=None, reply_from=None):
        self._execute(
            "UPDATE contacts SET reply_status = ?, reply_at = ?, reply_from = ? WHERE id = ?",
            (status, reply_at, reply_from, contact_id),
        )

    def set_manual_reply(self, contact_id, value):
        self._execute("UPDATE contacts SET manual_reply = ? WHERE id = ?", (1 if value else 0, contact_id))

    def set_rfc_message_id(self, contact_id, value):
        self._execute("UPDATE contacts SET rfc_message_id = ? WHERE id = ?", (value, contact_id))

    def mark_reminded(self, contact_id):
        self._execute(
            "UPDATE contacts SET reminder_count = reminder_count + 1, last_reminder_at = ? WHERE id = ?",
            (now_str(), contact_id),
        )

    def retry_errors(self):
        cur = self._execute(
            "UPDATE contacts SET status = ?, error = NULL WHERE status = ?", (PENDING, ERROR)
        )
        return cur.rowcount

    def delete_contacts(self, contact_ids):
        with self._lock:
            self._conn.executemany("DELETE FROM contacts WHERE id = ?", [(cid,) for cid in contact_ids])
            self._conn.commit()

    def delete_all_contacts(self):
        self._execute("DELETE FROM contacts")

    # ---------- Gönderim kaydı (günlük limit için) ----------

    def log_send(self, recipients, to_email, kind="campaign", sent_at=None):
        self._execute(
            "INSERT INTO send_log (sent_at, recipients, to_email, kind) VALUES (?, ?, ?, ?)",
            (sent_at or now_str(), recipients, to_email, kind),
        )

    def recipients_last_24h(self):
        """Gmail'in limiti kayan 24 saatlik pencerede sayılır; biz de öyle sayıyoruz."""
        since = (datetime.now() - timedelta(hours=24)).strftime(TIME_FORMAT)
        rows = self._query("SELECT COALESCE(SUM(recipients), 0) FROM send_log WHERE sent_at >= ?", (since,))
        return rows[0][0]

    # ---------- Şablonlar ----------

    def template_names(self):
        return [r[0] for r in self._query("SELECT name FROM templates ORDER BY name COLLATE NOCASE")]

    def get_template(self, name):
        rows = self._query("SELECT * FROM templates WHERE name = ?", (name,))
        return dict(rows[0]) if rows else None

    def save_template(self, name, subject, body, attachment):
        self._execute(
            "INSERT INTO templates (name, subject, body, attachment, updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET subject = excluded.subject, body = excluded.body, "
            "attachment = excluded.attachment, updated_at = excluded.updated_at",
            (name, subject, body, attachment, now_str()),
        )

    def delete_template(self, name):
        self._execute("DELETE FROM templates WHERE name = ?", (name,))

    # ---------- Ayarlar ----------

    def get_setting(self, key, default=None):
        rows = self._query("SELECT value FROM settings WHERE key = ?", (key,))
        return rows[0][0] if rows and rows[0][0] is not None else default

    def set_setting(self, key, value):
        self._execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, None if value is None else str(value)),
        )

    def close(self):
        with self._lock:
            self._conn.close()
