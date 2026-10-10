"""Toplu gönderimi ve hatırlatmaları arayüzü dondurmadan ayrı bir thread'de yürütür."""
import logging
import threading
from dataclasses import dataclass, field

import quota
from database import PENDING, REPLY_BOUNCED, REPLY_YES
from gmail_client import GmailError
from replies import awaiting_reply, refresh_contact
from template_engine import contact_fields, render, render_mail

log = logging.getLogger(__name__)

USER_STOPPED = "Gönderimi siz durdurdunuz."


@dataclass
class SendJob:
    subject: str
    body: str
    cc: list = field(default_factory=list)
    attachments: list = field(default_factory=list)
    signature: dict = None
    sender_name: str = ""
    delay: float = 5
    daily_limit: int = 200
    max_count: int = 0  # bir seferde en fazla kaç firma (0 = sınırsız)
    template_name: str = None  # kayıt için: hangi şablonla gönderildi


@dataclass
class ReminderJob:
    body: str
    contact_ids: list
    cc: list = field(default_factory=list)
    signature: dict = None
    sender_name: str = ""
    delay: float = 5
    daily_limit: int = 200


def reply_subject(subject):
    subject = (subject or "").strip()
    return subject if subject.lower().startswith(("re:", "ynt:")) else f"Re: {subject}"


class _BatchWorker(threading.Thread):
    """Ortak iskelet: sırayla işler, limit kontrolü, bekleme ve durdurma.

    Arayüze doğrudan dokunmaz; olayları notify(dict) ile bildirir. Her mail gönderildiği anda
    veritabanına işlenir, böylece uygulama kapanırsa kaldığı yerden devam edilebilir.
    """

    def __init__(self, db, gmail, job, notify):
        super().__init__(daemon=True)
        self.db = db
        self.gmail = gmail
        self.job = job
        self.notify = notify
        self._stop_event = threading.Event()
        self.per_mail = 1 + len(job.cc)

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()

    def limit_message(self):
        """Bir mail daha limiti aşacaksa sebep metni, aşmayacaksa None."""
        used, reserved = quota.gmail_used(self.db)
        if used + reserved + self.per_mail > self.job.daily_limit:
            extra = f" + Google'da planlı {reserved}" if reserved else ""
            return (
                f"Günlük limite ulaşıldı (son 24 saatte {used}{extra} / {self.job.daily_limit} alıcı).\n"
                "Kalanlar bekliyor; daha sonra tekrar başlatınca kaldığı yerden devam eder."
            )
        return None

    def wait(self):
        """Mailler arası bekleme. Bekleme sırasında durdurulursa True döner."""
        return self.job.delay > 0 and self._stop_event.wait(self.job.delay)

    def run(self):
        try:
            self.process()
        except Exception:
            log.exception("Gönderim sırasında beklenmeyen hata")
            self.notify({"type": "finished", "sent": 0, "failed": 0, "skipped": 0,
                         "stop_reason": "Beklenmeyen bir hata oluştu. Ayrıntılar uygulama.log dosyasında."})

    def process(self):
        raise NotImplementedError


class SendWorker(_BatchWorker):
    """'Bekliyor' durumundaki firmalara ilk maili gönderir."""

    def process(self):
        job = self.job
        contacts = self.db.pending_contacts()
        total = len(contacts)
        sent = failed = 0
        stop_reason = None
        self.notify({"type": "start", "total": total})
        log.info("Gönderim başladı: %d firma, mail başına %d alıcı", total, self.per_mail)

        for index, contact in enumerate(contacts, start=1):
            if self.stopped:
                stop_reason = USER_STOPPED
                break
            if job.max_count and sent >= job.max_count:
                stop_reason = (f"Bu seferlik {job.max_count} firmaya gönderildi (ayarlardaki 'bir seferde en fazla'). "
                               "Kalanlar 'Bekliyor' durumunda.")
                break

            # Gönderim sürerken liste değişmiş olabilir.
            contact = self.db.get_contact(contact["id"])
            if not contact or contact["status"] != PENDING:
                self.notify({"type": "skipped", "index": index, "total": total})
                continue

            stop_reason = self.limit_message()
            if stop_reason:
                break

            self.notify({"type": "sending", "index": index, "total": total, "contact": contact})
            subject, body, missing = render_mail(job.subject, job.body, contact)
            if missing:
                message = "Eksik alan: " + ", ".join("{{" + m + "}}" for m in missing)
                self.db.mark_error(contact["id"], message)
                failed += 1
                self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                             "ok": False, "message": message})
                continue

            try:
                result = self.gmail.send(contact["email"], subject, body, job.cc, job.attachments, job.sender_name,
                                         signature=job.signature)
            except GmailError as exc:
                if exc.fatal:
                    stop_reason = exc.message
                    break
                self.db.mark_error(contact["id"], exc.message)
                failed += 1
                self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                             "ok": False, "message": exc.message})
            else:
                self.db.mark_sent(contact["id"], result.get("id"), result.get("threadId"), subject,
                                  template=job.template_name)
                self.db.log_send(self.per_mail, contact["email"])
                sent += 1
                self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                             "ok": True, "message": ""})

            if index < total and self.wait():
                stop_reason = USER_STOPPED
                break

        log.info("Gönderim bitti: %d gönderildi, %d hata, sebep: %s", sent, failed, stop_reason)
        self.notify({"type": "finished", "sent": sent, "failed": failed, "skipped": 0, "stop_reason": stop_reason})


