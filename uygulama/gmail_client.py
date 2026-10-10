"""Gmail API bağlantısı (OAuth) ve mail gönderimi."""
import base64
import io
import json
import logging
import mimetypes
import os
import re
import threading
from email.headerregistry import Address
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

# Google, izin verilen yetkileri farklı sırada döndürebiliyor; oauthlib bunu hata saymasın.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

import httplib2  # noqa: E402
from google.auth.exceptions import RefreshError, TransportError  # noqa: E402
from google.auth.transport.requests import AuthorizedSession, Request  # noqa: E402
from google.oauth2.credentials import Credentials  # noqa: E402
from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: E402
from googleapiclient.discovery import build  # noqa: E402
from googleapiclient.errors import HttpError  # noqa: E402
from googleapiclient.http import MediaIoBaseUpload  # noqa: E402

from mail_format import html_body, plain_body, signature_images  # noqa: E402

log = logging.getLogger(__name__)

# gmail.send: mail gönderme.
# gmail.metadata: sadece başlıkları (kimden, konu, tarih) okur; mail içeriklerini ve ekleri OKUYAMAZ.
#   Gönderdiğimiz maillere cevap gelip gelmediğini anlamak için gerekli.
# gmail.compose: Google sunucusunun belirlenen saatte göndereceği taslakları oluşturmak/silmek için.
# userinfo.email: bağlı hesabın adresini üstte göstermek için.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.metadata",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/userinfo.email",
]
THREAD_HEADERS = ["From", "Subject", "Auto-Submitted", "X-Autoreply", "X-Autorespond", "Precedence"]
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
# 'raw' ile gönderimde istek 5 MB'ı geçemez (base64 ~%33 büyütür); büyük mailler upload ile gider.
RAW_SIZE_LIMIT = 3_500_000
QUOTA_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "dailyLimitExceeded", "quotaExceeded"}

SESSION_EXPIRED = (
    "Gmail oturumunun süresi dolmuş.\n"
    "Üstteki 'Hesabı değiştir' butonuyla tekrar bağlanın."
)
NETWORK_ERROR = "İnternet bağlantısı kurulamadı. Bağlantınızı kontrol edip tekrar deneyin."


class GmailError(Exception):
    """Kullanıcıya gösterilecek Türkçe mesaj taşır.

    fatal=True: sorun tüm gönderimi etkiler (oturum, limit, internet) -> gönderim durur.
    fatal=False: sadece bu alıcıyla ilgili (ör. hatalı adres) -> firma 'Hata' olur, devam edilir.
    """

    def __init__(self, message, fatal=False, status=None):
        super().__init__(message)
        self.message = message
        self.fatal = fatal
        self.status = status  # HTTP durum kodu (varsa)


