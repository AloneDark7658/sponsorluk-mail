"""Mail metni sekmesi: konu, gövde, CC, ek, şablonlar ve canlı önizleme."""
import logging
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from config import MAX_TOTAL_ATTACHMENT_MB
from importer import split_emails
from mail_format import (attachment_problems, blocked, dump_attachments, load_signature, parse_attachments,
                         preview_body, signature_problems, size_mb, total_size_mb)
from template_engine import contact_fields, normalize_key, render_mail
from ui.signature_dialog import SignatureDialog
from ui.variables import VariablePanel, attach_variable_menu, insert_variable

log = logging.getLogger(__name__)

NO_TEMPLATES = "(kayıtlı şablon yok)"
CHOOSE_TEMPLATE = "(şablon seçin)"
EMPTY_LIST = "(liste boş)"
OK_COLOR = "#1e8e3e"
WARN_COLOR = "#c5221f"
FIELD_COLUMNS = 5


def _file_size_text(path):
    return f"{size_mb(path):.1f} MB" if Path(path).exists() else "bulunamadı!"


class TemplateTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.db = app.db
        self.attachments = []
        self.current_template = None
        self.preview_contact_id = None
        self._preview_ids = []
        self._preview_labels = []
        self._update_job = None
        self._field_target = "body"

        self.grid_columnconfigure(0, weight=3, uniform="col")
        self.grid_columnconfigure(1, weight=2, uniform="col")
        self.grid_rowconfigure(0, weight=1)
        editor = ctk.CTkFrame(self)
        editor.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        preview = ctk.CTkFrame(self)
        preview.grid(row=0, column=1, sticky="nsew")
        self._build_editor(editor)
        self._build_preview(preview)
        self._load_draft()

    # ---------- Düzen ----------

    def _build_editor(self, f):
        f.grid_columnconfigure(1, weight=1)
        f.grid_rowconfigure(6, weight=1)
        label_font = ctk.CTkFont(size=13, weight="bold")
        pad = {"padx": 10, "pady": 5}

        ctk.CTkLabel(f, text="Şablon", font=label_font).grid(row=0, column=0, sticky="w", **pad)
        bar = ctk.CTkFrame(f, fg_color="transparent")
        bar.grid(row=0, column=1, sticky="ew", **pad)
        self.template_menu = ctk.CTkOptionMenu(bar, values=[NO_TEMPLATES], width=240, dynamic_resizing=False,
                                               command=self._on_template_selected)
        self.template_menu.pack(side="left")
        ctk.CTkButton(bar, text="Kaydet", width=80, command=self.save_template).pack(side="left", padx=(8, 0))
        ctk.CTkButton(bar, text="Yeni şablon olarak kaydet", width=180, command=self.save_template_as,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="left", padx=(8, 0))
        ctk.CTkButton(bar, text="Sil", width=50, command=self.delete_template,
                      fg_color="#c5221f", hover_color="#a31b17").pack(side="left", padx=(8, 0))

        ctk.CTkLabel(f, text="Konu", font=label_font).grid(row=1, column=0, sticky="w", **pad)
        self.subject_entry = ctk.CTkEntry(f, height=34, placeholder_text="Örn: {{Firma}} için sponsorluk teklifi")
        self.subject_entry.grid(row=1, column=1, sticky="ew", **pad)
        self.subject_entry.bind("<KeyRelease>", lambda e: self._schedule_update())
        self.subject_entry.bind("<FocusIn>", lambda e: self._set_field_target("subject"))

        ctk.CTkLabel(f, text="Sabit CC", font=label_font).grid(row=2, column=0, sticky="w", **pad)
        cc_bar = ctk.CTkFrame(f, fg_color="transparent")
        cc_bar.grid(row=2, column=1, sticky="ew", **pad)
        self.cc_entry = ctk.CTkEntry(cc_bar, height=34, placeholder_text="CC adresi yazıp Enter'a basın")
        self.cc_entry.pack(side="left", fill="x", expand=True)
        self.cc_entry.bind("<Return>", lambda e: self.add_cc())
        ctk.CTkButton(cc_bar, text="+ Ekle", width=80, height=34, command=self.add_cc).pack(side="left", padx=(8, 0))
        cc_box = ctk.CTkFrame(f, fg_color="transparent")
        cc_box.grid(row=3, column=1, sticky="ew", padx=10, pady=(0, 4))
        self.cc_list_frame = ctk.CTkFrame(cc_box, fg_color="transparent")
        self.cc_list_frame.pack(fill="x")
        self.cc_hint = ctk.CTkLabel(cc_box, text="", text_color="gray40", anchor="w")
        self.cc_hint.pack(fill="x")
        self.cc_addresses = []

        ctk.CTkLabel(f, text="Ekler", font=label_font).grid(row=4, column=0, sticky="nw", padx=10, pady=(10, 5))
        attach_box = ctk.CTkFrame(f, fg_color="transparent")
        attach_box.grid(row=4, column=1, sticky="ew", **pad)
        attach_bar = ctk.CTkFrame(attach_box, fg_color="transparent")
        attach_bar.pack(fill="x")
        ctk.CTkButton(attach_bar, text="+ Dosya ekle", width=120, command=self.add_attachments).pack(side="left")
        self.attachment_total = ctk.CTkLabel(attach_bar, text="", text_color="gray40", anchor="w")
        self.attachment_total.pack(side="left", padx=10)
        self.attachment_list = ctk.CTkFrame(attach_box, fg_color="transparent")
        self.attachment_list.pack(fill="x")

        ctk.CTkLabel(f, text="İmza", font=label_font).grid(row=5, column=0, sticky="w", **pad)
        signature_bar = ctk.CTkFrame(f, fg_color="transparent")
        signature_bar.grid(row=5, column=1, sticky="ew", **pad)
        ctk.CTkButton(signature_bar, text="İmzayı düzenle", width=120, command=self.open_signature,
                      fg_color="#5f6b7a", hover_color="#4a5462").pack(side="left")
        self.signature_label = ctk.CTkLabel(signature_bar, text="", text_color="gray40", anchor="w")
        self.signature_label.pack(side="left", padx=10)

        ctk.CTkLabel(f, text="Mail metni", font=label_font).grid(row=6, column=0, sticky="nw", padx=10, pady=(10, 5))
        body_box = ctk.CTkFrame(f, fg_color="transparent")
        body_box.grid(row=6, column=1, sticky="nsew", padx=10, pady=(5, 10))
        self.body_text = ctk.CTkTextbox(body_box, wrap="word", font=ctk.CTkFont(size=14), undo=True)
        self.body_text.pack(side="left", fill="both", expand=True)
        self.body_text.bind("<KeyRelease>", lambda e: self._schedule_update())
        self.body_text.bind("<FocusIn>", lambda e: self._set_field_target("body"))
        # Yan panel: kullanılabilecek değişkenler (önizlemedeki firmanın değerleriyle)
        self.variable_panel = VariablePanel(body_box, self.variables, self.insert_field)
        self.variable_panel.pack(side="right", fill="y", padx=(8, 0))
        # Sağ tık -> Değişken ekle: tıklanan yere yazar
        attach_variable_menu(self.body_text, self.variables, self._schedule_update)
        attach_variable_menu(self.subject_entry, self.variables, self._schedule_update)

    def _build_preview(self, f):
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(f, text="Önizleme", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 4))

        nav = ctk.CTkFrame(f, fg_color="transparent")
        nav.grid(row=1, column=0, sticky="ew", padx=12)
        ctk.CTkLabel(nav, text="Önizlenecek firma:").pack(side="left", padx=(0, 6))
        ctk.CTkButton(nav, text="<", width=34, command=lambda: self._step_preview(-1)).pack(side="left")
        self.contact_menu = ctk.CTkOptionMenu(nav, values=[EMPTY_LIST], dynamic_resizing=False,
                                              command=self._on_contact_menu)
        self.contact_menu.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(nav, text=">", width=34, command=lambda: self._step_preview(1)).pack(side="left")

        info = ctk.CTkFrame(f, fg_color=("gray95", "gray20"))
        info.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 4))
        info.grid_columnconfigure(1, weight=1)
        self.info_labels = {}
        for row, key in enumerate(("Kime", "CC", "Konu", "Ekler")):
            ctk.CTkLabel(info, text=key + ":", font=ctk.CTkFont(weight="bold")).grid(
                row=row, column=0, sticky="nw", padx=(10, 6), pady=2)
            label = ctk.CTkLabel(info, text="", anchor="w", justify="left", wraplength=380)
            label.grid(row=row, column=1, sticky="ew", padx=(0, 10), pady=2)
            self.info_labels[key] = label

        self.warning_label = ctk.CTkLabel(f, text="", anchor="w", justify="left", wraplength=440,
                                          font=ctk.CTkFont(weight="bold"))
        self.warning_label.grid(row=3, column=0, sticky="ew", padx=12, pady=4)

        self.preview_text = ctk.CTkTextbox(f, wrap="word", font=ctk.CTkFont(size=14))
        self.preview_text.grid(row=4, column=0, sticky="nsew", padx=12, pady=(4, 12))
        self.preview_text.configure(state="disabled")

    # ---------- Taslak (otomatik kayıt) ----------

    def _load_draft(self):
        # Boş değer eklenirse CTkEntry'nin gri örnek yazısı kaybolur, o yüzden sadece doluysa ekle.
        self._set_cc(split_emails(self.db.get_setting("cc_list", ""))[0])
        for entry, key in ((self.subject_entry, "draft_subject"),):
            value = self.db.get_setting(key, "")
            if value:
                entry.insert(0, value)
        self.body_text.insert("1.0", self.db.get_setting("draft_body", ""))
        self._set_attachments(parse_attachments(
            self.db.get_setting("draft_attachments") or self.db.get_setting("draft_attachment")))
        self.refresh_signature(update=False)
        self.current_template = self.db.get_setting("current_template") or None
        self._refresh_template_menu()
        self._update_now()

    def save_draft(self):
        mail = self.get_mail()
        self.db.set_setting("draft_subject", mail["subject"])
        self.db.set_setting("draft_body", self._body())
        self.db.set_setting("draft_attachments", dump_attachments(self.attachments))
        self.db.set_setting("cc_list", ", ".join(self.cc_addresses))
        self.db.set_setting("current_template", self.current_template or "")

    # ---------- Dışarıya açık yardımcılar ----------

    def _body(self):
        return self.body_text.get("1.0", "end-1c")

    def get_mail(self):
        return {
            "subject": self.subject_entry.get().strip(),
            "body": self._body().rstrip(),
            "attachments": list(self.attachments),
        }

    def get_cc(self):
        """(geçerli adresler, geçersiz yazılmış olanlar)"""
        typed = self.cc_entry.get().strip()  # yazılmış ama 'Ekle'ye basılmamış adres unutulmasın
        return list(self.cc_addresses), ([f"{typed} ('+ Ekle'ye basılmadı)"] if typed else [])

    def current_preview_contact(self):
        return self.db.get_contact(self.preview_contact_id) if self.preview_contact_id else None

    # ---------- Şablonlar ----------

    def template_state(self):
        """(seçili şablon adı ya da None, editörde kaydedilmemiş değişiklik var mı)"""
        template = self.db.get_template(self.current_template) if self.current_template else None
        if not template:
            return None, True
        mail = self.get_mail()
        modified = ((mail["subject"], mail["body"], list(self.attachments))
                    != (template["subject"].strip(), template["body"].rstrip(), parse_attachments(template["attachment"])))
        return template["name"], modified

    def template_label(self):
        """Kullanıcıya ve kayda yazılacak ad: "Teklif v1", "Teklif v1 (düzenlenmiş)", "Kayıtsız metin"."""
        name, modified = self.template_state()
        if not name:
            return "Kayıtsız metin"
        return f"{name} (düzenlenmiş)" if modified else name

    def _refresh_template_menu(self):
        names = self.db.template_names()
        self.template_menu.configure(values=names or [NO_TEMPLATES])
        if self.current_template in names:
            self.template_menu.set(self.current_template)
        else:
            self.current_template = None
            self.template_menu.set(CHOOSE_TEMPLATE if names else NO_TEMPLATES)
        if hasattr(self.app, "send_tab"):
            self.app.send_tab.refresh_mail_info()

    def _on_template_selected(self, name):
        template = self.db.get_template(name)
        if not template:
            self._refresh_template_menu()
            return
        mail = self.get_mail()
        editor_used = mail["subject"] or mail["body"]
        differs = (mail["subject"], mail["body"]) != (template["subject"].strip(), template["body"].rstrip())
        if editor_used and differs and not messagebox.askyesno(
            "Şablonu yükle", f"Şu anki konu ve metin '{name}' şablonuyla değiştirilecek. Devam edilsin mi?"
        ):
            self._refresh_template_menu()
            return
        self.subject_entry.delete(0, "end")
        self.subject_entry.insert(0, template["subject"])
        self.body_text.delete("1.0", "end")
        self.body_text.insert("1.0", template["body"])
        attachments = parse_attachments(template["attachment"])
        missing = [a for a in attachments if not Path(a).exists()]
        if missing:
            messagebox.showwarning("Ek dosya bulunamadı", "Şablondaki şu ekler bulunamadı, yeniden ekleyin:\n"
                                   + "\n".join(Path(a).name for a in missing))
        self._set_attachments([a for a in attachments if a not in missing])
        self.current_template = name
        self.template_menu.set(name)  # Gönderim sekmesinden seçildiyse burada da görünsün
        self._update_now()

    def save_template(self):
        if not self.current_template:
            self.save_template_as()
            return
        self._store_template(self.current_template)
        messagebox.showinfo("Kaydedildi", f"'{self.current_template}' şablonu güncellendi.")

    def save_template_as(self):
        mail = self.get_mail()
        if not mail["subject"] and not mail["body"]:
            messagebox.showinfo("Şablon", "Önce konu ve metin yazın.")
            return
        name = ctk.CTkInputDialog(text="Şablona bir ad verin:", title="Yeni şablon").get_input()
        name = (name or "").strip()
        if not name:
            return
        if name in self.db.template_names() and not messagebox.askyesno(
            "Şablon var", f"'{name}' adında bir şablon zaten var. Üzerine yazılsın mı?"
        ):
            return
        self._store_template(name)
        messagebox.showinfo("Kaydedildi", f"'{name}' şablonu kaydedildi.")

    def _store_template(self, name):
        mail = self.get_mail()
        self.db.save_template(name, mail["subject"], self._body(), dump_attachments(self.attachments))
        self.current_template = name
        self._refresh_template_menu()
        self.save_draft()

    def delete_template(self):
        if not self.current_template:
            messagebox.showinfo("Şablon sil", "Önce listeden silmek istediğiniz şablonu seçin.")
            return
        if messagebox.askyesno("Şablon sil", f"'{self.current_template}' şablonu silinsin mi?\n(Editördeki metin kalır.)"):
            self.db.delete_template(self.current_template)
            self.current_template = None
            self._refresh_template_menu()
            self.save_draft()

    # ---------- Sabit CC ----------

    def add_cc(self):
        """Kutudaki adres(ler)i listeye ekler. Virgülle birden fazla adres de yapıştırılabilir."""
        valid, invalid = split_emails(self.cc_entry.get())
        known = {a.lower() for a in self.cc_addresses}
        new = [a for a in valid if a.lower() not in known]
        self.cc_entry.delete(0, "end")
        if invalid:
            self.cc_entry.insert(0, " ".join(invalid))
            self.cc_hint.configure(text="Geçersiz adres: " + ", ".join(invalid) + " (düzeltip tekrar Ekle'ye basın)",
                                   text_color=WARN_COLOR)
        self._set_cc(self.cc_addresses + new, keep_hint=bool(invalid))
        self._schedule_update()
        return "break"

    def remove_cc(self, address):
        self._set_cc([a for a in self.cc_addresses if a != address])
        self._schedule_update()

    def _set_cc(self, addresses, keep_hint=False):
        self.cc_addresses = list(addresses)
        for child in self.cc_list_frame.winfo_children():
            child.destroy()
        for i, address in enumerate(self.cc_addresses):
            chip = ctk.CTkFrame(self.cc_list_frame, fg_color=("#e3e9f1", "gray25"), corner_radius=12)
            chip.grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 6), pady=2)
            ctk.CTkLabel(chip, text=address, text_color=("#1a3c6e", "white")).pack(side="left", padx=(10, 2))
            ctk.CTkButton(chip, text="✕", width=22, height=22, fg_color="transparent", text_color=WARN_COLOR,
                          hover_color=("#cfd9e6", "gray35"),
                          command=lambda a=address: self.remove_cc(a)).pack(side="left", padx=(0, 4))
        if not keep_hint:
            count = len(self.cc_addresses)
            self.cc_hint.configure(
                text=(f"{count} adres her maile otomatik CC olarak eklenir." if count else
                      "CC yok. Birden fazla adres ekleyebilirsiniz (her birini yazıp Enter)."),
                text_color="gray40")

    # ---------- Ekler ----------

    def add_attachments(self):
        paths = filedialog.askopenfilenames(
            title="Eklenecek dosyaları seçin (birden fazla seçebilirsiniz)",
            filetypes=[("Tüm dosyalar", "*.*"), ("PDF", "*.pdf"), ("Word", "*.doc *.docx"),
                       ("Excel", "*.xls *.xlsx"), ("PowerPoint", "*.ppt *.pptx"), ("Görsel", "*.png *.jpg *.jpeg")],
        )
        if not paths:
            return
        new = [p for p in dict.fromkeys(paths) if p not in self.attachments]
        bad = [Path(p).name for p in new if blocked(p)]
        if bad:
            messagebox.showerror("Bu dosya türü gönderilemez",
                                 "Gmail şu dosyaları güvenlik nedeniyle engelliyor:\n" + "\n".join(bad)
                                 + "\n\nGerekirse zip yerine Google Drive linki paylaşın.")
            new = [p for p in new if not blocked(p)]
        total = total_size_mb(self.attachments + new)
        if total > MAX_TOTAL_ATTACHMENT_MB:
            messagebox.showerror(
                "Ekler çok büyük",
                f"Eklerin toplamı {total:.1f} MB olur; en fazla {MAX_TOTAL_ATTACHMENT_MB} MB olabilir.\n\n"
                "PDF'leri sıkıştırın (ör. ilovepdf.com → PDF sıkıştır) ya da büyük dosyayı Google Drive'a "
                "yükleyip linkini mail metnine ekleyin.",
            )
            return
        self._set_attachments(self.attachments + new)
        self._schedule_update()

    def remove_attachment(self, path):
        self._set_attachments([p for p in self.attachments if p != path])
        self._schedule_update()

    def _set_attachments(self, paths):
        self.attachments = list(paths)
        for child in self.attachment_list.winfo_children():
            child.destroy()
        for path in self.attachments:
            row = ctk.CTkFrame(self.attachment_list, fg_color=("gray92", "gray22"), corner_radius=6)
            row.pack(fill="x", pady=2)
            missing = not Path(path).exists()
            ctk.CTkLabel(row, text=f"{Path(path).name}   ({_file_size_text(path)})", anchor="w",
                         text_color=WARN_COLOR if missing else ("gray10", "gray90")).pack(side="left", padx=8)
            ctk.CTkButton(row, text="✕", width=28, height=24, fg_color="transparent", text_color=WARN_COLOR,
                          hover_color=("gray85", "gray30"),
                          command=lambda p=path: self.remove_attachment(p)).pack(side="right", padx=4, pady=2)
        if self.attachments:
            self.attachment_total.configure(text=f"{len(self.attachments)} dosya, toplam "
                                                 f"{total_size_mb(self.attachments):.1f} / {MAX_TOTAL_ATTACHMENT_MB} MB")
        else:
            self.attachment_total.configure(text="Ek yok. PDF, Word, Excel, görsel vb. eklenebilir.")

    # ---------- İmza ----------

    def open_signature(self):
        SignatureDialog(self, self.app)

    def refresh_signature(self, update=True):
        signature = load_signature(self.db)
        if signature is None:
            enabled = self.db.get_setting("signature_enabled", "1") == "1"
            self.signature_label.configure(text="İmza tanımlı değil." if enabled else "İmza kapalı.")
        else:
            first_line = signature["text"].splitlines()[0] if signature["text"] else ""
            logo = "  + logo" if signature["logo"] else ""
            self.signature_label.configure(text=f"Her maile eklenir: {first_line}{logo}")
        if update:
            self._update_now()

    # ---------- Alan ekleme ----------

    def _set_field_target(self, target):
        self._field_target = target

    def variables(self):
        """[(değişken adı, önizlemedeki firmanın değeri)]"""
        contact = self.current_preview_contact()
        values = contact_fields(contact) if contact else {}
        names = ["Firma", "Yetkili", "Email"] + self.db.extra_field_names()
        return [(name, values.get(name, "")) for name in names]

    def insert_field(self, name):
        """Panelden tıklanan değişkeni, en son odaklanılan kutuda (konu ya da metin) imlecin yerine ekler."""
        insert_variable(self.subject_entry if self._field_target == "subject" else self.body_text, name)
        self._schedule_update()

    # ---------- Önizleme ----------

    def refresh_contacts(self):
        contacts = self.db.list_contacts()
        self._preview_ids = [c["id"] for c in contacts]
        self._preview_labels = [f"{i}. {c['firma'] or c['email']}" for i, c in enumerate(contacts, start=1)]
        self.contact_menu.configure(values=self._preview_labels or [EMPTY_LIST])
        if self.preview_contact_id not in self._preview_ids:
            self.preview_contact_id = self._preview_ids[0] if self._preview_ids else None
        self._update_now()
        self.variable_panel.refresh()

    def show_contact(self, contact_id):
        if contact_id in self._preview_ids:
            self.preview_contact_id = contact_id
            self._update_now()
            self.variable_panel.refresh()

    def _on_contact_menu(self, label):
        if label in self._preview_labels:
            self.preview_contact_id = self._preview_ids[self._preview_labels.index(label)]
            self._update_now()
            self.variable_panel.refresh()

    def _step_preview(self, step):
        if not self._preview_ids:
            return
        index = self._preview_ids.index(self.preview_contact_id) if self.preview_contact_id in self._preview_ids else 0
        self.preview_contact_id = self._preview_ids[(index + step) % len(self._preview_ids)]
        self._update_now()
        self.variable_panel.refresh()

    def _schedule_update(self):
        if self._update_job:
            self.after_cancel(self._update_job)
        self._update_job = self.after(350, self._update_now)

    def _update_now(self):
        self._update_job = None
        self._update_preview()
        self.save_draft()
        if hasattr(self.app, "send_tab"):
            self.app.send_tab.refresh_summary()

    def _update_preview(self):
        mail = self.get_mail()
        cc_valid, cc_invalid = self.get_cc()
        contact = self.current_preview_contact()
        warnings = []

        if contact:
            self.contact_menu.set(self._preview_labels[self._preview_ids.index(contact["id"])])
            subject, body, missing = render_mail(mail["subject"], mail["body"], contact)
            to_text = f"{contact['yetkili']} <{contact['email']}>" if contact["yetkili"] else contact["email"]
            known = {normalize_key(k) for k in contact_fields(contact)}
            unknown = [m for m in missing if normalize_key(m) not in known]
            empty = [m for m in missing if normalize_key(m) in known]
            if unknown:
                warnings.append("Listede olmayan alan: " + ", ".join("{{" + m + "}}" for m in unknown)
                                + "  (yazım hatası olabilir)")
            if empty:
                warnings.append("Bu firmada boş olan alan: " + ", ".join("{{" + m + "}}" for m in empty))
            if missing:
                warnings.append("Bu haliyle bu firmaya mail GÖNDERİLMEZ, 'Hata: Eksik alan' olarak işaretlenir.")
        else:
            self.contact_menu.set(EMPTY_LIST)
            subject, body = mail["subject"], mail["body"]
            to_text = "(Önce 'Firma Listesi' sekmesinden liste içe aktarın)"

        if not mail["subject"]:
            warnings.append("Konu boş.")
        if not mail["body"]:
            warnings.append("Mail metni boş.")
        if cc_invalid:
            warnings.append("Geçersiz CC adresi: " + ", ".join(cc_invalid))
        signature = load_signature(self.db)
        warnings += attachment_problems(self.attachments) + signature_problems(signature)

        self.info_labels["Kime"].configure(text=to_text)
        self.info_labels["CC"].configure(text=", ".join(cc_valid) or "(yok)")
        self.info_labels["Konu"].configure(text=subject or "(boş)")
        self.info_labels["Ekler"].configure(
            text=", ".join(Path(a).name for a in self.attachments) if self.attachments else "(yok)"
        )
        if warnings:
            self.warning_label.configure(text="⚠ " + "\n⚠ ".join(warnings), text_color=WARN_COLOR)
        elif contact:
            self.warning_label.configure(text="✓ Bu firma için mail hazır.", text_color=OK_COLOR)
        else:
            self.warning_label.configure(text="")

        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", preview_body(body, signature))
        self.preview_text.configure(state="disabled")
