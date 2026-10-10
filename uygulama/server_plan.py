"""Google sunucusuyla planlı gönderim: bilgisayar kapalıyken de belirlenen saatte gider.

Gmail'in kendi 'gönderme zamanını planla' özelliği API'ye açık değil. Bunun yerine:
  1. Uygulama, mailleri Gmail'e TASLAK olarak koyar; her taslağa gönderim zamanı başlığı ekler.
  2. Kullanıcının Google hesabında çalışan küçük bir Apps Script (SCRIPT_CODE) 5 dakikada bir
     zamanı gelen taslakları gönderir. Sadece bu başlığı taşıyan taslaklara dokunur.
  3. Uygulama açıldığında taslakların gönderildiğini Gmail'den okuyup listeyi günceller.
Google, Apps Script ile gönderimde normal hesaplara günde 100 alıcı sınırı uygular (CC dahil).
"""
import logging
from datetime import datetime, timedelta, timezone

from database import TIME_FORMAT, now_str
from gmail_client import GmailError
from template_engine import contact_fields, render, render_mail

log = logging.getLogger(__name__)

WINDOW_MINUTES = 30  # Apps Script tarafındaki PENCERE_DAKIKA ile aynı olmalı
# Google'daki kodun sürümü. Değişince kullanıcıya 'kodu güncelleyin' denir (Kurulum → Kodu kopyala).
SCRIPT_VERSION = 2

H_TIME = "X-Sponsorluk-Zaman"
H_SLOTS = "X-Sponsorluk-Saatler"
H_OFFSET = "X-Sponsorluk-Utc-Fark"
H_WEEKEND = "X-Sponsorluk-Haftasonu"
H_ORDER = "X-Sponsorluk-Sira"
H_TEST = "X-Sponsorluk-Test"
# Hatırlatma taslakları ayrı başlık kullanır: eski (v1) kod bunları hiç görmez, yani cevap kontrolü
# yapmadan gönderemez. Sadece v2+ kod, göndermeden önce konuşmada cevap var mı diye bakar.
H_REMINDER_TIME = "X-Sponsorluk-Hatirlatma-Zaman"
H_INTERNAL = "X-Sponsorluk-Ic"  # cevap sayılmayacak ekip adresleri (sabit CC)

SCRIPT_URL = "https://script.google.com/home/projects/create"

