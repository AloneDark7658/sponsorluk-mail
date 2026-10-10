"""Gönderim sekmesi: ayarlar, gönderim saatleri, özet, test maili, toplu gönderim ve ilerleme."""
import logging
from datetime import datetime
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from config import DEFAULT_DAILY_LIMIT, DEFAULT_DELAY_SECONDS, MAX_DAILY_LIMIT
from collections import Counter

import quota
import server_plan
from database import ERROR, PENDING, SENT, SERVER, TIME_FORMAT
from mail_format import attachment_problems, load_signature, signature_problems
from schedule import DEFAULT_TIMES, describe, format_times, parse_times
from sender import USER_STOPPED, SendJob, SendWorker
from template_engine import render_mail
from ui.server_dialogs import ServerPlanDialog, ServerSetupDialog
from ui.signature_dialog import SignatureDialog

log = logging.getLogger(__name__)

GREEN = "#1e8e3e"
GREEN_HOVER = "#17712f"
ORANGE = "#e37400"
ORANGE_HOVER = "#b85e00"
RED = "#c5221f"
RED_HOVER = "#a31b17"
NO_TEMPLATE = "(şablon seçilmedi)"


class SendTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.db = app.db
        self.worker = None
        self._testing = False
        self._scheduled_run = False

        self.grid_columnconfigure((0, 1), weight=1, uniform="col")
        self.grid_rowconfigure(5, weight=1)
        title_font = ctk.CTkFont(size=15, weight="bold")

        # Özet kartı
        summary = ctk.CTkFrame(self)
        summary.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        ctk.CTkLabel(summary, text="Durum", font=title_font).pack(anchor="w", padx=14, pady=(10, 2))
        self.summary_label = ctk.CTkLabel(summary, text="", justify="left", anchor="w", font=ctk.CTkFont(size=14))
        self.summary_label.pack(fill="x", padx=14, pady=(0, 6))
        self.schedule_label = ctk.CTkLabel(summary, text="", justify="left", anchor="w",
                                           font=ctk.CTkFont(size=14, weight="bold"), wraplength=520)
        self.schedule_label.pack(fill="x", padx=14, pady=(0, 8))

        # Google sunucusu: bilgisayar kapalıyken de gönderim
        ctk.CTkFrame(summary, height=2, fg_color=("gray80", "gray30")).pack(fill="x", padx=14, pady=(2, 6))
        ctk.CTkLabel(summary, text="Google sunucusu (bilgisayar kapalıyken gönderim)", font=title_font).pack(
            anchor="w", padx=14)
        self.server_label = ctk.CTkLabel(summary, text="", justify="left", anchor="w", wraplength=520)
        self.server_label.pack(fill="x", padx=14, pady=(2, 6))
        server_bar = ctk.CTkFrame(summary, fg_color="transparent")
        server_bar.pack(fill="x", padx=14, pady=(0, 12))
        self.server_plan_button = ctk.CTkButton(server_bar, text="Google'da planla", width=150,
                                                command=self.open_server_plan, fg_color="#7b3fb5",
                                                hover_color="#5f2f8c")
        self.server_plan_button.pack(side="left")
        self.server_cancel_button = ctk.CTkButton(server_bar, text="Google planını iptal et", width=170,
                                                  command=self.cancel_server_plan, fg_color=ORANGE,
                                                  hover_color=ORANGE_HOVER)
        self.server_cancel_button.pack(side="left", padx=8)
        ctk.CTkButton(server_bar, text="Kurulum", width=90, command=lambda: ServerSetupDialog(self, self.app),
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="left")

        # Ayarlar kartı
        settings = ctk.CTkFrame(self)
        settings.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 8))
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings, text="Ayarlar", font=title_font).grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))
        self.delay_entry = self._setting_row(settings, 1, "Mailler arası bekleme (saniye)",
                                             self.db.get_setting("delay", DEFAULT_DELAY_SECONDS))
        # Günlük limit: kutunun yanında tavsiye edilen değer ve üst sınır
        ctk.CTkLabel(settings, text="Günlük alıcı limiti (CC dahil)").grid(row=2, column=0, sticky="w", padx=14, pady=3)
        limit_cell = ctk.CTkFrame(settings, fg_color="transparent")
        limit_cell.grid(row=2, column=1, sticky="ew", padx=(6, 14), pady=3)
        self.limit_entry = ctk.CTkEntry(limit_cell, width=90)
        self.limit_entry.pack(side="left")
        self.limit_entry.insert(0, str(self.db.get_setting("daily_limit", DEFAULT_DAILY_LIMIT)))
        self.limit_entry.bind("<FocusOut>", lambda e: self.save_settings(show_errors=False))
        self.limit_entry.bind("<KeyRelease>", lambda e: self.refresh_summary())
        ctk.CTkLabel(limit_cell, text=f"Tavsiye edilen: {DEFAULT_DAILY_LIMIT}  ·  en fazla {MAX_DAILY_LIMIT}",
                     text_color="gray40").pack(side="left", padx=10)
        self.batch_entry = self._setting_row(settings, 3, "Bir seferde en fazla firma",
                                             self.db.get_setting("batch_max", ""), placeholder="Boş = sınırsız")
        self.sender_entry = self._setting_row(settings, 4, "Gönderen adı (isteğe bağlı)",
                                              self.db.get_setting("sender_name", ""),
                                              placeholder="Örn: ABC Üniversitesi Yatırım Kulübü")
        self.times_entry = self._setting_row(settings, 5, "Gönderim saatleri (ilk mailler)",
                                             self.db.get_setting("send_times", DEFAULT_TIMES), placeholder="09:00, 13:30")

        options = ctk.CTkFrame(settings, fg_color="transparent")
        options.grid(row=6, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 2))
        self.schedule_check = ctk.CTkCheckBox(options, text="Belirtilen saatlerde gönder", command=self._on_schedule_option)
        if self.db.get_setting("schedule_enabled", "1") == "1":
            self.schedule_check.select()
        self.schedule_check.pack(side="left")
        self.weekend_check = ctk.CTkCheckBox(options, text="Hafta sonu gönderme", command=self._on_schedule_option)
        if self.db.get_setting("skip_weekends", "1") == "1":
            self.weekend_check.select()
        self.weekend_check.pack(side="left", padx=16)
        ctk.CTkButton(options, text="İmza ayarları", width=110, command=lambda: SignatureDialog(self, self.app),
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="left")

        ctk.CTkLabel(
            settings,
            text=f"Gmail'in sınırı günde ~{MAX_DAILY_LIMIT} alıcıdır; daha fazlası yazılamaz. {DEFAULT_DAILY_LIMIT} güvenli bir değerdir. Planlı gönderimde saat geldiğinde "
                 "uygulamanın açık olması gerekir (bilgisayar uykuya geçmez, ama dizüstünün kapağı kapatılırsa uyur).",
            text_color="gray40", wraplength=520, justify="left",
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 10))

        # Hangi mail gidecek: şablon seçimi ve özeti
        mail_bar = ctk.CTkFrame(self)
        mail_bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(mail_bar, text="Gönderilecek mail:", font=title_font).pack(side="left", padx=(14, 8), pady=10)
        self.mail_template_menu = ctk.CTkOptionMenu(mail_bar, values=[NO_TEMPLATE], width=230, dynamic_resizing=False,
                                                    command=self._on_mail_template)
        self.mail_template_menu.pack(side="left")
        ctk.CTkButton(mail_bar, text="Metni düzenle", width=110, command=self.app.show_mail_tab,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="right", padx=14)
        self.mail_info = ctk.CTkLabel(mail_bar, text="", anchor="w", justify="left", wraplength=700)
        self.mail_info.pack(side="left", fill="x", expand=True, padx=12)

        # Butonlar
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.test_button = ctk.CTkButton(
            actions, text="Kendime test maili gönder", height=44, width=230, command=self.send_test,
            fg_color="#5f6b7a", hover_color="#4a5462", font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.test_button.pack(side="left")
        self.stop_button = ctk.CTkButton(
            actions, text="Durdur", height=44, width=130, command=self.stop, state="disabled",
            fg_color="gray70", hover_color=RED_HOVER, font=ctk.CTkFont(size=14, weight="bold"),
        )
        self.stop_button.pack(side="right")
        self.send_button = ctk.CTkButton(
            actions, text="GÖNDERİMİ BAŞLAT", height=44, width=300, command=self._on_send_button,
            fg_color=GREEN, hover_color=GREEN_HOVER, font=ctk.CTkFont(size=15, weight="bold"),
        )
        self.send_button.pack(side="right", padx=10)

        # İlerleme
        self.progress = ctk.CTkProgressBar(self, height=18, progress_color=GREEN)
        self.progress.set(0)
        self.progress.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        self.progress_label = ctk.CTkLabel(self, text="Hazır.", anchor="w")
        self.progress_label.grid(row=4, column=0, columnspan=2, sticky="ew")

        # Günlük (log)
        self.log_box = ctk.CTkTextbox(self, wrap="word", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_box.grid(row=5, column=0, columnspan=2, sticky="nsew", pady=(6, 0))
        self.log_box.configure(state="disabled")

        counts = self.db.counts()
        if counts[PENDING] and counts[SENT]:
            self.log(f"Önceki gönderimden {counts[PENDING]} firma 'Bekliyor' durumunda. "
                     "Gönderim kaldığı yerden devam eder.")
        self.after(30_000, self._periodic_refresh)

    def _setting_row(self, parent, row, label, value, placeholder=None):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=14, pady=3)
        entry = ctk.CTkEntry(parent, placeholder_text=placeholder)
        entry.grid(row=row, column=1, sticky="ew", padx=(6, 14), pady=3)
        if str(value):
            entry.insert(0, str(value))
        entry.bind("<FocusOut>", lambda e: self.save_settings(show_errors=False))
        entry.bind("<KeyRelease>", lambda e: self.refresh_summary())
        return entry

    # ---------- Ayarlar ----------

    def _read_settings(self):
        """(bekleme, limit) döner; hatalıysa ValueError fırlatır."""
        try:
            delay = float(self.delay_entry.get().replace(",", ".").strip())
        except ValueError:
            raise ValueError("Bekleme süresi bir sayı olmalı (ör. 5).")
        try:
            limit = int(self.limit_entry.get().strip())
        except ValueError:
            raise ValueError("Günlük limit tam sayı olmalı (ör. 200).")
        if delay < 0:
            raise ValueError("Bekleme süresi negatif olamaz.")
        if limit < 1:
            raise ValueError("Günlük limit en az 1 olmalı.")
        if limit > MAX_DAILY_LIMIT:
            raise ValueError(f"Günlük limit en fazla {MAX_DAILY_LIMIT} olabilir (Gmail'in sınırı). "
                             f"Tavsiye edilen: {DEFAULT_DAILY_LIMIT}.")
        return delay, limit

    def _read_batch_max(self):
        text = self.batch_entry.get().strip()
        if not text:
            return 0
        try:
            value = int(text)
        except ValueError:
            raise ValueError("'Bir seferde en fazla firma' boş ya da tam sayı olmalı (ör. 50).")
        if value < 1:
            raise ValueError("'Bir seferde en fazla firma' en az 1 olmalı (sınırsız için boş bırakın).")
        return value

    def schedule_settings(self):
        """(saatlere bağlı mı, saatler, hafta sonu atlansın mı). Saatler hatalıysa ValueError."""
        return (self.schedule_check.get() == 1, parse_times(self.times_entry.get()), self.weekend_check.get() == 1)

    def save_settings(self, show_errors=True):
        try:
            delay, limit = self._read_settings()
            batch_max = self._read_batch_max()
            _, times, _ = self.schedule_settings()
        except ValueError as exc:
            if show_errors:
                messagebox.showerror("Ayar hatası", str(exc))
            return False
        self.db.set_setting("delay", f"{delay:g}")
        self.db.set_setting("daily_limit", limit)
        self.db.set_setting("batch_max", batch_max or "")
        self.db.set_setting("sender_name", self.sender_entry.get().strip())
        self.db.set_setting("send_times", format_times(times))
        self.app.refresh_schedule()
        return True

    def _on_schedule_option(self):
        self.db.set_setting("schedule_enabled", "1" if self.schedule_check.get() == 1 else "0")
        self.db.set_setting("skip_weekends", "1" if self.weekend_check.get() == 1 else "0")
        if self.schedule_check.get() != 1:
            self.app.set_scheduled("campaign", False)
        self.app.refresh_schedule()

    # ---------- Özet ----------

    def _periodic_refresh(self):
        self.refresh_summary()
        self.after(30_000, self._periodic_refresh)

    def refresh_mail_info(self):
        """Gönderilecek mailin şablonu ve özeti (Mail Metni sekmesindeki hâli)."""
        tt = self.app.template_tab
        names = self.db.template_names()
        self.mail_template_menu.configure(values=names + [NO_TEMPLATE] if names else [NO_TEMPLATE])
        name, modified = tt.template_state()
        self.mail_template_menu.set(name or NO_TEMPLATE)
        mail = tt.get_mail()
        cc, _ = tt.get_cc()
        parts = [f"Konu: {mail['subject'] or '(boş)'}", f"{len(mail['attachments'])} ek", f"{len(cc)} CC",
                 "imza var" if load_signature(self.db) else "imza yok"]
        warning = ""
        if not name:
            warning = "Kayıtsız metin: Mail Metni sekmesinde şu an ne yazılıysa o gider."
        elif modified:
            warning = f"'{name}' şablonunda kaydedilmemiş değişiklik var: düzenlenmiş hâli gider."
        self.mail_info.configure(text="   •   ".join(parts) + (f"\n⚠ {warning}" if warning else ""),
                                 text_color=ORANGE if warning else ("gray10", "gray90"))

    def _on_mail_template(self, value):
        if value != NO_TEMPLATE:
            self.app.template_tab._on_template_selected(value)  # metni bu şablonla doldurur (gerekirse onay sorar)
        self.refresh_mail_info()

    def refresh_summary(self):
        self.refresh_mail_info()
        counts = self.db.counts()
        try:
            _, limit = self._read_settings()
        except ValueError:
            limit = int(self.db.get_setting("daily_limit", DEFAULT_DAILY_LIMIT))
        used, reserved = quota.gmail_used(self.db)
        room = max(0, limit - used - reserved)
        today = datetime.now().date()
        cc_valid, _ = self.app.template_tab.get_cc()
        per_mail = 1 + len(cc_valid)
        can_send = min(counts[PENDING], room // per_mail)
        self.summary_label.configure(text=(
            f"Bekleyen firma:  {counts[PENDING]}      Google'da planlı:  {counts[SERVER]}\n"
            f"Gönderilmiş:  {counts[SENT]}      Hatalı:  {counts[ERROR]}\n"
            f"Gmail günlük limiti:  {used} gönderildi + {reserved} Google'da planlı = {used + reserved} / {limit}"
            f"  (kalan {room})\n"
            f"Google sunucusu bugün:  {quota.server_used_on(self.db, today)} / {quota.SERVER_DAILY_RECIPIENTS} alıcı "
            f"(ilk mail + hatırlatma)\n"
            f"Her mail 1 firma + {len(cc_valid)} CC = {per_mail} alıcı sayılır   •   Şu an gönderilebilecek: {can_send} firma"
        ))

    def refresh_schedule(self):
        """Planlı gönderim bilgisi ve buton metni."""
        try:
            enabled, times, _ = self.schedule_settings()
        except ValueError as exc:
            self.schedule_label.configure(text="⚠ " + str(exc), text_color=RED)
            self._update_buttons()
            return
        if self.app.is_scheduled("campaign"):
            self.schedule_label.configure(
                text=f"⏰ Gönderim planlandı. Zamanı: {self.app.upcoming_slot_text('campaign')}\n"
                     "Uygulamayı açık bırakın.", text_color=ORANGE)
        elif enabled:
            self.schedule_label.configure(text=f"Gönderim saatleri: {format_times(times)}", text_color="gray35")
        else:
            self.schedule_label.configure(text="Saat kısıtı kapalı: 'Başlat'a basınca hemen gönderilir.",
                                          text_color="gray35")
        self._update_buttons()

    # ---------- Google sunucusu ----------

    def refresh_server(self):
        planned = self.db.server_planned_contacts()
        lines = []
        if planned:
            groups = Counter(c["scheduled_for"] for c in planned)
            parts = []
            for when, n in sorted(groups.items()):
                try:
                    parts.append(f"{n} firma {describe(datetime.strptime(when, TIME_FORMAT))}")
                except (TypeError, ValueError):
                    parts.append(f"{n} firma")
            lines.append("☁ Google'da planlı: " + ", ".join(parts) + ". Bilgisayarı kapatabilirsiniz.")
        verified = self.db.get_setting("server_verified")
        if server_plan.script_needs_update(self.db):
            lines.append("⚠ Google'daki kod güncellenmeli (hatırlatmalar için): 'Kurulum' → 'Kodu kopyala' → "
                         "script.google.com'da eski kodun yerine yapıştırıp kaydedin.")
        elif verified:
            lines.append("Kurulum: çalışıyor ✓")
        elif self.db.get_setting("server_test_thread"):
            lines.append("Kurulum: test maili bekleniyor...")
        else:
            lines.append("Kurulum yapılmadı: önce 'Kurulum'a basın (bir kez).")
        lines.append("Google günde en fazla 100 alıcıya gönderir (CC dahil); kalanları uygulamadan gönderin.")
        self.server_label.configure(text="\n".join(lines))
        busy = self.app.busy or self._testing
        self.server_plan_button.configure(state="disabled" if busy else "normal")
        self.server_cancel_button.configure(state="normal" if planned and not busy else "disabled")

    def open_server_plan(self):
        if self.app.busy:
            return
        ready = self._check_ready()
        if not ready:
            return
        mail, cc, signature = ready
        if not self.db.pending_contacts():
            messagebox.showinfo("Gönderilecek firma yok", "Durumu 'Bekliyor' olan firma yok.")
            return
        ServerPlanDialog(self, self.app, cc, signature, kind="campaign", mail=mail)

    def cancel_server_plan(self):
        count = len(self.db.server_planned_contacts())
        if not count or not messagebox.askyesno(
            "Google planını iptal et",
            f"Google'da planlı {count} firmanın taslakları Gmail'den silinecek ve firmalar 'Bekliyor'a dönecek.\n"
            "Devam edilsin mi?",
        ):
            return
        self.app.set_busy(True)

        def done(result):
            cancelled, already_sent = result
            self.app.set_busy(False)
            self.app.contacts_changed()
            text = f"{cancelled} firmanın Google planı iptal edildi."
            if already_sent:
                text += f"\n{already_sent} firmaya bu arada zaten gönderilmişti; 'Gönderildi' olarak işaretlendi."
            self.log(text.replace("\n", " "))
            messagebox.showinfo("Google planı iptal edildi", text)

        def failed(message):
            self.app.set_busy(False)
            self.app.contacts_changed()
            messagebox.showerror("İptal tamamlanamadı", message)

        self.app.run_background(lambda: server_plan.cancel_plan(self.db, self.app.gmail), on_done=done, on_error=failed)

    # ---------- Günlük ----------

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _report(self, title, message, interactive, level="warning"):
        """Kullanıcı başındaysa pencereyle, planlı gönderimde (kimse yokken) günlüğe yazarak bildirir."""
        if interactive:
            {"warning": messagebox.showwarning, "error": messagebox.showerror,
             "info": messagebox.showinfo}[level](title, message)
        else:
            self.log(f"{title}: " + message.replace("\n", " "))

    # ---------- Ortak kontroller ----------

    def _check_ready(self, interactive=True):
        """Gönderim için gerekenler tamam mı? Değilse bildirir ve None döner."""
        if not self.app.gmail.connected:
            self._report("Gmail bağlı değil", "Önce sağ üstteki 'Gmail ile bağlan' butonuyla hesabınızı bağlayın.",
                         interactive)
            return None
        mail = self.app.template_tab.get_mail()
        if not mail["subject"] or not mail["body"]:
            self._report("Mail metni eksik", "'Mail Metni' sekmesinde konu ve metni doldurun.", interactive)
            return None
        signature = load_signature(self.db)
        problems = attachment_problems(mail["attachments"]) + signature_problems(signature)
        if problems:
            self._report("Ek / imza sorunu", "\n".join(problems), interactive, "error")
            return None
        cc_valid, cc_invalid = self.app.template_tab.get_cc()
        if cc_invalid:
            self._report("Geçersiz CC", "Şu CC adresleri geçersiz, düzeltin:\n" + "\n".join(cc_invalid),
                         interactive, "error")
            return None
        if not self.save_settings(show_errors=interactive):
            if not interactive:
                self.log("Ayarlarda hata var, gönderim başlatılamadı.")
            return None
        return mail, cc_valid, signature

    # ---------- Test maili ----------

    def send_test(self):
        ready = self._check_ready()
        if not ready:
            return
        mail, _, signature = ready
        contact = self.app.template_tab.current_preview_contact()
        me = self.app.gmail.email
        if contact:
            subject, body, missing = render_mail(mail["subject"], mail["body"], contact)
            sample = contact["firma"] or contact["email"]
        else:
            subject, body, missing = mail["subject"], mail["body"], []
            sample = None
        sender_name = self.sender_entry.get().strip()
        self._testing = True
        self._update_buttons()
        self.log(f"Test maili gönderiliyor → {me}" + (f"  (örnek firma: {sample})" if sample else ""))

        def work():
            self.app.gmail.send(me, "[TEST] " + subject, body, None, mail["attachments"], sender_name,
                                signature=signature)
            self.db.log_send(1, me, kind="test")

        def done(_):
            self._testing = False
            self._update_buttons()
            self.refresh_summary()
            self.log("Test maili gönderildi. Gelen kutunuzu kontrol edin.")
            note = ""
            if missing:
                note = "\n\nNot: Bu firmada doldurulamayan alanlar var: " + ", ".join("{{" + m + "}}" for m in missing)
            messagebox.showinfo(
                "Test maili gönderildi",
                f"Test maili {me} adresine gönderildi (saat kısıtı test mailine uygulanmaz)."
                + (f"\nÖrnek olarak '{sample}' firmasının bilgileri kullanıldı." if sample else "")
                + "\n(CC listesine test maili gönderilmez.)" + note,
            )

        def failed(message):
            self._testing = False
            self._update_buttons()
            self.log("Test maili gönderilemedi: " + message.replace("\n", " "))
            messagebox.showerror("Test maili gönderilemedi", message)

        self.app.run_background(work, on_done=done, on_error=failed)

    # ---------- Toplu gönderim ----------

    def is_sending(self):
        return self.worker is not None and self.worker.is_alive()

    def _on_send_button(self):
        if self.app.is_scheduled("campaign"):
            if messagebox.askyesno("Planı iptal et", "Planlı gönderim iptal edilsin mi?\n(Firmalar 'Bekliyor' kalır.)"):
                self.app.set_scheduled("campaign", False)
                self.log("Planlı gönderim iptal edildi.")
            return
        self.start()

    def start(self, scheduled=False):
        """Kullanıcı basınca: onay alır, saat kısıtı açıksa planlar, kapalıysa hemen gönderir.
        Zamanlayıcı çağırınca (scheduled=True): onay sormadan gönderir. Başladıysa/planlandıysa True döner."""
        if self.app.busy:
            return False
        interactive = not scheduled
        ready = self._check_ready(interactive)
        if not ready:
            return False
        mail, cc, signature = ready
        pending = self.db.pending_contacts()
        if not pending:
            if scheduled:
                self.app.set_scheduled("campaign", False)
            self._report("Gönderilecek firma yok", "Durumu 'Bekliyor' olan firma yok.", interactive, "info")
            return False

        delay, limit = self._read_settings()
        batch_max = self._read_batch_max()
        per_mail = 1 + len(cc)
        used, reserved = quota.gmail_used(self.db)
        can_send = max(0, limit - used - reserved) // per_mail
        if can_send == 0 and not (interactive and self.schedule_check.get() == 1):
            self._report("Günlük limit dolu",
                         f"Son 24 saatte {used} alıcıya gönderildi, {reserved} alıcı Google'da planlı; limit {limit}. "
                         f"Bir mail {per_mail} alıcı sayıldığı için şu an gönderim yapılamaz.", interactive)
            return False

        if interactive:
            this_round = min(len(pending), can_send, batch_max or len(pending))
            missing_count = sum(1 for c in pending if render_mail(mail["subject"], mail["body"], c)[2])
            planned = self.schedule_check.get() == 1
            lines = [f"{len(pending)} firmaya mail gönderilecek.", f"Şablon: {self.app.template_tab.template_label()}"]
            if planned:
                lines.append(f"\n⏰ Gönderim zamanı: {self.app.upcoming_slot_text('campaign')}. "
                             "Saat gelince otomatik başlar; o saatte uygulama açık olmalı.")
            if this_round < len(pending):
                lines.append(f"\nGünlük limit / 'bir seferde en fazla' ayarı nedeniyle her seferde en fazla "
                             f"{this_round} firma; kalanlar sonraki gönderim saatlerinde devam eder.")
            if missing_count:
                lines.append(f"\n⚠ {missing_count} firmada doldurulamayan alan var; bunlara gönderilmez, "
                             "'Hata' olarak işaretlenir.")
            lines.append(f"\nKonu: {mail['subject']}")
            lines.append("CC: " + (", ".join(cc) if cc else "(yok)"))
            lines.append("Ekler: " + (", ".join(Path(a).name for a in mail["attachments"]) or "(yok)"))
            lines.append("İmza: " + ("var" if signature else "yok"))
            lines.append(f"Mailler arası bekleme: {delay:g} sn")
            lines.append("\nOnaylıyor musunuz?")
            if not messagebox.askyesno("Gönderimi onayla", "\n".join(lines), icon="warning"):
                return False
            if planned:
                self.app.set_scheduled("campaign", True)
                self.log(f"Gönderim planlandı: {self.app.upcoming_slot_text('campaign')}.")
                return True

        job = SendJob(
            subject=mail["subject"], body=mail["body"], cc=cc, attachments=mail["attachments"], signature=signature,
            sender_name=self.sender_entry.get().strip(), delay=delay, daily_limit=limit, max_count=batch_max,
            template_name=self.app.template_tab.template_label(),
        )
        self.worker = SendWorker(self.db, self.app.gmail, job, notify=lambda ev: self.app.call_in_ui(self._on_event, ev))
        self._scheduled_run = scheduled
        self.app.set_busy(True)
        self.log(("Planlı gönderim başladı: " if scheduled else "Gönderim başladı: ") + f"{len(pending)} firma bekliyor.")
        self.worker.start()
        return True

    def stop(self):
        if self.is_sending():
            self.worker.stop()
            self.stop_button.configure(state="disabled", text="Durduruluyor...")
            self.log("Durdurma istendi; o an gönderilen mail tamamlanınca duracak.")

    def stop_and_wait(self):
        if self.is_sending():
            self.worker.stop()
            self.worker.join(timeout=20)

    def _update_buttons(self):
        sending = self.is_sending()
        busy = self.app.busy or self._testing
        if self.app.is_scheduled("campaign") and not sending:
            self.send_button.configure(state="normal", text="Planı iptal et", fg_color=ORANGE, hover_color=ORANGE_HOVER)
        else:
            text = "GÖNDERİMİ PLANLA" if self.schedule_check.get() == 1 else "GÖNDERİMİ BAŞLAT"
            self.send_button.configure(state="disabled" if busy else "normal", text=text,
                                       fg_color=GREEN, hover_color=GREEN_HOVER)
        self.test_button.configure(state="disabled" if busy else "normal")
        self.refresh_server()
        self.stop_button.configure(state="normal" if sending else "disabled", text="Durdur",
                                   fg_color=RED if sending else "gray70")

    def _on_event(self, ev):
        kind = ev["type"]
        if kind == "start":
            self.progress.set(0)
            self.progress_label.configure(text=f"0 / {ev['total']}")
        elif kind == "sending":
            c = ev["contact"]
            self.progress_label.configure(text=f"Gönderiliyor ({ev['index']} / {ev['total']}):  {c['firma']}  <{c['email']}>")
        elif kind in ("result", "skipped"):
            self.progress.set(ev["index"] / max(1, ev["total"]))
            if kind == "result":
                c = ev["contact"]
                self.app.contacts_tab.update_contact_row(c["id"])
                if ev["ok"]:
                    self.log(f"✓ {c['firma']} <{c['email']}>")
                else:
                    self.log(f"✗ {c['firma']} <{c['email']}>: {ev['message']}")
                self.progress_label.configure(text=f"{ev['index']} / {ev['total']} işlendi")
                self.refresh_summary()
        elif kind == "finished":
            scheduled_run, self._scheduled_run = self._scheduled_run, False
            self.worker = None
            remaining = self.db.counts()[PENDING]
            if self.app.is_scheduled("campaign"):
                if remaining == 0 or ev["stop_reason"] == USER_STOPPED:
                    self.app.set_scheduled("campaign", False)
                else:
                    self.log(f"Kalan {remaining} firma sonraki gönderim saatinde "
                             f"({self.app.upcoming_slot_text('campaign')}) devam edecek.")
            self.app.set_busy(False)
            self.app.contacts_changed()
            summary = f"Gönderilen: {ev['sent']}    Hatalı: {ev['failed']}"
            if ev["stop_reason"]:
                self.log("Gönderim durdu: " + ev["stop_reason"].replace("\n", " "))
                self.progress_label.configure(text=f"Durdu. {summary}    Bekleyen: {remaining}")
                if not scheduled_run:
                    messagebox.showwarning("Gönderim durdu", f"{ev['stop_reason']}\n\n{summary}\nBekleyen: {remaining}")
            else:
                self.progress.set(1)
                self.log(f"Gönderim tamamlandı. {summary}")
                self.progress_label.configure(text=f"Tamamlandı. {summary}")
                if not scheduled_run:
                    extra = "\n\nHatalı olanları 'Firma Listesi' sekmesinde görebilirsiniz." if ev["failed"] else ""
                    messagebox.showinfo("Gönderim tamamlandı", summary + extra)
