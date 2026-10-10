"""Ana pencere: üst bar (Gmail hesabı) ve sekmeler."""
import logging
import queue
import threading
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

from config import APP_NAME, APP_VERSION, ASSET_DIR
from gmail_client import GmailError
import server_plan
import updater
from database import SERVER
from replies import check_replies
from schedule import BUSY_WINDOW, START_WINDOW, describe, keep_awake, latest_slot, next_slot, slot_key
from ui.contacts_tab import ContactsTab
from ui.followup_tab import FollowupTab
from ui.send_tab import SendTab
from ui.template_tab import TemplateTab
from ui.update_dialog import UpdateDialog

log = logging.getLogger(__name__)

TAB_LIST = "1) Firma Listesi"
TAB_TEXT = "2) Mail Metni ve Önizleme"
TAB_SEND = "3) Gönderim"
TAB_FOLLOW = "4) Cevaplar ve Hatırlatma"
REPLY_CHECK_INTERVAL_MS = 15 * 60 * 1000
SCHEDULE_TICK_MS = 20 * 1000
UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
SCHEDULE_KINDS = ("campaign", "reminder")  # aynı saatte önce ilk mailler, sonra hatırlatmalar gider

HEADER_BG = "#1a3c6e"
UNEXPECTED = "Beklenmeyen bir hata oluştu. Ayrıntılar uygulama.log dosyasında."


