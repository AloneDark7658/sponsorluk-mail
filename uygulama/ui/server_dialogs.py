"""Google sunucusu: kurulum penceresi ve 'Google'da planla' penceresi."""
import logging
import math
import webbrowser
from datetime import datetime
from tkinter import messagebox

import customtkinter as ctk

import server_plan
from database import display_time
from schedule import describe, format_times, next_slot

log = logging.getLogger(__name__)

SPLIT = "İkiye böl"
STEPS = (
    "1)  'Kodu kopyala'ya basın.\n"
    "2)  'script.google.com'u aç'a basın (Gmail hesabınızla yeni bir proje açılır).\n"
    "3)  Sayfadaki hazır kodu tamamen silip kopyaladığınız kodu yapıştırın, Ctrl+S ile kaydedin.\n"
    "4)  Üstteki fonksiyon listesinden 'kurulum'u seçip 'Çalıştır'a basın. İzin isterse:\n"
    "      hesabınızı seçin → Gelişmiş → '... (güvenli değil)' → İzin ver.\n"
    "5)  Aşağıdaki 'Test maili planla'ya basın. 5-10 dakika içinde kendinize\n"
    "      '[TEST] Google sunucusu çalışıyor' maili gelmeli. Gelince kurulum tamamdır."
)


def _bring_to_front(window, focus=None):
    window.lift()
    window.focus_force()
    window.grab_set()
    if focus:
        focus.focus_set()


