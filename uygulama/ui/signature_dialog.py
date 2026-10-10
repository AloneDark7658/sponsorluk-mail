"""İmza ayarları penceresi: kartvizit şablonu ya da düz metin, logo, açık/kapalı."""
import json
import logging
import shutil
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import DATA_DIR
from mail_format import (CARD_FIELDS, DEFAULT_LOGO_WIDTH, SIGNATURE_CARD, SIGNATURE_TEXT, SOCIAL_FIELDS,
                         card_plain_text, load_card, preview_html_file, size_mb)

log = logging.getLogger(__name__)

MAX_LOGO_MB = 1
MODES = {"Kartvizit şablonu": SIGNATURE_CARD, "Düz metin": SIGNATURE_TEXT}
PLACEHOLDERS = {
    "name": "Ör: Ad Soyad", "title": "Ör: Yönetim Kurulu Üyesi", "phone": "Ör: 0 (5xx) xxx xx xx",
    "email": "Ör: ad.soyad@yatirimkulubu.net", "address": "Ör: İTÜ Maçka Kampüsü", "website": "Ör: yatirimkulubu.net",
    "x": "Profil linki (boşsa ikon çıkmaz)", "instagram": "Profil linki", "facebook": "Sayfa linki",
    "linkedin": "Sayfa linki",
}
TEXT_EXAMPLE = ("Örnek:\n"
                "Ad Soyad\n"
                "Sponsorluk Sorumlusu | X Üniversitesi Yatırım Kulübü\n"
                "Tel: +90 5xx xxx xx xx\n"
                "www.kulubumuz.org")