class App(ctk.CTk):
    def __init__(self, db, gmail):
        super().__init__()
        self.db = db
        self.gmail = gmail
        self.busy = False
        self._checking = False
        self._new_replies = 0
        self._update_info = None
        self._ui_queue = queue.Queue()

        self.title(f"{APP_NAME}  v{APP_VERSION}")
        try:
            self.iconbitmap(str(ASSET_DIR / "simge.ico"))
        except Exception:
            pass
        self.geometry("1280x820")
        self.minsize(1080, 700)
        self.report_callback_exception = self._on_tk_error

        self._build_header()

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        for name in (TAB_LIST, TAB_TEXT, TAB_SEND, TAB_FOLLOW):
            self.tabs.add(name)
        try:
            self.tabs._segmented_button.configure(font=ctk.CTkFont(size=14, weight="bold"), height=36)
        except Exception:
            pass

        self.contacts_tab = ContactsTab(self.tabs.tab(TAB_LIST), self)
        self.contacts_tab.pack(fill="both", expand=True)
        self.template_tab = TemplateTab(self.tabs.tab(TAB_TEXT), self)
        self.template_tab.pack(fill="both", expand=True)
        self.send_tab = SendTab(self.tabs.tab(TAB_SEND), self)
        self.send_tab.pack(fill="both", expand=True)
        self.followup_tab = FollowupTab(self.tabs.tab(TAB_FOLLOW), self)
        self.followup_tab.pack(fill="both", expand=True)

        self.contacts_changed()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._process_ui_queue)
        self.after(300, self._auto_login)
        self.after(REPLY_CHECK_INTERVAL_MS, self._periodic_reply_check)
        self.refresh_schedule()
        self.after(5000, self._schedule_tick)
        self.after(3000, lambda: self.check_for_update(silent=True))
        self.after(15000, updater.cleanup_backup)  # yeni sürüm sorunsuz açıldı -> eski sürüm yedeğini sil

    # ---------- Üst bar ----------

    def _build_header(self):
        header = ctk.CTkFrame(self, corner_radius=0, fg_color=HEADER_BG, height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        ctk.CTkLabel(
            header, text=APP_NAME, text_color="white", font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left", padx=18)
        # Yeni cevap / hatırlatma bildirimi; tıklayınca ilgili sekmeye gider.
        self.notice_label = ctk.CTkLabel(header, text="", text_color="#ffd666", cursor="hand2",
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.notice_label.pack(side="left", padx=10)
        self.notice_label.bind("<Button-1>", lambda e: self._open_notice())
        # Sürüm: tıklayınca güncelleme kontrol edilir; yeni sürüm varsa yanında 'Güncelle' butonu çıkar.
        self.version_label = ctk.CTkLabel(header, text=f"v{APP_VERSION}", text_color="#9fb4d3", cursor="hand2",
                                          font=ctk.CTkFont(size=12))
        self.version_label.pack(side="left", padx=(0, 6))
        self.version_label.bind("<Button-1>", lambda e: self.check_for_update(silent=False))
        self.update_button = ctk.CTkButton(header, text="", height=30, command=self.open_update,
                                           fg_color="#e37400", hover_color="#b85e00",
                                           font=ctk.CTkFont(size=13, weight="bold"))
        self.connect_button = ctk.CTkButton(
            header, text="Gmail ile bağlan", width=170, height=36, command=self.connect_clicked,
            fg_color="white", text_color=HEADER_BG, hover_color="#dde6f2",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.connect_button.pack(side="right", padx=18)
        self.account_label = ctk.CTkLabel(header, text="", text_color="white", font=ctk.CTkFont(size=14))
        self.account_label.pack(side="right", padx=6)
        self.update_account_state()

    # ---------- Güncelleme ----------

    def check_for_update(self, silent=True):
        def done(info):
            if info:
                self._update_info = info
                self.update_button.configure(text=f"⬆ v{info['version']} hazır — Güncelle")
                self.update_button.pack(side="left", padx=6, after=self.version_label)
                if not silent:
                    self.open_update()
            elif not silent:
                messagebox.showinfo("Güncelleme", f"En güncel sürümü kullanıyorsunuz (v{APP_VERSION}).")
            if silent:
                self.after(UPDATE_CHECK_INTERVAL_MS, lambda: self.check_for_update(silent=True))

        def failed(message):
            log.info("Güncelleme kontrolü yapılamadı: %s", message)
            if not silent:
                messagebox.showwarning("Güncelleme", message)

        def work():
            try:
                return updater.check_latest()
            except updater.UpdateError as exc:
                raise GmailError(str(exc))  # run_background'ın kullanıcı mesajı yolu

        self.run_background(work, on_done=done, on_error=failed)

    def open_update(self):
        if self._update_info:
            UpdateDialog(self, self, self._update_info)

    def close_for_update(self):
        """Güncelleme yardımcısı başladı: verileri kaydedip kapan (yardımcı yeni sürümü açacak)."""
        try:
            self.template_tab.save_draft()
            self.send_tab.save_settings(show_errors=False)
            self.followup_tab.save_settings()
            keep_awake(False)
            self.db.close()
        except Exception:
            log.exception("Güncelleme öncesi kayıt sorunu")
        log.info("Güncelleme için kapatılıyor")
        self.destroy()

    def update_account_state(self, status_text=None):
        if self.gmail.connected:
            self.account_label.configure(text=f"●  Bağlı hesap: {self.gmail.email}", text_color="#9be7a8")
            self.connect_button.configure(text="Hesabı değiştir")
        else:
            self.account_label.configure(text=status_text or "●  Gmail hesabı bağlı değil", text_color="#ffb4a8")
            self.connect_button.configure(text="Gmail ile bağlan")
        self.connect_button.configure(state="disabled" if self.busy else "normal")

    def _auto_login(self):
        if not self.gmail.token_file.exists():
            return
        self.account_label.configure(text="Bağlanıyor...", text_color="white")
        def done(ok):
            if ok:
                self.update_account_state()
                self.check_replies(silent=True)  # kapalıyken gelen cevapları yakala
            elif self.gmail.needs_reconsent:
                self.update_account_state("●  Yeni özellikler için 'Gmail ile bağlan'a basıp izin verin")
            else:
                self.update_account_state("●  Oturum süresi dolmuş, tekrar bağlanın")

        self.run_background(
            self.gmail.load_saved_login,
            on_done=done,
            on_error=lambda msg: self.update_account_state("●  Bağlanılamadı (internet?)"),
        )

    def connect_clicked(self):
        if self.gmail.connected:
            if not messagebox.askyesno(
                "Hesabı değiştir",
                f"Şu an {self.gmail.email} bağlı.\nBağlantı kapatılıp yeniden giriş yapılacak. Devam edilsin mi?",
            ):
                return
            self.gmail.disconnect()
            self.update_account_state()
        if not self.gmail.has_credentials_file():
            messagebox.showerror(
                "credentials.json bulunamadı",
                "Gmail'e bağlanmak için Google Cloud'dan indirdiğiniz 'credentials.json' dosyası gerekli.\n\n"
                f"Dosyayı şu klasöre koyun:\n{self.gmail.credentials_file.parent}\n\n"
                "Nasıl alınacağı README.md dosyasında adım adım anlatılıyor.",
            )
            return
        self.connect_button.configure(state="disabled", text="Tarayıcıda onay bekleniyor...")
        self.account_label.configure(text="Açılan tarayıcı sekmesinde Google hesabınızla giriş yapın", text_color="white")

        def done(_):
            self.update_account_state()
            self.send_tab.log(f"Gmail hesabı bağlandı: {self.gmail.email}")
            self.check_replies(silent=True)

        def failed(message):
            self.update_account_state()
            messagebox.showerror("Bağlantı kurulamadı", message)

        self.run_background(self.gmail.connect, on_done=done, on_error=failed)

    # ---------- Sekmeler arası iletişim ----------

    def contacts_changed(self):
        self.contacts_tab.refresh()
        self.template_tab.refresh_contacts()
        self.send_tab.refresh_summary()
        self.followup_tab.refresh()
        self.send_tab.refresh_server()
        self.update_notice()

    # ---------- Cevap takibi ----------

    def check_replies(self, silent=True):
        """Gmail'deki konuşmalara bakıp gelen cevapları işler (arka planda)."""
        if self._checking or self.busy or not self.gmail.connected:
            if not silent and not self.gmail.connected:
                messagebox.showwarning("Gmail bağlı değil", "Önce sağ üstteki 'Gmail ile bağlan' butonuyla bağlanın.")
            return
        self._checking = True
        self.followup_tab.set_checking(True)
        cc, _ = self.template_tab.get_cc()

        def work():
            # Önce Google sunucusunun gönderdiklerini işle, sonra cevaplara bak.
            synced = server_plan.sync(self.db, self.gmail)
            result = check_replies(self.db, self.gmail, cc)
            result["server"] = synced
            return result

        def done(result):
            self._checking = False
            self.followup_tab.set_checking(False)
            self._new_replies += len(result["new_replies"])
            self.contacts_changed()
            synced = result["server"]
            if synced["sent"]:
                self.send_tab.log(f"Google sunucusu gönderdi: {len(synced['sent'])} firma ("
                                  + ", ".join(synced["sent"][:10]) + ("..." if len(synced["sent"]) > 10 else "") + ").")
            if synced.get("reminders_sent"):
                self.followup_tab.log(f"Google sunucusu hatırlatma gönderdi: {len(synced['reminders_sent'])} firma ("
                                      + ", ".join(synced["reminders_sent"][:10]) + ").")
            if synced.get("reminders_dropped"):
                self.followup_tab.log("Cevap geldiği için hatırlatması gönderilmeyen: "
                                      + ", ".join(synced["reminders_dropped"][:10]) + ".")
            if synced["missing"]:
                self.send_tab.log("Google taslağı bulunamayan firmalar 'Hata' yapıldı: " + ", ".join(synced["missing"]))
            if synced["test_ok"]:
                self.send_tab.log("Google sunucusu testi başarılı ✓ Kurulum tamam.")
                messagebox.showinfo("Google sunucusu çalışıyor",
                                    "Test maili Google sunucusundan gönderildi. Kurulum tamam!\n"
                                    "Artık 'Google'da planla' ile bilgisayar kapalıyken de gönderebilirsiniz.")
            parts = [f"{result['checked']} konuşma kontrol edildi"]
            if result["new_replies"]:
                parts.append("yeni cevap: " + ", ".join(result["new_replies"]))
            if result["new_bounces"]:
                parts.append("ulaşmadı: " + ", ".join(result["new_bounces"]))
            self.followup_tab.log("Cevap kontrolü: " + "; ".join(parts) + ".")
            if not silent:
                messagebox.showinfo("Cevap kontrolü", "\n".join(p[0].upper() + p[1:] for p in parts) + ".")

        def failed(message):
            self._checking = False
            self.followup_tab.set_checking(False)
            self.followup_tab.log("Cevap kontrolü yapılamadı: " + message.replace("\n", " "))
            if not silent:
                messagebox.showerror("Cevap kontrolü yapılamadı", message)

        self.run_background(work, on_done=done, on_error=failed)

    def _periodic_reply_check(self):
        if self.followup_tab.auto_check_enabled():
            self.check_replies(silent=True)
        self.after(REPLY_CHECK_INTERVAL_MS, self._periodic_reply_check)

    def update_notice(self):
        parts = []
        if self._new_replies:
            parts.append(f"✉ {self._new_replies} yeni cevap")
        planned = [k for k in SCHEDULE_KINDS if self.is_scheduled(k) and self._schedule_config(k)]
        if planned:
            first = min(planned, key=lambda k: self.upcoming_slot(k) or datetime.max)
            what = "hatırlatma" if first == "reminder" else "gönderim"
            parts.append(f"⏰ Planlı {what}: {self.upcoming_slot_text(first)}")
        on_server = self.db.counts()[SERVER]
        if on_server:
            parts.append(f"☁ Google'da planlı: {on_server} firma")
        due = len(self.followup_tab.due_contacts())
        if due and not self.is_scheduled("reminder"):
            parts.append(f"● {due} firmaya hatırlatma zamanı geldi")
        self.notice_label.configure(text="   ".join(parts))

    # ---------- Gönderim saatleri (planlı gönderim) ----------

    def is_scheduled(self, kind):
        return self.db.get_setting(f"scheduled_{kind}") == "1"

    def set_scheduled(self, kind, value):
        self.db.set_setting(f"scheduled_{kind}", "1" if value else "0")
        self.refresh_schedule()

    def _schedule_config(self, kind="campaign"):
        """Saat kısıtı açıksa (saatler, hafta sonu atlansın mı); kapalı ya da hatalıysa None.
        İlk mailler 'Gönderim saatleri'ni, hatırlatmalar kendi 'Hatırlatma saatleri'ni kullanır."""
        try:
            enabled, times, skip_weekends = self.send_tab.schedule_settings()
            if kind == "reminder":
                times = self.followup_tab.reminder_times()
        except ValueError:
            return None
        return (times, skip_weekends) if enabled else None

    def upcoming_slot(self, kind):
        config = self._schedule_config(kind)
        if not config:
            return None
        now = datetime.now()
        slot = latest_slot(now, *config)
        if slot and now - slot <= START_WINDOW and self.db.get_setting(f"last_slot_{kind}") != slot_key(slot):
            return slot  # saat yeni geçti, henüz bu saatte gönderilmedi -> hemen başlar
        return next_slot(now, *config)

    def upcoming_slot_text(self, kind):
        slot = self.upcoming_slot(kind)
        if slot is None:
            return "-"
        if slot <= datetime.now():
            return f"hemen ({slot:%H:%M} gönderim saati)"
        return describe(slot)

    def refresh_schedule(self):
        planned = any(self.is_scheduled(k) and self._schedule_config(k) for k in SCHEDULE_KINDS)
        keep_awake(planned or self.busy)
        self.send_tab.refresh_schedule()
        self.followup_tab.refresh_schedule()
        self.update_notice()

    def _schedule_tick(self):
        try:
            self._run_due_schedule()
        except Exception:
            log.exception("Planlı gönderim başlatılamadı")
        self.refresh_schedule()
        self.after(SCHEDULE_TICK_MS, self._schedule_tick)

    def _run_due_schedule(self):
        now = datetime.now()
        due = []
        for kind in SCHEDULE_KINDS:  # ilk mailler ve hatırlatmalar ayrı saatlerde olabilir
            config = self._schedule_config(kind)
            if not config or not self.is_scheduled(kind):
                continue
            slot = latest_slot(now, *config)
            if not slot:
                continue
            key = slot_key(slot)
            if self.db.get_setting(f"last_slot_{kind}") == key:
                continue
            if now - slot <= START_WINDOW:
                # Saat geldi. Başka gönderim sürüyorsa sıraya alınır, o bitince başlar.
                self.db.set_setting(f"waiting_slot_{kind}", key)
            if self.db.get_setting(f"waiting_slot_{kind}") == key and now - slot <= BUSY_WINDOW:
                due.append((kind, key))
        if self.busy:
            return
        for kind, key in due:
            self.db.set_setting(f"last_slot_{kind}", key)
            log.info("Planlı gönderim saati geldi: %s (%s)", key, kind)
            tab = self.send_tab if kind == "campaign" else self.followup_tab
            if tab.start(scheduled=True):
                return  # aynı anda tek iş; diğeri bu iş bitince sıradaki kontrolde başlar

    def _open_notice(self):
        if self._new_replies:
            self._new_replies = 0
            self.contacts_tab.show_filter("Cevap geldi")
            self.tabs.set(TAB_LIST)
        else:
            self.tabs.set(TAB_FOLLOW)
        self.update_notice()

    def select_contact(self, contact_id):
        self.template_tab.show_contact(contact_id)

    def show_mail_tab(self):
        self.tabs.set(TAB_TEXT)

    def show_preview(self, contact_id):
        self.template_tab.show_contact(contact_id)
        self.tabs.set(TAB_TEXT)

    def set_busy(self, busy):
        self.busy = busy
        self.contacts_tab.set_busy(busy)
        self.send_tab._update_buttons()
        self.followup_tab._update_buttons()
        self.update_account_state()

    # ---------- Thread yardımcıları ----------

    def call_in_ui(self, func, *args):
        """Arka plan thread'lerinden arayüzü güncellemenin güvenli yolu."""
        self._ui_queue.put((func, args))

    def _process_ui_queue(self):
        try:
            while True:
                func, args = self._ui_queue.get_nowait()
                try:
                    func(*args)
                except Exception:
                    log.exception("Arayüz güncellemesi başarısız")
        except queue.Empty:
            pass
        self.after(100, self._process_ui_queue)

    def run_background(self, work, on_done=None, on_error=None):
        def target():
            try:
                result = work()
            except GmailError as exc:
                if on_error:
                    self.call_in_ui(on_error, exc.message)
            except Exception:
                log.exception("Arka plan işi başarısız")
                if on_error:
                    self.call_in_ui(on_error, UNEXPECTED)
            else:
                if on_done:
                    self.call_in_ui(on_done, result)

        threading.Thread(target=target, daemon=True).start()

    # ---------- Hata ve kapanış ----------

    def _on_tk_error(self, exc_type, exc_value, exc_tb):
        log.error("Arayüz hatası", exc_info=(exc_type, exc_value, exc_tb))
        messagebox.showerror("Hata", UNEXPECTED)

    def _on_close(self):
        if self.send_tab.is_sending() or self.followup_tab.is_sending():
            if not messagebox.askyesno(
                "Gönderim sürüyor",
                "Gönderim devam ediyor. Durdurup çıkmak istiyor musunuz?\n"
                "Gönderilmeyenler bekler, sonra kaldığınız yerden devam edebilirsiniz.",
            ):
                return
            self.send_tab.stop_and_wait()
            self.followup_tab.stop_and_wait()
        try:
            self.template_tab.save_draft()
            self.send_tab.save_settings(show_errors=False)
            self.followup_tab.save_settings()
        except Exception:
            log.exception("Kapanışta ayarlar kaydedilemedi")
        log.info("Uygulama kapatıldı")
        self.destroy()