class ReminderWorker(_BatchWorker):
    """Cevap vermeyen firmalara, ilk mailin cevabı olarak (aynı konuşmada) hatırlatma gönderir."""

    def process(self):
        job = self.job
        total = len(job.contact_ids)
        internal = list(job.cc)
        sent = failed = skipped = 0
        stop_reason = None
        self.notify({"type": "start", "total": total})
        log.info("Hatırlatma başladı: %d firma", total)

        for index, contact_id in enumerate(job.contact_ids, start=1):
            if self.stopped:
                stop_reason = USER_STOPPED
                break
            contact = self.db.get_contact(contact_id)
            if (not contact or not awaiting_reply(contact) or not contact.get("thread_id")
                    or contact.get("reminder_draft_id")):
                skipped += 1
                self.notify({"type": "skipped", "index": index, "total": total})
                continue

            stop_reason = self.limit_message()
            if stop_reason:
                break
            self.notify({"type": "sending", "index": index, "total": total, "contact": contact})

            try:
                # Son anda tekrar bak: bu arada cevap verdiyse hatırlatma gitmesin.
                status = refresh_contact(self.db, self.gmail, contact, internal)
                if status is None or status in (REPLY_YES, REPLY_BOUNCED):
                    reason = {REPLY_YES: "Bu arada cevap gelmiş, gönderilmedi.",
                              REPLY_BOUNCED: "Mail adrese ulaşmamış, gönderilmedi."}.get(
                                  status, "Gmail'de ilk mail bulunamadı, gönderilmedi.")
                    skipped += 1
                    self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                                 "ok": None, "message": reason})
                    continue

                body, missing = render(job.body, contact_fields(contact))
                if missing:
                    failed += 1
                    self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                                 "ok": False, "message": "Eksik alan: " + ", ".join("{{" + m + "}}" for m in missing)})
                    continue

                rfc_id = contact.get("rfc_message_id")
                if not rfc_id and contact.get("message_id"):
                    rfc_id = self.gmail.get_rfc_message_id(contact["message_id"])
                    if rfc_id:
                        self.db.set_rfc_message_id(contact["id"], rfc_id)

                self.gmail.send(contact["email"], reply_subject(contact.get("sent_subject")), body, job.cc,
                                None, job.sender_name, thread_id=contact["thread_id"], in_reply_to=rfc_id,
                                signature=job.signature)
            except GmailError as exc:
                if exc.fatal:
                    stop_reason = exc.message
                    break
                failed += 1
                self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                             "ok": False, "message": exc.message})
            else:
                self.db.mark_reminded(contact["id"])
                self.db.log_send(self.per_mail, contact["email"], kind="reminder")
                sent += 1
                self.notify({"type": "result", "index": index, "total": total, "contact": contact,
                             "ok": True, "message": ""})

            if index < total and self.wait():
                stop_reason = USER_STOPPED
                break

        log.info("Hatırlatma bitti: %d gönderildi, %d atlandı, %d hata, sebep: %s", sent, skipped, failed, stop_reason)
        self.notify({"type": "finished", "sent": sent, "failed": failed, "skipped": skipped,
                     "stop_reason": stop_reason})
