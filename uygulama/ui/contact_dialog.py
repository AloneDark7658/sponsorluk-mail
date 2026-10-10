"""Tek bir firmayı elle ekleme / düzenleme penceresi."""
import logging
from tkinter import messagebox

import customtkinter as ctk

from database import ERROR, REPLY_YES, SENT, SERVER, display_time
from importer import is_valid_email

log = logging.getLogger(__name__)

BASE_FIELDS = [("Email", True), ("Firma", True), ("Yetkili", False)]
SCROLL_AFTER = 6  # bundan fazla ek alan varsa kaydırılabilir alan kullan


class ContactDialog(ctk.CTkToplevel):
    def __init__(self, master, app, contact=None):
        super().__init__(master)
        self.app = app
        self.db = app.db
        self.contact = contact
        self.entries = {}

        self.title("Firmayı düzenle" if contact else "Yeni firma ekle")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        ctk.CTkLabel(
            self, text=self.title(), font=ctk.CTkFont(size=17, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 4))
        if contact:
            ctk.CTkLabel(self, text=self._status_text(), text_color="gray35", justify="left").pack(
                anchor="w", padx=20)

        extra_names = self.db.extra_field_names()
        if len(extra_names) > SCROLL_AFTER:
            form = ctk.CTkScrollableFrame(self, width=460, height=380, fg_color="transparent")
        else:
            form = ctk.CTkFrame(self, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=12, pady=8)
        form.grid_columnconfigure(1, weight=1)

        values = {"Email": "", "Firma": "", "Yetkili": ""}
        if contact:
            values = {"Email": contact["email"], "Firma": contact["firma"], "Yetkili": contact["yetkili"]}
            values.update(contact["extra"])
        fields = BASE_FIELDS + [(name, False) for name in extra_names]
        for row, (name, required) in enumerate(fields):
            ctk.CTkLabel(form, text=name + (" *" if required else "")).grid(
                row=row, column=0, sticky="w", padx=(8, 12), pady=5)
            entry = ctk.CTkEntry(form, width=340)
            entry.grid(row=row, column=1, sticky="ew", padx=(0, 8), pady=5)
            if values.get(name):
                entry.insert(0, values[name])
            self.entries[name] = entry

        ctk.CTkLabel(
            self, text="* zorunlu.  Ek sütunlar içe aktardığınız dosyadan gelir.", text_color="gray45"
        ).pack(anchor="w", padx=20)
        self.manual_reply = None
        if contact and contact["status"] == SENT:
            self.manual_reply = ctk.CTkCheckBox(
                self, text="Cevap alındı olarak işaretle (telefonla ya da başka adresten döndüyse)\n"
                           "İşaretli firmalara hatırlatma gönderilmez.",
            )
            if contact.get("manual_reply"):
                self.manual_reply.select()
            self.manual_reply.pack(anchor="w", padx=20, pady=(10, 0))
        self.error_label = ctk.CTkLabel(self, text="", text_color="#c5221f", justify="left", wraplength=460)
        self.error_label.pack(anchor="w", padx=20, pady=(4, 0))

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=(8, 16))
        locked = bool(contact and contact["status"] == SERVER)
        ctk.CTkButton(buttons, text="Kaydet", width=110, command=self.save, state="disabled" if locked else "normal",
                      fg_color="#1e8e3e", hover_color="#17712f").pack(side="right")
        ctk.CTkButton(buttons, text="İptal", width=90, command=self.destroy,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="right", padx=8)
        if contact:
            ctk.CTkButton(buttons, text="Firmayı sil", width=100, command=self.delete,
                          fg_color="#c5221f", hover_color="#a31b17",
                          state="disabled" if app.busy or locked else "normal").pack(side="left")

        self.bind("<Return>", lambda e: self.save())
        self.bind("<Escape>", lambda e: self.destroy())
        # CTkToplevel Windows'ta bazen ana pencerenin arkasında açılıyor; öne getir ve odağı al.
        self.after(150, self._bring_to_front)

    def _bring_to_front(self):
        self.lift()
        self.focus_force()
        self.grab_set()
        self.entries["Email"].focus_set()

    def _status_text(self):
        c = self.contact
        if c["status"] == SENT:
            text = f"Durum: Gönderildi ({display_time(c['sent_at'])})"
            if c.get("sent_template"):
                text += f"\nŞablon: {c['sent_template']}"
            if c.get("reply_status") == REPLY_YES:
                text += f"\nCevap: {display_time(c['reply_at'])} - {c.get('reply_from') or ''}"
            return text
        if c["status"] == SERVER:
            return ("Durum: Google'da planlı. Değiştirmek için önce Gönderim sekmesinden\n"
                    "'Google planını iptal et'e basın.")
        if c["status"] == ERROR:
            return f"Durum: Hata ({c['error']})\nKaydedince tekrar 'Bekliyor' olur."
        return "Durum: Bekliyor"

    def save(self):
        values = {name: entry.get().strip() for name, entry in self.entries.items()}
        email = values.pop("Email")
        firma = values.pop("Firma")
        yetkili = values.pop("Yetkili")
        if email.lower().startswith("mailto:"):
            email = email[7:].strip()

        if not is_valid_email(email):
            self.error_label.configure(text="Geçerli bir email adresi yazın (ör. ad@firma.com).")
            return
        if not firma:
            self.error_label.configure(text="Firma adı boş olamaz.")
            return
        other = self.db.find_by_email(email, exclude_id=self.contact["id"] if self.contact else None)
        if other:
            self.error_label.configure(text=f"Bu email listede zaten var: {other['firma']} ({other['email']})")
            return

        extra = {name: value for name, value in values.items()}
        if self.contact:
            cid = self.contact["id"]
            self.db.update_contact(cid, email, firma, yetkili, extra)
            if self.manual_reply is not None:
                self.db.set_manual_reply(cid, self.manual_reply.get() == 1)
            if self.contact["status"] == ERROR:
                self.db.set_pending([cid])
            elif (self.contact["status"] == SENT and email.lower() != self.contact["email"].lower()
                  and messagebox.askyesno(
                      "Email değişti",
                      "Bu firmaya daha önce eski adresten mail gönderilmişti.\n"
                      "Yeni adrese de gönderilmesi için 'Bekliyor' yapılsın mı?", parent=self)):
                self.db.set_pending([cid])
            log.info("Firma düzenlendi: %s", email)
        else:
            self.db.add_contacts([{"email": email, "firma": firma, "yetkili": yetkili, "extra": extra}])
            log.info("Firma elle eklendi: %s", email)

        self.app.contacts_changed()
        self.destroy()

    def delete(self):
        if messagebox.askyesno("Firmayı sil", f"'{self.contact['firma']}' listeden silinsin mi?", parent=self):
            self.db.delete_contacts([self.contact["id"]])
            self.app.contacts_changed()
            self.destroy()