class ServerSetupDialog(ctk.CTkToplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.db = app.db
        self.title("Google sunucusu kurulumu")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        ctk.CTkLabel(self, text="Google sunucusu kurulumu (bir kez)", font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(
            self, text="Bu kurulumdan sonra planladığınız mailler bilgisayarınız kapalıyken de Google'ın sunucusundan "
                       "gider. Google bu yolla günde en fazla 100 alıcıya izin verir (CC dahil).",
            text_color="gray35", wraplength=600, justify="left",
        ).pack(anchor="w", padx=20)
        ctk.CTkLabel(self, text=STEPS, justify="left", anchor="w", font=ctk.CTkFont(size=13)).pack(
            anchor="w", padx=20, pady=12)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20)
        self.copy_button = ctk.CTkButton(buttons, text="Kodu kopyala", width=130, command=self.copy_code)
        self.copy_button.pack(side="left")
        ctk.CTkButton(buttons, text="script.google.com'u aç", width=170,
                      command=lambda: webbrowser.open(server_plan.SCRIPT_URL)).pack(side="left", padx=8)
        self.test_button = ctk.CTkButton(buttons, text="Test maili planla", width=140, command=self.send_test,
                                         fg_color="#1e8e3e", hover_color="#17712f")
        self.test_button.pack(side="left")

        self.status = ctk.CTkLabel(self, text="", justify="left", anchor="w", wraplength=600)
        self.status.pack(fill="x", padx=20, pady=(12, 0))
        self._update_status()
        ctk.CTkButton(self, text="Kapat", width=90, command=self.destroy, fg_color="#5f6b7a",
                      hover_color="#4a5462").pack(anchor="e", padx=20, pady=16)
        self.bind("<Escape>", lambda e: self.destroy())
        self.after(150, lambda: _bring_to_front(self))

    def _update_status(self):
        verified = self.db.get_setting("server_verified")
        if verified:
            self.status.configure(text=f"✓ Google sunucusu çalışıyor (test: {display_time(verified)}).",
                                  text_color="#1e8e3e")
        elif self.db.get_setting("server_test_thread"):
            self.status.configure(
                text="Test bekleniyor: test maili 5-10 dakika içinde gelmeli. Uygulama bunu kendisi fark eder; "
                     "hemen bakmak için 4. sekmede 'Cevapları şimdi kontrol et'e basın.\n"
                     "15 dakikada gelmezse: script.google.com'da 'kurulum'u çalıştırıp izin verdiğinizden emin olun.",
                text_color="#b05a00")
        else:
            self.status.configure(text="Kurulum henüz test edilmedi.", text_color="gray35")

    def copy_code(self):
        self.clipboard_clear()
        self.clipboard_append(server_plan.SCRIPT_CODE)
        self.copy_button.configure(text="Kopyalandı ✓")

    def send_test(self):
        if not self.app.gmail.connected:
            messagebox.showwarning("Gmail bağlı değil", "Önce 'Gmail ile bağlan'.", parent=self)
            return
        try:
            _, times, _ = self.app.send_tab.schedule_settings()
        except ValueError as exc:
            messagebox.showerror("Ayar hatası", str(exc), parent=self)
            return
        self.test_button.configure(state="disabled", text="Hazırlanıyor...")

        def done(_):
            if self.winfo_exists():
                self.test_button.configure(state="normal", text="Test maili planla")
                self._update_status()
            self.app.send_tab.log("Google sunucusu testi planlandı; 5-10 dakika içinde test maili gelmeli.")

        def failed(message):
            if self.winfo_exists():
                self.test_button.configure(state="normal", text="Test maili planla")
            messagebox.showerror("Test planlanamadı", message)

        self.app.run_background(lambda: server_plan.send_test(self.db, self.app.gmail, format_times(times)),
                                on_done=done, on_error=failed)


class ServerPlanDialog(ctk.CTkToplevel):
    """Bekleyen firmaların Google'ın günlük sınırına sığan kısmını taslak olarak planlar."""

    def __init__(self, master, app, mail, cc, signature):
        super().__init__(master)
        self.app = app
        self.db = app.db
        self.mail, self.cc, self.signature = mail, cc, signature
        _, self.times, self.skip_weekends = app.send_tab.schedule_settings()
        self.pending = self.db.pending_contacts()
        self.per_mail = 1 + len(cc)

        self.title("Google'da planla")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        ctk.CTkLabel(self, text="Google sunucusuyla planla", font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(self, text="Mailler Gmail'inize taslak olarak konur ve seçtiğiniz saatte Google'ın sunucusundan "
                                "gider. Bilgisayarınızın açık olması gerekmez.",
                     text_color="gray35", wraplength=560, justify="left").pack(anchor="w", padx=20)

        ctk.CTkLabel(self, text="Gönderim saati:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(14, 4))
        choices = [t.strftime("%H:%M") for t in self.times] + ([SPLIT] if len(self.times) >= 2 else [])
        self.choice = ctk.CTkSegmentedButton(self, values=choices, command=lambda v: self._refresh())
        self.choice.set(choices[0])
        self.choice.pack(anchor="w", padx=20)

        self.summary = ctk.CTkLabel(self, text="", justify="left", anchor="w", wraplength=560)
        self.summary.pack(fill="x", padx=20, pady=12)
        if not self.db.get_setting("server_verified"):
            ctk.CTkLabel(self, text="⚠ Google sunucusu kurulumu henüz test edilmedi. Kurulum yapılmazsa mailler "
                                    "taslakta bekler, gönderilmez.",
                         text_color="#c5221f", wraplength=560, justify="left").pack(anchor="w", padx=20)

        self.progress = ctk.CTkLabel(self, text="", text_color="gray35")
        self.progress.pack(anchor="w", padx=20)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        self.ok_button = ctk.CTkButton(buttons, text="Google'da planla", width=150, command=self.confirm,
                                       fg_color="#1e8e3e", hover_color="#17712f")
        self.ok_button.pack(side="right")
        ctk.CTkButton(buttons, text="İptal", width=90, command=self.destroy, fg_color="#5f6b7a",
                      hover_color="#4a5462").pack(side="right", padx=8)
        self._refresh()
        self.after(150, lambda: _bring_to_front(self))

    def _plan_items(self):
        """[(firma, zaman)] - Google'ın günlük 100 alıcı sınırına sığacak kadar."""
        now = datetime.now()
        choice = self.choice.get()
        if choice == SPLIT:
            first = next_slot(now, self.times[:1], self.skip_weekends)
            slots = [first, datetime.combine(first.date(), self.times[1])]
        else:
            chosen = next(t for t in self.times if t.strftime("%H:%M") == choice)
            slots = [next_slot(now, [chosen], self.skip_weekends)]
        room = max(0, server_plan.SERVER_DAILY_RECIPIENTS - server_plan.planned_recipients_on(self.db, slots[0].date()))
        count = min(len(self.pending), room // self.per_mail)
        selected = self.pending[:count]
        if len(slots) == 1:
            return [(c, slots[0]) for c in selected], slots
        half = math.ceil(count / 2)
        return [(c, slots[0]) for c in selected[:half]] + [(c, slots[1]) for c in selected[half:]], slots

    def _refresh(self):
        items, slots = self._plan_items()
        groups = [sum(1 for _, when in items if when == slot) for slot in slots]
        lines = [f"Şablon: {self.app.template_tab.template_label()}   •   Konu: {self.mail['subject']}"]
        if items:
            parts = [f"{n} firma {describe(slot)}" for n, slot in zip(groups, slots) if n]
            lines.append(f"Google'a verilecek: {len(items)} firma  →  " + ", ".join(parts))
        else:
            lines.append("Google'ın o günkü 100 alıcılık sınırı dolu ya da bekleyen firma yok.")
        lines.append(f"Google sınırı: günde 100 alıcı (CC dahil; 1 firma = {self.per_mail} alıcı).")
        rest = len(self.pending) - len(items)
        if rest:
            lines.append(f"Kalan {rest} firma 'Bekliyor'da kalır; onları uygulamadan siz gönderirsiniz.")
        self.summary.configure(text="\n".join(lines))
        self.ok_button.configure(state="normal" if items else "disabled")

    def confirm(self):
        items, _ = self._plan_items()
        if not items:
            return
        self.ok_button.configure(state="disabled")
        self.choice.configure(state="disabled")
        send_tab = self.app.send_tab
        sender_name = send_tab.sender_entry.get().strip()
        _, times, skip = send_tab.schedule_settings()
        template_name = self.app.template_tab.template_label()
        self.app.set_busy(True)

        def progress(done, total):
            self.app.call_in_ui(lambda: self.winfo_exists() and self.progress.configure(
                text=f"Taslaklar hazırlanıyor: {done} / {total}"))

        def work():
            return server_plan.create_plan(self.db, self.app.gmail, items, self.mail, self.cc, self.signature,
                                           sender_name, format_times(times), skip, progress, template_name)

        def done(result):
            planned, skipped = result
            self.app.set_busy(False)
            self.app.contacts_changed()
            send_tab.log(f"Google sunucusuyla planlandı: {planned} firma"
                         + (f" ({skipped} firma eksik alan yüzünden 'Hata')" if skipped else "") + ".")
            if self.winfo_exists():
                self.destroy()
            messagebox.showinfo("Google'da planlandı",
                                f"{planned} firma Google sunucusuna verildi. Bilgisayarınızı kapatabilirsiniz."
                                + (f"\n{skipped} firma eksik alan yüzünden 'Hata' olarak işaretlendi." if skipped else ""))

        def failed(message):
            self.app.set_busy(False)
            self.app.contacts_changed()
            if self.winfo_exists():
                self.destroy()
            messagebox.showerror("Planlama yarıda kaldı",
                                 message + "\n\nO ana kadar hazırlananlar Google'da planlı durumda.")

        self.app.run_background(work, on_done=done, on_error=failed)