class GmailClient:
    def __init__(self, credentials_file, token_file):
        self.credentials_file = Path(credentials_file)
        self.token_file = Path(token_file)
        self.email = None
        # Kayıtlı oturum var ama yeni eklenen izinleri içermiyor -> kullanıcı tekrar bağlanmalı.
        self.needs_reconsent = False
        self._creds = None
        self._service = None
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._service is not None and bool(self.email)

    def has_credentials_file(self):
        return self.credentials_file.exists()

    # ---------- Bağlantı ----------

    def load_saved_login(self):
        """Daha önce kaydedilmiş oturum varsa sessizce bağlanır. Başarılıysa True döner."""
        if not self.token_file.exists():
            return False
        try:
            creds = Credentials.from_authorized_user_file(str(self.token_file), SCOPES)
        except (ValueError, KeyError, json.JSONDecodeError):
            log.warning("Token dosyası okunamadı, yeniden giriş gerekecek.", exc_info=True)
            return False
        if not creds.has_scopes(SCOPES):
            self.needs_reconsent = True
            return False
        if not creds.valid:
            if not creds.refresh_token:
                return False
            try:
                creds.refresh(Request())
            except RefreshError:
                log.warning("Kayıtlı oturum yenilenemedi (süresi dolmuş olabilir).", exc_info=True)
                return False
            except TransportError as exc:
                raise GmailError(NETWORK_ERROR, fatal=True) from exc
            self._save_token(creds)
        self._activate(creds)
        return True

    def connect(self):
        """Tarayıcıda Google girişini açar ve oturumu kaydeder. (Arka plan thread'inde çağrılmalı.)"""
        if not self.has_credentials_file():
            raise GmailError(
                "credentials.json bulunamadı.\n\n"
                f"Google Cloud'dan indirdiğiniz dosyayı şu klasöre 'credentials.json' adıyla koyun:\n"
                f"{self.credentials_file.parent}\n\nAdımlar README.md dosyasında."
            )
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_file), SCOPES)
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            log.exception("credentials.json okunamadı")
            raise GmailError(
                "credentials.json dosyası geçersiz.\n"
                "Google Cloud'da 'Masaüstü uygulaması (Desktop app)' türünde oluşturup indirdiğinizden emin olun."
            ) from exc
        try:
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                timeout_seconds=300,
                authorization_prompt_message="",
                success_message="Baglanti basarili! Bu sekmeyi kapatip uygulamaya donebilirsiniz.",
            )
        except Exception as exc:
            log.exception("Google girişi tamamlanamadı")
            raise GmailError(
                "Google girişi tamamlanamadı (iptal edildi ya da 5 dakika içinde onaylanmadı).\n"
                "Tekrar deneyin. 'Erişim engellendi' gördüyseniz kendinizi test kullanıcısı olarak "
                "eklediğinizden emin olun (README)."
            ) from exc
        if not creds:
            raise GmailError("Google girişi tamamlanamadı. Tekrar deneyin.")
        self._save_token(creds)
        self.needs_reconsent = False
        self._activate(creds)

    def disconnect(self):
        self._creds = None
        self._service = None
        self.email = None
        try:
            self.token_file.unlink(missing_ok=True)
        except OSError:
            log.warning("Token dosyası silinemedi", exc_info=True)

    def _activate(self, creds):
        self._creds = creds
        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        self.email = self._fetch_email(creds)

    def _fetch_email(self, creds):
        try:
            response = AuthorizedSession(creds).get(USERINFO_URL, timeout=20)
            response.raise_for_status()
            return response.json().get("email")
        except Exception as exc:
            log.exception("Hesap adresi alınamadı")
            self._service = None
            raise GmailError("Bağlı Gmail adresi öğrenilemedi. İnternet bağlantınızı kontrol edip tekrar bağlanın.") from exc

    def _save_token(self, creds):
        try:
            self.token_file.write_text(creds.to_json(), encoding="utf-8")
        except OSError:
            log.exception("Token kaydedilemedi")

    def _ensure_fresh(self):
        if self._creds and not self._creds.valid and self._creds.refresh_token:
            self._creds.refresh(Request())
            self._save_token(self._creds)

    # ---------- Gönderim ----------

    def build_message(self, to, subject, body, cc=None, attachments=None, sender_name="", in_reply_to=None,
                      signature=None, extra_headers=None):
        msg = EmailMessage()
        if self.email:
            local, _, domain = self.email.partition("@")
            msg["From"] = Address(display_name=sender_name.strip(), username=local, domain=domain)
        msg["To"] = to
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg["Subject"] = subject
        for name, value in (extra_headers or {}).items():
            msg[name] = value
        if in_reply_to:
            # Alıcının mail programı da hatırlatmayı ilk mailin devamı olarak göstersin.
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = in_reply_to
        # Her zaman düz metin + HTML birlikte gönderilir. Sadece düz metin gönderilirse Gmail onu dar bir
        # sütunda (~75 karakterde) kırarak gösteriyor; HTML'de paragraflar ekran genişliğinde akar.
        # İmza görselleri (logo, ikonlar) HTML'in içine gömülür.
        msg.set_content(plain_body(body, signature))
        msg.add_alternative(html_body(body, signature), subtype="html")
        html_part = msg.get_payload()[1]
        for cid, path in signature_images(signature):
            maintype, subtype, data, name = _read_file(path, "İmza görseli")
            html_part.add_related(data, maintype=maintype, subtype=subtype, cid=f"<{cid}>",
                                  filename=name, disposition="inline")
        for attachment in attachments or []:
            maintype, subtype, data, name = _read_file(attachment, "Ek dosya")
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
        return msg

    def _execute(self, make_request):
        """API isteğini tek seferde bir tane olacak şekilde çalıştırır, hatayı Türkçeye çevirir."""
        if not self.connected:
            raise GmailError("Gmail hesabı bağlı değil. Önce üstteki 'Gmail ile bağlan' butonuna basın.", fatal=True)
        with self._lock:
            try:
                self._ensure_fresh()
                return make_request(self._service.users()).execute(num_retries=1)
            except Exception as exc:
                raise _translate_error(exc) from exc

    def send(self, to, subject, body, cc=None, attachments=None, sender_name="", thread_id=None, in_reply_to=None,
             signature=None):
        """Maili gönderir. {'id': ..., 'threadId': ...} döner."""
        if not self.connected:
            raise GmailError("Gmail hesabı bağlı değil. Önce üstteki 'Gmail ile bağlan' butonuna basın.", fatal=True)
        raw = self.build_message(to, subject, body, cc, attachments, sender_name, in_reply_to, signature).as_bytes()

        def make_request(users):
            if len(raw) <= RAW_SIZE_LIMIT:
                body_json = {"raw": base64.urlsafe_b64encode(raw).decode("ascii")}
                if thread_id:
                    body_json["threadId"] = thread_id
                return users.messages().send(userId="me", body=body_json)
            media = MediaIoBaseUpload(io.BytesIO(raw), mimetype="message/rfc822", resumable=True)
            return users.messages().send(userId="me", body={"threadId": thread_id} if thread_id else {},
                                         media_body=media)

        return self._execute(make_request)

    # ---------- Taslaklar (Google sunucusuyla planlı gönderim) ----------

    def create_draft(self, to, subject, body, cc=None, attachments=None, sender_name="", signature=None,
                     extra_headers=None, thread_id=None, in_reply_to=None):
        """Gmail'de taslak oluşturur (thread_id verilirse o konuşmanın içinde). {'draft_id', 'message_id',
        'thread_id'} döner."""
        raw = self.build_message(to, subject, body, cc, attachments, sender_name, in_reply_to, signature,
                                 extra_headers).as_bytes()

        def make_request(users):
            if len(raw) <= RAW_SIZE_LIMIT:
                message = {"raw": base64.urlsafe_b64encode(raw).decode("ascii")}
                if thread_id:
                    message["threadId"] = thread_id
                return users.drafts().create(userId="me", body={"message": message})
            media = MediaIoBaseUpload(io.BytesIO(raw), mimetype="message/rfc822", resumable=True)
            return users.drafts().create(userId="me", body={"message": {"threadId": thread_id}} if thread_id else {},
                                         media_body=media)

        draft = self._execute(make_request)
        message = draft.get("message", {})
        return {"draft_id": draft.get("id"), "message_id": message.get("id"), "thread_id": message.get("threadId")}

    def delete_draft(self, draft_id):
        """Taslağı siler. Zaten yoksa (gönderilmiş ya da elle silinmiş) False döner."""
        try:
            self._execute(lambda users: users.drafts().delete(userId="me", id=draft_id))
            return True
        except GmailError as exc:
            if exc.status == 404:
                return False
            raise

    # ---------- Cevap takibi ----------

    def get_thread_messages(self, thread_id):
        """Konuşmadaki mesajların sadece başlıklarını döner. Konuşma silinmişse None döner."""
        try:
            thread = self._execute(lambda users: users.threads().get(
                userId="me", id=thread_id, format="metadata", metadataHeaders=THREAD_HEADERS))
        except GmailError as exc:
            if exc.status == 404:
                return None
            raise
        messages = []
        for m in thread.get("messages", []):
            headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
            messages.append({
                "id": m.get("id"),
                "labels": m.get("labelIds", []),
                "internal_date": int(m.get("internalDate", 0)),
                "headers": headers,
            })
        return messages

    def get_rfc_message_id(self, message_id):
        """Gönderilen mailin Message-ID başlığı (hatırlatmayı aynı konuşmaya bağlamak için)."""
        result = self._execute(lambda users: users.messages().get(
            userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID"]))
        for header in result.get("payload", {}).get("headers", []):
            if header["name"].lower() == "message-id":
                return header["value"]
        return None

    def thread_link(self, thread_id):
        """Konuşmayı tarayıcıda, doğru Gmail hesabında açan link."""
        account = f"?authuser={quote(self.email)}" if self.email else ""
        return f"https://mail.google.com/mail/{account}#all/{thread_id}"


def _read_file(path, what):
    """(maintype, subtype, içerik, dosya adı). Okunamazsa tüm gönderimi durduran hata."""
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise GmailError(f"{what} okunamadı: {path.name}\nDosya taşınmış ya da silinmiş olabilir.", fatal=True) from exc
    ctype, _ = mimetypes.guess_type(path.name)
    maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
    return maintype, subtype, data, path.name


def _http_error_details(exc):
    try:
        error = json.loads(exc.content.decode("utf-8")).get("error", {})
        reasons = {e.get("reason", "") for e in error.get("errors", [])}
        return error.get("message", ""), reasons
    except (ValueError, AttributeError):
        return str(exc), set()


def _translate_error(exc):
    log.error("Gmail gönderim hatası: %r", exc, exc_info=exc)
    if isinstance(exc, HttpError):
        status = exc.resp.status
        message, reasons = _http_error_details(exc)
        if status == 404:
            return GmailError("Gmail'de bulunamadı (konuşma silinmiş olabilir).", status=404)
        if status == 400:
            return GmailError(f"Gmail bu maili kabul etmedi (adres hatalı olabilir). Detay: {message}")
        if status == 401:
            return GmailError(SESSION_EXPIRED, fatal=True)
        if "accessNotConfigured" in reasons or "SERVICE_DISABLED" in str(exc.content):
            link = re.search(r"https://console\.developers\.google\.com/apis/api/gmail\.googleapis\.com/\S*?project=\d+", message)
            return GmailError(
                "Google Cloud projenizde Gmail API etkin değil.\n\n"
                "Google Cloud → API'ler ve Hizmetler → Kitaplık → 'Gmail API' → Etkinleştir.\n"
                + (f"Doğrudan link:\n{link.group(0)}\n\n" if link else "\n")
                + "Etkinleştirdikten sonra 2-3 dakika bekleyip tekrar deneyin.",
                fatal=True,
            )
        if "insufficientPermissions" in reasons or "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in str(exc.content):
            return GmailError(
                "Uygulamaya gereken Gmail izinlerinden biri verilmemiş.\n\n"
                "'Hesabı değiştir' ile tekrar bağlanın ve Google izin ekranındaki TÜM kutuları "
                "(e-posta gönderme ve e-posta başlıklarını görüntüleme) işaretleyin.",
                fatal=True,
            )
        if status == 429 or reasons & QUOTA_REASONS or "limit" in message.lower():
            return GmailError(
                "Gmail gönderim limitine ulaşıldı. Gönderim durduruldu; kalan firmalar 'Bekliyor' olarak kaldı.\n"
                "Birkaç saat (en geç 24 saat) sonra 'Gönder'e tekrar basarak devam edebilirsiniz.",
                fatal=True,
            )
        if status == 403:
            return GmailError(
                "Gmail bu işleme izin vermedi. 'Hesabı değiştir' ile tekrar bağlanmayı deneyin.", fatal=True
            )
        if status >= 500:
            return GmailError("Gmail sunucularında geçici bir sorun var. Birkaç dakika sonra tekrar deneyin.", fatal=True)
        return GmailError(f"Gmail beklenmeyen bir hata döndürdü ({status}): {message}", fatal=True)
    if isinstance(exc, GmailError):
        return exc
    if isinstance(exc, RefreshError):
        return GmailError(SESSION_EXPIRED, fatal=True)
    if isinstance(exc, (TransportError, OSError, httplib2.HttpLib2Error)):
        return GmailError(NETWORK_ERROR, fatal=True)
    return GmailError("Mail gönderilirken beklenmeyen bir hata oluştu. Ayrıntılar uygulama.log dosyasında.", fatal=True)