class SignatureDialog(ctk.CTkToplevel):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.db = app.db
        self.logo = self.db.get_setting("signature_logo") or None

        self.title("Mail imzası")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        ctk.CTkLabel(self, text="Mail imzası", font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(self, text="Her mailin ve hatırlatmanın sonuna otomatik eklenir.", text_color="gray35").pack(
            anchor="w", padx=20)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(10, 6))
        self.enabled = ctk.CTkCheckBox(top, text="İmzayı maillere ekle")
        if self.db.get_setting("signature_enabled", "1") == "1":
            self.enabled.select()
        self.enabled.pack(side="left")
        self.mode = ctk.CTkSegmentedButton(top, values=list(MODES), command=lambda v: self._show_mode())
        current = self.db.get_setting("signature_mode", SIGNATURE_CARD)
        self.mode.set(next(label for label, value in MODES.items() if value == current))
        self.mode.pack(side="right")

        # --- Kartvizit formu ---
        self.card_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.card_frame.grid_columnconfigure((1, 3), weight=1)
        card = load_card(self.db)
        self.card_entries = {}
        ctk.CTkLabel(self.card_frame, text="Bilgiler", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ctk.CTkLabel(self.card_frame, text="Sosyal medya (linki olanın ikonu çıkar)",
                     font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, columnspan=2, sticky="w", padx=(16, 0),
                                                            pady=(0, 4))
        for i, (key, label) in enumerate(CARD_FIELDS):
            self._card_row(key, label, card[key], row=i + 1, column=0)
        for i, (key, label) in enumerate(SOCIAL_FIELDS):
            self._card_row(key, label, card[key], row=i + 1, column=2)

        # --- Düz metin ---
        self.text_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.text = ctk.CTkTextbox(self.text_frame, width=360, height=150, wrap="word", font=ctk.CTkFont(size=14))
        self.text.pack(side="left")
        self.text.insert("1.0", self.db.get_setting("signature_text") or "")
        ctk.CTkLabel(self.text_frame, text=TEXT_EXAMPLE, text_color="gray45", justify="left", anchor="nw").pack(
            side="left", anchor="n", padx=(12, 0))

        self.body_slot = ctk.CTkFrame(self, fg_color="transparent")
        self.body_slot.pack(fill="x", padx=20)

        # --- Logo ---
        logo_bar = ctk.CTkFrame(self, fg_color="transparent")
        logo_bar.pack(fill="x", padx=20, pady=(12, 0))
        ctk.CTkLabel(logo_bar, text="Logo:").pack(side="left")
        ctk.CTkButton(logo_bar, text="Logo seç", width=90, command=self.choose_logo).pack(side="left", padx=8)
        ctk.CTkButton(logo_bar, text="Kaldır", width=70, command=self.remove_logo,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="left")
        self.logo_label = ctk.CTkLabel(logo_bar, text="", text_color="gray35")
        self.logo_label.pack(side="left", padx=10)
        ctk.CTkLabel(logo_bar, text="Genişlik (px):").pack(side="left", padx=(10, 4))
        self.width_entry = ctk.CTkEntry(logo_bar, width=60)
        self.width_entry.insert(0, self.db.get_setting("signature_logo_width", DEFAULT_LOGO_WIDTH))
        self.width_entry.pack(side="left")
        self._update_logo_label()

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        ctk.CTkButton(buttons, text="Tarayıcıda önizle", width=140, command=self.preview).pack(side="left")
        ctk.CTkButton(buttons, text="Kaydet", width=110, command=self.save,
                      fg_color="#1e8e3e", hover_color="#17712f").pack(side="right")
        ctk.CTkButton(buttons, text="İptal", width=90, command=self.destroy,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="right", padx=8)

        self._show_mode()
        self.bind("<Escape>", lambda e: self.destroy())
        # CTkToplevel Windows'ta bazen ana pencerenin arkasında açılıyor; öne getir.
        self.after(150, self._bring_to_front)

    def _card_row(self, key, label, value, row, column):
        ctk.CTkLabel(self.card_frame, text=label).grid(row=row, column=column, sticky="w",
                                                      padx=(16 if column else 0, 8), pady=3)
        entry = ctk.CTkEntry(self.card_frame, width=230, placeholder_text=PLACEHOLDERS.get(key))
        if value:
            entry.insert(0, value)
        entry.grid(row=row, column=column + 1, sticky="ew", pady=3)
        self.card_entries[key] = entry

    def _bring_to_front(self):
        self.lift()
        self.focus_force()
        self.grab_set()

    def _mode(self):
        return MODES[self.mode.get()]

    def _show_mode(self):
        self.card_frame.pack_forget()
        self.text_frame.pack_forget()
        frame = self.card_frame if self._mode() == SIGNATURE_CARD else self.text_frame
        frame.pack(in_=self.body_slot, fill="x")

    def _update_logo_label(self):
        if not self.logo:
            self.logo_label.configure(text="Logo yok", text_color="gray35")
        elif not Path(self.logo).exists():
            self.logo_label.configure(text="Logo dosyası bulunamadı!", text_color="#c5221f")
        else:
            self.logo_label.configure(text=f"{Path(self.logo).name} ({size_mb(self.logo) * 1024:.0f} KB)",
                                      text_color="gray35")

    def choose_logo(self):
        path = filedialog.askopenfilename(parent=self, title="Logo seçin",
                                          filetypes=[("Görsel", "*.png *.jpg *.jpeg *.gif")])
        if not path:
            return
        if size_mb(path) > MAX_LOGO_MB:
            messagebox.showerror("Logo çok büyük",
                                 f"Logo en fazla {MAX_LOGO_MB} MB olabilir (küçük bir PNG idealdir, ~50 KB).",
                                 parent=self)
            return
        self.logo = path
        self._update_logo_label()

    def remove_logo(self):
        self.logo = None
        self._update_logo_label()

    def _card_values(self):
        return {key: entry.get().strip() for key, entry in self.card_entries.items()}

    def _read_width(self):
        try:
            width = int(self.width_entry.get().strip())
            if not 30 <= width <= 600:
                raise ValueError
        except ValueError:
            messagebox.showerror("Hatalı değer", "Logo genişliği 30 ile 600 arasında bir sayı olmalı.", parent=self)
            return None
        return width

    def _current_signature(self, width):
        if self._mode() == SIGNATURE_CARD:
            card = self._card_values()
            return {"mode": SIGNATURE_CARD, "card": card, "text": card_plain_text(card), "logo": self.logo,
                    "logo_width": width}
        return {"mode": SIGNATURE_TEXT, "text": self.text.get("1.0", "end-1c").strip(), "logo": self.logo,
                "logo_width": width}

    def preview(self):
        width = self._read_width()
        if width is None:
            return
        signature = self._current_signature(width)
        if signature["mode"] == SIGNATURE_CARD and not signature["card"]["name"]:
            messagebox.showinfo("Önizleme", "Önce en azından 'Ad Soyad'ı yazın.", parent=self)
            return
        try:
            webbrowser.open(preview_html_file(signature).as_uri())
        except OSError:
            log.exception("İmza önizlemesi açılamadı")
            messagebox.showerror("Önizleme açılamadı", "Ayrıntılar uygulama.log dosyasında.", parent=self)

    def save(self):
        width = self._read_width()
        if width is None:
            return
        if self._mode() == SIGNATURE_CARD and not self.card_entries["name"].get().strip():
            messagebox.showerror("Eksik bilgi", "Kartvizit şablonu için en azından 'Ad Soyad' gerekli.", parent=self)
            return

        logo = self.logo
        if logo and Path(logo).exists() and Path(logo).parent.resolve() != DATA_DIR.resolve():
            # Orijinal dosya taşınsa/silinse de imza bozulmasın diye 'veriler' klasörüne kopyala.
            target = DATA_DIR / f"imza_logo{Path(logo).suffix.lower()}"
            try:
                shutil.copyfile(logo, target)
                logo = str(target)
            except OSError:
                log.exception("Logo kopyalanamadı")

        self.db.set_setting("signature_enabled", "1" if self.enabled.get() == 1 else "0")
        self.db.set_setting("signature_mode", self._mode())
        self.db.set_setting("signature_card", json.dumps(self._card_values(), ensure_ascii=False))
        self.db.set_setting("signature_text", self.text.get("1.0", "end-1c").strip())
        self.db.set_setting("signature_logo", logo or "")
        self.db.set_setting("signature_logo_width", width)
        log.info("İmza ayarları kaydedildi (%s)", self._mode())
        self.app.template_tab.refresh_signature()
        self.app.followup_tab.refresh()
        self.destroy()