SCRIPT_CODE = r"""/**
 * Sponsorluk Mail Gönderici - Google sunucusu gönderim kodu
 *
 * Uygulamanın Gmail'e koyduğu taslakları (ilk mailler ve hatırlatmalar) belirlenen saatte gönderir.
 * Hatırlatmayı göndermeden önce konuşmaya bakar: firma bu arada cevap verdiyse hatırlatmayı göndermez, siler.
 * Sadece uygulamanın işaretlediği taslaklara dokunur; sizin kendi taslaklarınıza dokunmaz.
 *
 * KURULUM: Üstteki listeden "kurulum" fonksiyonunu seçip "Çalıştır"a basın (bir kez yeterli).
 */
var BASLIK_ZAMAN = 'X-Sponsorluk-Zaman';
var BASLIK_SAATLER = 'X-Sponsorluk-Saatler';
var BASLIK_UTC_FARK = 'X-Sponsorluk-Utc-Fark';
var BASLIK_HAFTASONU = 'X-Sponsorluk-Haftasonu';
var BASLIK_SIRA = 'X-Sponsorluk-Sira';
var BASLIK_TEST = 'X-Sponsorluk-Test';
var BASLIK_HATIRLATMA_ZAMAN = 'X-Sponsorluk-Hatirlatma-Zaman';
var BASLIK_IC = 'X-Sponsorluk-Ic';
var KOD_SURUMU = 2;
var PENCERE_DAKIKA = 30;        // saat geldikten sonra bu süre içinde gönderilir
var BEKLEME_MS = 3000;          // mailler arası bekleme
var TEK_SEFERDE_EN_FAZLA = 60;  // bir çalışmada en fazla kaç mail

function kurulum() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'zamaniGelenleriGonder') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('zamaniGelenleriGonder').timeBased().everyMinutes(5).create();
  Logger.log('Kurulum tamam (kod sürümü ' + KOD_SURUMU + '): 5 dakikada bir kontrol edilecek. '
             + 'Bugünkü kalan alıcı kotası: ' + MailApp.getRemainingDailyQuota());
}

function pencereIcinde(simdi, saatler, utcFarkDakika, haftasonuGonder) {
  var yerel = new Date(simdi.getTime() + utcFarkDakika * 60000);
  var gun = yerel.getUTCDay();  // 0 = Pazar, 6 = Cumartesi
  if (!haftasonuGonder && (gun === 0 || gun === 6)) return false;
  var dakika = yerel.getUTCHours() * 60 + yerel.getUTCMinutes();
  return saatler.split(',').some(function (s) {
    var p = s.trim().split(':');
    if (p.length !== 2) return false;
    var baslangic = Number(p[0]) * 60 + Number(p[1]);
    return dakika >= baslangic && dakika < baslangic + PENCERE_DAKIKA;
  });
}

function aliciSayisi(mesaj) {
  return [mesaj.getTo(), mesaj.getCc()].join(',').split(',')
    .filter(function (a) { return a.trim(); }).length;
}

function adres(metin) {
  var m = String(metin || '').match(/<([^>]+)>/);
  return (m ? m[1] : String(metin || '')).trim().toLowerCase();
}

function otomatikYanitMi(m) {
  var oto = String(m.getHeader('Auto-Submitted') || '').toLowerCase();
  if (oto && oto !== 'no') return true;
  if (m.getHeader('X-Autoreply') || m.getHeader('X-Autorespond')) return true;
  var konu = String(m.getSubject() || '').toLowerCase();
  return ['otomatik yanıt', 'otomatik cevap', 'automatic reply', 'auto reply', 'auto-reply', 'out of office',
          'ofis dışında'].some(function (s) { return konu.indexOf(s) !== -1; });
}

// Konuşmada firmadan (ya da 'ulaşmadı' bildirimi olarak) mesaj var mı? Ekip adresleri ve otomatik yanıtlar sayılmaz.
function cevapVarMi(mesaj) {
  var ben = adres(Session.getEffectiveUser().getEmail());
  var ic = String(mesaj.getHeader(BASLIK_IC) || '').toLowerCase().split(',')
    .map(function (a) { return a.trim(); }).filter(String);
  return mesaj.getThread().getMessages().some(function (m) {
    if (m.isDraft()) return false;
    var kimden = adres(m.getFrom());
    if (!kimden || kimden === ben || ic.indexOf(kimden) !== -1) return false;
    return !otomatikYanitMi(m);
  });
}

function zamaniGelenleriGonder() {
  var kilit = LockService.getScriptLock();
  if (!kilit.tryLock(1000)) return;
  try {
    var simdi = new Date();
    var sira = [];
    GmailApp.getDrafts().forEach(function (taslak) {
      var mesaj = taslak.getMessage();
      var zaman = mesaj.getHeader(BASLIK_ZAMAN);
      var hatirlatma = false;
      if (!zaman) {
        zaman = mesaj.getHeader(BASLIK_HATIRLATMA_ZAMAN);
        hatirlatma = !!zaman;
      }
      if (!zaman) return;  // uygulamanın taslağı değil
      var enErken = new Date(zaman);
      if (isNaN(enErken.getTime()) || enErken > simdi) return;
      var test = mesaj.getHeader(BASLIK_TEST) === '1';
      if (!test && !pencereIcinde(simdi, mesaj.getHeader(BASLIK_SAATLER) || '',
                                  Number(mesaj.getHeader(BASLIK_UTC_FARK) || 0),
                                  mesaj.getHeader(BASLIK_HAFTASONU) === '1')) return;
      if (hatirlatma && cevapVarMi(mesaj)) {
        taslak.deleteDraft();  // firma bu arada cevap verdi: hatırlatma gereksiz
        Logger.log('Cevap gelmiş, hatırlatma gönderilmedi: ' + mesaj.getTo());
        return;
      }
      sira.push({ taslak: taslak, zaman: enErken.getTime(),
                  no: Number(mesaj.getHeader(BASLIK_SIRA) || 0), alici: aliciSayisi(mesaj) });
    });
    sira.sort(function (a, b) { return a.zaman - b.zaman || a.no - b.no; });
    var kota = MailApp.getRemainingDailyQuota();
    var gonderilen = 0;
    for (var i = 0; i < sira.length && gonderilen < TEK_SEFERDE_EN_FAZLA; i++) {
      if (sira[i].alici > kota) {
        Logger.log('Günlük kota doldu; kalanlar sonraki gönderim saatinde gidecek.');
        break;
      }
      try {
        sira[i].taslak.send();
        kota -= sira[i].alici;
        gonderilen++;
        Utilities.sleep(BEKLEME_MS);
      } catch (e) {
        Logger.log('Gönderilemedi: ' + e);
      }
    }
    if (gonderilen) Logger.log(gonderilen + ' mail gönderildi.');
  } finally {
    kilit.releaseLock();
  }
}
"""


