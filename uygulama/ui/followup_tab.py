"""Cevaplar ve Hatırlatma sekmesi: cevap takibi özeti ve cevap vermeyenlere hatırlatma gönderimi."""
import json
import logging
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

import quota
import server_plan
from database import TIME_FORMAT, display_time
from schedule import DEFAULT_REMINDER_TIMES, describe, format_times, parse_times
from mail_format import load_signature, preview_body, signature_problems
from replies import due_for_reminder, reply_counts
from sender import ReminderJob, ReminderWorker, reply_subject
from template_engine import contact_fields, render
from ui.server_dialogs import ServerPlanDialog
from ui.variables import attach_variable_menu

log = logging.getLogger(__name__)

GREEN = "#1e8e3e"
GREEN_HOVER = "#17712f"
ORANGE = "#e37400"
ORANGE_HOVER = "#b85e00"
RED = "#c5221f"
RED_HOVER = "#a31b17"
DEFAULT_DAYS = 7
DEFAULT_MAX = 1
DEFAULT_REMINDER = (
    "Sayın {{Yetkili}},\n\n"
    "Birkaç gün önce {{Firma}} ile olası bir sponsorluk iş birliği hakkında size bir e-posta göndermiştik. "
    "Yoğunluğunuz arasında gözden kaçmış olabileceğini düşünerek kısaca hatırlatmak istedik.\n\n"
    "Değerlendirme fırsatınız olursa dönüşünüzü memnuniyetle bekleriz.\n\n"
    "Saygılarımızla"
)


class FollowupTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.db = app.db
        self.worker = None
        self._save_job = None
        self._scheduled_run = False
        # Hatırlatma listesinde işareti kaldırılan firmalar (kalıcı); yeni zamanı gelenler seçili gelir.
        try:
            self._excluded = set(json.loads(self.db.get_setting("reminder_excluded") or "[]"))
        except ValueError:
            self._excluded = set()
        self._preview_id = None
        self._due_signature = None

        self.grid_columnconfigure((0, 1), weight=1, uniform="col")
        self.grid_rowconfigure(1, weight=1)
        title_font = ctk.CTkFont(size=15, weight="bold")

        # --- Cevap takibi kartı ---
        track = ctk.CTkFrame(self)
        track.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 8))
        ctk.CTkLabel(track, text="Cevap takibi", font=title_font).pack(anchor="w", padx=14, pady=(10, 2))
        self.stats_label = ctk.CTkLabel(track, text="", justify="left", anchor="w", font=ctk.CTkFont(size=14))
        self.stats_label.pack(fill="x", padx=14)
        row = ctk.CTkFrame(track, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=(8, 2))
        self.check_button = ctk.CTkButton(row, text="Cevapları şimdi kontrol et", width=200,
                                          command=lambda: self.app.check_replies(silent=False))
        self.check_button.pack(side="left")
        self.last_check_label = ctk.CTkLabel(row, text="", text_color="gray35")
        self.last_check_label.pack(side="left", padx=10)
        self.auto_check = ctk.CTkCheckBox(track, text="Uygulama açıkken 15 dakikada bir otomatik kontrol et",
                                          command=self._save_auto_check)
        if self.db.get_setting("auto_reply_check", "1") == "1":
            self.auto_check.select()
        self.auto_check.pack(anchor="w", padx=14, pady=(6, 2))
        ctk.CTkLabel(
            track, text="Bilgisayar kapalıyken gelen cevaplar kaybolmaz: uygulama her açıldığında otomatik "
                        "kontrol edilir. Firmalar listesinde 'Gmail'de aç ↗' ile konuşmayı görebilirsiniz.",
            text_color="gray40", wraplength=520, justify="left",
        ).pack(anchor="w", padx=14, pady=(2, 12))

        # --- Hatırlatma ayarları kartı ---
        settings = ctk.CTkFrame(self)
        settings.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 8))
        settings.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(settings, text="Hatırlatma ayarları", font=title_font).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(10, 4))
        self.days_entry = self._setting_row(settings, 1, "İlk mailden kaç gün sonra",
                                            self.db.get_setting("reminder_days", DEFAULT_DAYS))
        self.max_entry = self._setting_row(settings, 2, "Firma başına en fazla hatırlatma",
                                           self.db.get_setting("reminder_max", DEFAULT_MAX))
        self.times_entry = self._setting_row(settings, 3, "Hatırlatma saatleri",
                                             self.db.get_setting("reminder_times", DEFAULT_REMINDER_TIMES), width=140)
        options = ctk.CTkFrame(settings, fg_color="transparent")
        options.grid(row=4, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 2))
        self.schedule_check = ctk.CTkCheckBox(options, text="Belirtilen saatlerde gönder",
                                              command=self._on_schedule_option)
        if self.db.get_setting("reminder_schedule_enabled", "1") == "1":
            self.schedule_check.select()
        self.schedule_check.pack(side="left")
        self.weekend_check = ctk.CTkCheckBox(options, text="Hafta sonu gönderme", command=self._on_schedule_option)
        if self.db.get_setting("reminder_skip_weekends", "1") == "1":
            self.weekend_check.select()
        self.weekend_check.pack(side="left", padx=16)
        ctk.CTkLabel(
            settings,
            text="Hatırlatma, ilk mailin cevabı olarak aynı konuşmada ('Re: ...' konusuyla) gider ve sabit CC "
                 "listesi eklenir. Saat ve hafta sonu ayarları ilk maillerinkinden ayrıdır. "
                 "Bekleme süresi ve günlük limit 'Gönderim' sekmesindeki ayarlardır. "
                 "Göndermeden hemen önce her firmanın cevabı tekrar kontrol edilir.",
            text_color="gray40", wraplength=520, justify="left",
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=14, pady=(4, 12))

        # --- Hatırlatma metni ve önizleme ---
        editor = ctk.CTkFrame(self)
        editor.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(editor, text="Hatırlatma metni  (sağ tık → Değişken ekle)",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=12, pady=(10, 4))
        self.body_text = ctk.CTkTextbox(editor, wrap="word", font=ctk.CTkFont(size=14), undo=True)
        self.body_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.body_text.insert("1.0", self.db.get_setting("reminder_body") or DEFAULT_REMINDER)
        self.body_text.bind("<KeyRelease>", lambda e: self._schedule_save())
        attach_variable_menu(self.body_text, self.app.template_tab.variables, self._schedule_save)

        side = ctk.CTkFrame(self, fg_color="transparent")
        side.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        # Hatırlatma zamanı gelen firmalar: son mailden geçen güne göre gruplu, seçilebilir
        due_box = ctk.CTkFrame(side)
        due_box.pack(fill="both", expand=True, pady=(0, 6))
        head = ctk.CTkFrame(due_box, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 2))
        ctk.CTkLabel(head, text="Hatırlatma zamanı gelen firmalar", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(head, text="Hiçbiri", width=64, height=24, command=lambda: self._select_all(False),
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="right")
        ctk.CTkButton(head, text="Tümü", width=64, height=24, command=lambda: self._select_all(True)).pack(
            side="right", padx=6)
        self.due_list = ctk.CTkScrollableFrame(due_box, fg_color="transparent", height=160)
        self.due_list.pack(fill="both", expand=True, padx=6, pady=(0, 8))

        preview = ctk.CTkFrame(side)
        preview.pack(fill="both", expand=True)
        self.preview_title = ctk.CTkLabel(preview, text="Önizleme", font=ctk.CTkFont(weight="bold"),
                                          anchor="w", justify="left", wraplength=520)
        self.preview_title.pack(fill="x", padx=12, pady=(10, 4))
        self.preview_text = ctk.CTkTextbox(preview, wrap="word", font=ctk.CTkFont(size=14))
        self.preview_text.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.preview_text.configure(state="disabled")

        # --- Gönderim satırı ---
        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 4))
        self.due_label = ctk.CTkLabel(actions, text="", font=ctk.CTkFont(size=14, weight="bold"))
        self.due_label.pack(side="left")
        self.stop_button = ctk.CTkButton(actions, text="Durdur", width=110, height=40, command=self.stop,
                                         state="disabled", fg_color="gray70", hover_color=RED_HOVER,
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.stop_button.pack(side="right")
        self.send_button = ctk.CTkButton(actions, text="Hatırlatma gönder", width=280, height=40,
                                         command=self._on_send_button, fg_color=GREEN, hover_color=GREEN_HOVER,
                                         font=ctk.CTkFont(size=14, weight="bold"))
        self.send_button.pack(side="right", padx=10)
        # Google sunucusu: bilgisayar kapalıyken hatırlatma
        self.server_cancel_button = ctk.CTkButton(actions, text="Google planını iptal et", width=160, height=40,
                                                  command=self.cancel_server_plan, fg_color=ORANGE,
                                                  hover_color=ORANGE_HOVER)
        self.server_cancel_button.pack(side="right")
        self.server_button = ctk.CTkButton(actions, text="Google'da planla", width=150, height=40,
                                           command=self.open_server_plan, fg_color="#7b3fb5", hover_color="#5f2f8c",
                                           font=ctk.CTkFont(size=14, weight="bold"))
        self.server_button.pack(side="right", padx=10)

        self.progress = ctk.CTkProgressBar(self, height=14, progress_color=GREEN)
        self.progress.set(0)
        self.progress.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 2))
        self.log_box = ctk.CTkTextbox(self, height=110, wrap="word", font=ctk.CTkFont(family="Consolas", size=13))
        self.log_box.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.log_box.configure(state="disabled")

    def _setting_row(self, parent, row, label, value, width=90):
        ctk.CTkLabel(parent, text=label).grid(row=row, column=0, sticky="w", padx=14, pady=4)
        entry = ctk.CTkEntry(parent, width=width)
        entry.grid(row=row, column=1, sticky="w", padx=(6, 14), pady=4)
        entry.insert(0, str(value))
        entry.bind("<KeyRelease>", lambda e: self._schedule_save())
        return entry

    # ---------- Ayarlar ----------

    def _read_settings(self):
        try:
            days = int(self.days_entry.get().strip())
            max_reminders = int(self.max_entry.get().strip())
        except ValueError:
            raise ValueError("Gün sayısı ve hatırlatma sayısı tam sayı olmalı (ör. 7 ve 1).")
        if days < 1 or max_reminders < 1:
            raise ValueError("Gün sayısı ve hatırlatma sayısı en az 1 olmalı.")
        return days, max_reminders

    def reminder_times(self):
        """Hatırlatma saatleri (ilk maillerin saatlerinden ayrı). Hatalıysa ValueError."""
        return parse_times(self.times_entry.get())

    def schedule_settings(self):
        """(saatlere bağlı mı, saatler, hafta sonu atlansın mı) — hatırlatmalara özel. Saatler hatalıysa ValueError."""
        return self.schedule_check.get() == 1, self.reminder_times(), self.weekend_check.get() == 1

    def _on_schedule_option(self):
        self.db.set_setting("reminder_schedule_enabled", "1" if self.schedule_check.get() == 1 else "0")
        self.db.set_setting("reminder_skip_weekends", "1" if self.weekend_check.get() == 1 else "0")
        if self.schedule_check.get() != 1:
            self.app.set_scheduled("reminder", False)
        self.app.refresh_schedule()

    def _body(self):
        return self.body_text.get("1.0", "end-1c").rstrip()

    def _schedule_save(self):
        if self._save_job:
            self.after_cancel(self._save_job)
        self._save_job = self.after(400, self.save_settings)

    def save_settings(self):
        self._save_job = None
        self.db.set_setting("reminder_body", self._body())
        try:
            days, max_reminders = self._read_settings()
        except ValueError:
            pass
        else:
            self.db.set_setting("reminder_days", days)
            self.db.set_setting("reminder_max", max_reminders)
        try:
            self.db.set_setting("reminder_times", format_times(self.reminder_times()))
        except ValueError:
            pass
        self.app.refresh_schedule()
        self.refresh()
        self.app.update_notice()

    def _save_auto_check(self):
        self.db.set_setting("auto_reply_check", "1" if self.auto_check.get() == 1 else "0")

    def auto_check_enabled(self):
        return self.auto_check.get() == 1

    # ---------- Görünüm ----------

    def due_contacts(self):
        try:
            days, max_reminders = self._read_settings()
        except ValueError:
            return []
        return due_for_reminder(self.db.list_contacts(), days, max_reminders)

    # ---------- Hatırlatma listesi (seçim) ----------

    def selected_due(self, due=None):
        due = self.due_contacts() if due is None else due
        return [c for c in due if c["id"] not in self._excluded]

    @staticmethod
    def _days_waiting(contact):
        """Son mailden (ilk mail ya da son hatırlatma) bu yana geçen gün."""
        last = contact.get("last_reminder_at") or contact.get("sent_at")
        try:
            return (datetime.now() - datetime.strptime(last, TIME_FORMAT)).days
        except (TypeError, ValueError):
            return 0

    def _set_selected(self, contact_ids, selected):
        for cid in contact_ids:
            if selected:
                self._excluded.discard(cid)
            else:
                self._excluded.add(cid)
        self.db.set_setting("reminder_excluded", json.dumps(sorted(self._excluded)))
        self.refresh()
        self.app.update_notice()

    def _select_all(self, selected):
        self._set_selected([c["id"] for c in self.due_contacts()], selected)

    def _show_preview(self, contact_id):
        self._preview_id = contact_id
        self.refresh()

    def _render_due_list(self, due):
        signature = tuple((c["id"], self._days_waiting(c), c["id"] in self._excluded, c.get("reminder_count") or 0,
                           c["id"] == self._preview_id) for c in due)
        if signature == self._due_signature:
            return
        self._due_signature = signature
        for child in self.due_list.winfo_children():
            child.destroy()
        if not due:
            ctk.CTkLabel(self.due_list, text="Şu an hatırlatma zamanı gelen firma yok.", text_color="gray45").pack(
                anchor="w", padx=6, pady=6)
            return
        groups = {}
        for c in sorted(due, key=lambda c: (-self._days_waiting(c), c["firma"].casefold())):
            groups.setdefault(self._days_waiting(c), []).append(c)
        for days, items in groups.items():
            ids = [c["id"] for c in items]
            header = ctk.CTkCheckBox(
                self.due_list, text=f"Son mailden {days} gün geçenler ({len(items)})",
                font=ctk.CTkFont(weight="bold"), checkbox_width=18, checkbox_height=18,
                command=lambda ids=ids: self._set_selected(ids, any(i in self._excluded for i in ids)))
            if not any(i in self._excluded for i in ids):
                header.select()
            header.pack(anchor="w", padx=4, pady=(8, 2))
            for c in items:
                row = ctk.CTkFrame(self.due_list, fg_color=("#e3e9f1", "gray25") if c["id"] == self._preview_id
                                   else "transparent", corner_radius=6)
                row.pack(fill="x", padx=(22, 4), pady=1)
                box = ctk.CTkCheckBox(row, text="", width=24, checkbox_width=16, checkbox_height=16,
                                      command=lambda c=c: self._set_selected([c["id"]], c["id"] in self._excluded))
                if c["id"] not in self._excluded:
                    box.select()
                box.pack(side="left", padx=(4, 0))
                count = c.get("reminder_count") or 0
                text = f"{c['firma']}   <{c['email']}>" + (f"   •   {count + 1}. hatırlatma" if count else "")
                name = ctk.CTkLabel(row, text=text, anchor="w", cursor="hand2")
                name.pack(side="left", fill="x", expand=True, padx=4)
                name.bind("<Button-1>", lambda e, cid=c["id"]: self._show_preview(cid))

    def refresh(self):
        contacts = self.db.list_contacts()
        c = reply_counts(contacts)
        rate = f"  (%{round(100 * c['replied'] / c['sent'])})" if c["sent"] else ""
        self.stats_label.configure(text=(
            f"Gönderilen firma:  {c['sent']}\n"
            f"Cevap veren:  {c['replied']}{rate}\n"
            f"Cevap bekleyen:  {c['waiting']}   (otomatik yanıt veren: {c['auto']})\n"
            f"Ulaşmayan (adres hatalı):  {c['bounced']}\n"
            f"Hatırlatma gönderilen firma:  {c['reminded']}"
        ))
        last = self.db.get_setting("last_reply_check")
        self.last_check_label.configure(text=f"Son kontrol: {display_time(last)}" if last else "Henüz kontrol edilmedi")

        all_due = self.due_contacts()
        self._render_due_list(all_due)
        due = self.selected_due(all_due)
        chosen = f" ({len(due)} / {len(all_due)} seçili)" if len(due) != len(all_due) else ""
        planned = self.db.reminder_planned_contacts()
        if self.is_sending():
            pass
        elif planned:
            times = sorted({c["reminder_scheduled_for"] for c in planned if c.get("reminder_scheduled_for")})
            when = ""
            if times:
                try:
                    when = " — " + describe(datetime.strptime(times[0], TIME_FORMAT))
                except ValueError:
                    pass
            extra = f"   •   zamanı gelen {len(due)} firma daha" if due else ""
            self.due_label.configure(text=f"☁ Google'da planlı hatırlatma: {len(planned)} firma{when}{extra}",
                                     text_color="#7b3fb5")
        elif self.app.is_scheduled("reminder"):
            self.due_label.configure(
                text=f"⏰ Hatırlatma planlandı: {self.app.upcoming_slot_text('reminder')} ({len(due)} firma)",
                text_color=ORANGE)
        elif all_due:
            self.due_label.configure(text=f"Hatırlatma zamanı gelen: {len(all_due)} firma{chosen}",
                                     text_color="#b05a00")
        else:
            self.due_label.configure(text="Şu an hatırlatma zamanı gelen firma yok.", text_color="gray35")
        self._update_buttons(len(due))
        previewed = next((x for x in all_due if x["id"] == self._preview_id), None)
        self._update_preview(previewed or (due[0] if due else (all_due[0] if all_due else
                             next((x for x in contacts if x.get("thread_id")), None))))

    def _update_preview(self, contact):
        if contact:
            body, missing = render(self._body(), contact_fields(contact))
            body = preview_body(body, load_signature(self.db))
            title = f"Önizleme: {contact['firma']} <{contact['email']}>\nKonu: {reply_subject(contact.get('sent_subject'))}"
            if missing:
                title += "\n⚠ Bu firmada boş alan: " + ", ".join("{{" + m + "}}" for m in missing)
        else:
            body, title = self._body(), "Önizleme (henüz gönderilmiş firma yok)"
        self.preview_title.configure(text=title, text_color="#c5221f" if contact and missing else ("gray10", "gray90"))
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", body)
        self.preview_text.configure(state="disabled")

    def set_checking(self, checking):
        self.check_button.configure(state="disabled" if checking else "normal",
                                    text="Kontrol ediliyor..." if checking else "Cevapları şimdi kontrol et")

    def log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"[{datetime.now():%H:%M:%S}] {text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    # ---------- Hatırlatma gönderimi ----------

    def is_sending(self):
        return self.worker is not None and self.worker.is_alive()

    def refresh_schedule(self):
        self.refresh()

    def _update_buttons(self, due_count=None):
        if due_count is None:
            due_count = len(self.selected_due())
        sending = self.is_sending()
        if self.app.is_scheduled("reminder") and not sending:
            self.send_button.configure(state="normal", text="Hatırlatma planını iptal et",
                                       fg_color=ORANGE, hover_color=ORANGE_HOVER)
        else:
            verb = "planla" if self.schedule_check.get() == 1 else "gönder"
            self.send_button.configure(
                state="disabled" if (self.app.busy or not due_count) else "normal",
                text=f"Hatırlatmayı {verb} ({due_count} firma)" if due_count else f"Hatırlatmayı {verb}",
                fg_color=GREEN, hover_color=GREEN_HOVER,
            )
        self.stop_button.configure(state="normal" if sending else "disabled", text="Durdur",
                                   fg_color=RED if sending else "gray70")
        has_plan = bool(self.db.reminder_planned_contacts())
        self.server_button.configure(state="disabled" if self.app.busy else "normal")
        self.server_cancel_button.configure(state="normal" if has_plan and not self.app.busy else "disabled")

    # ---------- Google sunucusuyla hatırlatma ----------

    def open_server_plan(self):
        if self.app.busy:
            return
        if not self.app.gmail.connected:
            messagebox.showwarning("Gmail bağlı değil", "Önce sağ üstteki 'Gmail ile bağlan' butonuyla bağlanın.")
            return
        body = self._body()
        try:
            self._read_settings()
            self.app.send_tab._read_settings()
            self.schedule_settings()
        except ValueError as exc:
            messagebox.showerror("Ayar hatası", str(exc))
            return
        if not body:
            messagebox.showwarning("Metin boş", "Hatırlatma metnini yazın.")
            return
        cc, cc_invalid = self.app.template_tab.get_cc()
        if cc_invalid:
            messagebox.showerror("Geçersiz CC", "Şu CC adresleri geçersiz ('Mail Metni' sekmesi):\n" + "\n".join(cc_invalid))
            return
        signature = load_signature(self.db)
        problems = signature_problems(signature)
        if problems:
            messagebox.showerror("İmza sorunu", "\n".join(problems))
            return
        self.save_settings()
        ServerPlanDialog(self, self.app, cc, signature, kind="reminder", reminder_body=body,
                         excluded_ids=set(self._excluded))

    def cancel_server_plan(self):
        count = len(self.db.reminder_planned_contacts())
        if not count or not messagebox.askyesno(
            "Google planını iptal et",
            f"Google'da planlı {count} hatırlatma taslağı Gmail'den silinecek. Devam edilsin mi?"):
            return
        self.app.set_busy(True)

        def done(result):
            cancelled, already_sent = result
            self.app.set_busy(False)
            self.app.contacts_changed()
            text = f"{cancelled} hatırlatmanın Google planı iptal edildi."
            if already_sent:
                text += f" {already_sent} hatırlatma bu arada zaten gönderilmişti."
            self.log(text)
            messagebox.showinfo("Google planı iptal edildi", text)

        def failed(message):
            self.app.set_busy(False)
            self.app.contacts_changed()
            messagebox.showerror("İptal tamamlanamadı", message)

        self.app.run_background(lambda: server_plan.cancel_reminder_plan(self.db, self.app.gmail),
                                on_done=done, on_error=failed)

    def _on_send_button(self):
        if self.app.is_scheduled("reminder"):
            if messagebox.askyesno("Planı iptal et", "Planlı hatırlatma iptal edilsin mi?"):
                self.app.set_scheduled("reminder", False)
                self.log("Planlı hatırlatma iptal edildi.")
            return
        self.start()

    def _report(self, title, message, interactive, level="warning"):
        if interactive:
            {"warning": messagebox.showwarning, "error": messagebox.showerror}[level](title, message)
        else:
            self.log(f"{title}: " + message.replace("\n", " "))

    def start(self, scheduled=False):
        """Kullanıcı basınca onay alır (saat kısıtı açıksa planlar); zamanlayıcı çağırınca onaysız gönderir."""
        if self.app.busy:
            return False
        interactive = not scheduled
        if not self.app.gmail.connected:
            self._report("Gmail bağlı değil", "Önce sağ üstteki 'Gmail ile bağlan' butonuyla bağlanın.", interactive)
            return False
        body = self._body()
        if not body:
            self._report("Metin boş", "Hatırlatma metnini yazın.", interactive)
            return False
        try:
            self._read_settings()
            self.reminder_times()
            delay, limit = self.app.send_tab._read_settings()
        except ValueError as exc:
            self._report("Ayar hatası", str(exc), interactive, "error")
            return False
        cc, cc_invalid = self.app.template_tab.get_cc()
        if cc_invalid:
            self._report("Geçersiz CC", "Şu CC adresleri geçersiz ('Mail Metni' sekmesi):\n" + "\n".join(cc_invalid),
                         interactive, "error")
            return False
        signature = load_signature(self.db)
        problems = signature_problems(signature)
        if problems:
            self._report("İmza sorunu", "\n".join(problems), interactive, "error")
            return False
        due = self.selected_due()
        if not due:
            if scheduled:
                self.app.set_scheduled("reminder", False)
                self.log("Planlı hatırlatma: zamanı gelen firma kalmamış.")
            return False

        per_mail = 1 + len(cc)
        can_send = quota.gmail_room(self.db, limit) // per_mail
        planned = interactive and self.schedule_check.get() == 1
        if can_send == 0 and not planned:
            self._report("Günlük limit dolu", "Günlük alıcı limiti dolu, daha sonra tekrar deneyin.", interactive)
            return False

        if interactive:
            missing = sum(1 for c in due if render(body, contact_fields(c))[1])
            lines = [f"{len(due)} firmaya hatırlatma gönderilecek (ilk mailin cevabı olarak, aynı konuşmada)."]
            if planned:
                lines.append(f"\n⏰ Gönderim zamanı: {self.app.upcoming_slot_text('reminder')}. "
                             "Saat gelince otomatik gider; o saatte uygulama açık olmalı.")
            lines.append("Göndermeden hemen önce cevaplar tekrar kontrol edilir; bu arada cevap verenlere gönderilmez.")
            if can_send < len(due):
                lines.append(f"\nGünlük limit nedeniyle bu sefer en fazla {can_send} firmaya gidebilir.")
            if missing:
                lines.append(f"\n⚠ {missing} firmada metindeki bir alan boş; bunlara gönderilmez.")
            lines.append("CC: " + (", ".join(cc) if cc else "(yok)"))
            lines.append("İmza: " + ("var" if signature else "yok"))
            lines.append("\nOnaylıyor musunuz?")
            if not messagebox.askyesno("Hatırlatmayı onayla", "\n".join(lines), icon="warning"):
                return False
            self.save_settings()
            if planned:
                self.app.set_scheduled("reminder", True)
                self.log(f"Hatırlatma planlandı: {self.app.upcoming_slot_text('reminder')}.")
                return True

        job = ReminderJob(body=body, contact_ids=[c["id"] for c in due], cc=cc, signature=signature,
                          sender_name=self.app.send_tab.sender_entry.get().strip(), delay=delay, daily_limit=limit)
        self.worker = ReminderWorker(self.db, self.app.gmail, job,
                                     notify=lambda ev: self.app.call_in_ui(self._on_event, ev))
        self._scheduled_run = scheduled
        self.app.set_busy(True)
        self.log(("Planlı hatırlatma başladı: " if scheduled else "Hatırlatma başladı: ") + f"{len(due)} firma.")
        self.worker.start()
        return True

    def stop(self):
        if self.is_sending():
            self.worker.stop()
            self.stop_button.configure(state="disabled", text="Durduruluyor...")

    def stop_and_wait(self):
        if self.is_sending():
            self.worker.stop()
            self.worker.join(timeout=20)

    def _on_event(self, ev):
        kind = ev["type"]
        if kind == "start":
            self.progress.set(0)
        elif kind == "sending":
            c = ev["contact"]
            self.due_label.configure(text=f"Gönderiliyor ({ev['index']} / {ev['total']}): {c['firma']}",
                                     text_color=("gray10", "gray90"))
        elif kind in ("result", "skipped"):
            self.progress.set(ev["index"] / max(1, ev["total"]))
            if kind == "result":
                c = ev["contact"]
                mark = {True: "✓", False: "✗", None: "–"}[ev["ok"]]
                self.log(f"{mark} {c['firma']} <{c['email']}>" + (f": {ev['message']}" if ev["message"] else ""))
                self.app.contacts_tab.update_contact_row(c["id"])
        elif kind == "finished":
            scheduled_run, self._scheduled_run = self._scheduled_run, False
            self.worker = None
            if scheduled_run:
                self.app.set_scheduled("reminder", False)
            self.app.set_busy(False)
            self.app.contacts_changed()
            summary = f"Gönderilen: {ev['sent']}    Atlanan: {ev['skipped']}    Hatalı: {ev['failed']}"
            if ev["stop_reason"]:
                self.log("Durdu: " + ev["stop_reason"].replace("\n", " "))
                if not scheduled_run:
                    messagebox.showwarning("Hatırlatma durdu", f"{ev['stop_reason']}\n\n{summary}")
            else:
                self.progress.set(1)
                self.log("Tamamlandı. " + summary)
                if not scheduled_run:
                    messagebox.showinfo("Hatırlatma tamamlandı", summary)