def utc_offset_minutes():
    return int(datetime.now().astimezone().utcoffset().total_seconds() // 60)


def plan_headers(when, slots_text, skip_weekends, order=0, test=False, reminder=False, internal=()):
    """Taslağa eklenen, Google sunucusundaki kodun okuyacağı başlıklar."""
    headers = {
        (H_REMINDER_TIME if reminder else H_TIME): when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        H_SLOTS: slots_text,
        H_OFFSET: str(utc_offset_minutes()),
        H_WEEKEND: "0" if skip_weekends else "1",
        H_ORDER: str(order),
    }
    if test:
        headers[H_TEST] = "1"
    if reminder:
        headers[H_INTERNAL] = ",".join(internal)
    return headers


def script_needs_update(db):
    """Kurulum yapılmış ama Google'daki kod eski sürümde mi?"""
    copied = int(db.get_setting("server_script_version", "1") or 1)
    return bool(db.get_setting("server_verified")) and copied < SCRIPT_VERSION


def create_plan(db, gmail, items, mail, cc, signature, sender_name, slots_text, skip_weekends, progress=None,
                template_name=None):
    """items: [(firma, gönderim zamanı)]. Taslakları oluşturur. (planlanan, eksik alanlı) sayısı döner."""
    planned = skipped = 0
    per_mail = 1 + len(cc)
    for order, (contact, when) in enumerate(items, start=1):
        subject, body, missing = render_mail(mail["subject"], mail["body"], contact)
        if missing:
            db.mark_error(contact["id"], "Eksik alan: " + ", ".join("{{" + m + "}}" for m in missing))
            skipped += 1
        else:
            draft = gmail.create_draft(contact["email"], subject, body, cc, mail["attachments"], sender_name,
                                       signature, plan_headers(when, slots_text, skip_weekends, order))
            db.mark_server_planned(contact["id"], draft["draft_id"], draft["message_id"], draft["thread_id"],
                                   subject, when.strftime(TIME_FORMAT), per_mail, template_name)
            planned += 1
        if progress:
            progress(order, len(items))
    log.info("Google sunucusuyla planlandı: %d firma (%d eksik alan)", planned, skipped)
    return planned, skipped


def create_reminder_plan(db, gmail, items, body, cc, signature, sender_name, slots_text, skip_weekends, me,
                         progress=None):
    """items: [(firma, zaman)]. Hatırlatmaları ilk mailin konuşmasına taslak olarak koyar. (planlanan, atlanan)"""
    from sender import reply_subject
    planned = skipped = 0
    per_mail = 1 + len(cc)
    internal = [a.lower() for a in cc] + ([me.lower()] if me else [])
    for order, (contact, when) in enumerate(items, start=1):
        text, missing = render(body, contact_fields(contact))
        if missing or not contact.get("thread_id"):
            skipped += 1
        else:
            rfc_id = contact.get("rfc_message_id")
            if not rfc_id and contact.get("message_id"):
                rfc_id = gmail.get_rfc_message_id(contact["message_id"])
                if rfc_id:
                    db.set_rfc_message_id(contact["id"], rfc_id)
            draft = gmail.create_draft(
                contact["email"], reply_subject(contact.get("sent_subject")), text, cc, None, sender_name, signature,
                plan_headers(when, slots_text, skip_weekends, order, reminder=True, internal=internal),
                thread_id=contact["thread_id"], in_reply_to=rfc_id)
            db.mark_reminder_planned(contact["id"], draft["draft_id"], draft["message_id"],
                                     when.strftime(TIME_FORMAT), per_mail)
            planned += 1
        if progress:
            progress(order, len(items))
    log.info("Hatırlatma Google sunucusuyla planlandı: %d firma (%d atlandı)", planned, skipped)
    return planned, skipped


def _sent_message(messages, after_ms=0):
    for m in messages:
        if "SENT" in m["labels"] and "DRAFT" not in m["labels"] and m["internal_date"] >= after_ms:
            return m
    return None


def _planned_at_ms(contact):
    try:
        return int(datetime.strptime(contact["reminder_planned_at"], TIME_FORMAT).timestamp() * 1000)
    except (TypeError, ValueError):
        return 0


def _sync_reminder(db, contact, messages):
    """Planlı hatırlatmanın durumu: 'planned' (bekliyor), 'sent' (gitti) ya da 'dropped' (cevap geldi/silindi)."""
    if messages and any(m["id"] == contact.get("reminder_message_id") and "DRAFT" in m["labels"] for m in messages):
        return "planned"
    sent = _sent_message(messages or [], _planned_at_ms(contact))
    if sent:
        sent_at = datetime.fromtimestamp(sent["internal_date"] / 1000).strftime(TIME_FORMAT)
        db.mark_reminded(contact["id"], at=sent_at)
        db.log_send(contact.get("reminder_recipients") or 1, contact["email"], kind="server_reminder", sent_at=sent_at)
        return "sent"
    db.clear_reminder_plan(contact["id"])
    return "dropped"


def sync(db, gmail):
    """Google sunucusunun gönderdiklerini bulup listeyi günceller. Test mailini de kontrol eder."""
    result = {"sent": [], "missing": [], "test_ok": False}
    for c in db.server_planned_contacts():
        try:
            messages = gmail.get_thread_messages(c["thread_id"]) if c.get("thread_id") else None
        except GmailError as exc:
            if exc.fatal:
                raise
            continue
        if messages is None:
            # Taslak da gönderilmiş mail de yok: elle silinmiş olabilir. Tekrar gönderim riski olmasın diye
            # otomatik 'Bekliyor' yapılmaz, kullanıcıya bildirilir.
            db.mark_error(c["id"], "Google taslağı bulunamadı. Gmail 'Gönderilenler'e bakın; gitmediyse "
                                   "'Bekliyor' yapıp tekrar planlayın.")
            result["missing"].append(c["firma"] or c["email"])
            continue
        sent = _sent_message(messages)
        if sent:
            sent_at = datetime.fromtimestamp(sent["internal_date"] / 1000).strftime(TIME_FORMAT)
            db.mark_sent(c["id"], sent["id"], c["thread_id"], c.get("sent_subject"), sent_at=sent_at)
            db.log_send(c.get("recipients") or 1, c["email"], kind="server", sent_at=sent_at)
            result["sent"].append(c["firma"] or c["email"])

    result["reminders_sent"], result["reminders_dropped"] = [], []
    for c in db.reminder_planned_contacts():
        try:
            messages = gmail.get_thread_messages(c["thread_id"]) if c.get("thread_id") else None
        except GmailError as exc:
            if exc.fatal:
                raise
            continue
        state = _sync_reminder(db, c, messages)
        if state == "sent":
            result["reminders_sent"].append(c["firma"] or c["email"])
        elif state == "dropped":
            result["reminders_dropped"].append(c["firma"] or c["email"])

    test_thread = db.get_setting("server_test_thread")
    if test_thread:
        messages = gmail.get_thread_messages(test_thread)
        if messages and _sent_message(messages):
            db.set_setting("server_verified", now_str())
            db.set_setting("server_test_thread", "")
            result["test_ok"] = True
    return result


def cancel_plan(db, gmail):
    """Google'daki planlı taslakları siler; firmalar 'Bekliyor'a döner. (iptal edilen, bu arada gönderilmiş)"""
    cancelled = already_sent = 0
    for c in db.server_planned_contacts():
        if c.get("draft_id") and gmail.delete_draft(c["draft_id"]):
            db.unplan_server(c["id"])
            cancelled += 1
            continue
        messages = gmail.get_thread_messages(c["thread_id"]) if c.get("thread_id") else None
        sent = _sent_message(messages or [])
        if sent:
            sent_at = datetime.fromtimestamp(sent["internal_date"] / 1000).strftime(TIME_FORMAT)
            db.mark_sent(c["id"], sent["id"], c["thread_id"], c.get("sent_subject"), sent_at=sent_at)
            already_sent += 1
        else:
            db.unplan_server(c["id"])
            cancelled += 1
    return cancelled, already_sent


def cancel_reminder_plan(db, gmail):
    """Google'daki planlı hatırlatma taslaklarını siler. (iptal edilen, bu arada gönderilmiş)"""
    cancelled = already_sent = 0
    for c in db.reminder_planned_contacts():
        if gmail.delete_draft(c["reminder_draft_id"]):
            db.clear_reminder_plan(c["id"])
            cancelled += 1
            continue
        messages = gmail.get_thread_messages(c["thread_id"]) if c.get("thread_id") else None
        if _sync_reminder(db, c, messages) == "sent":
            already_sent += 1
        else:
            cancelled += 1
    return cancelled, already_sent


def send_test(db, gmail, slots_text):
    """Kendine, sunucunun hemen göndereceği bir test taslağı koyar."""
    when = datetime.now() - timedelta(minutes=1)
    draft = gmail.create_draft(
        gmail.email, "[TEST] Google sunucusu çalışıyor",
        "Bu mail Google sunucusundaki kod tarafından gönderildi. Kurulum tamam!\n\n"
        "Bu maili silebilirsiniz.", None, None, "", None, plan_headers(when, slots_text, False, 0, test=True))
    db.set_setting("server_test_thread", draft["thread_id"])
    db.set_setting("server_test_at", now_str())
    return draft
