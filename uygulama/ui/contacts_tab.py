"""Firma listesi sekmesi: içe/dışa aktarma ve durum tablosu."""
import logging
import os
import webbrowser
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import customtkinter as ctk

from database import ERROR, PENDING, REPLY_AUTO, REPLY_BOUNCED, REPLY_YES, SENT, SERVER, TIME_FORMAT, display_time
from importer import ImportFailed, create_template_xlsx, export_csv, read_contacts
from replies import awaiting_reply, has_reply
from schedule import describe
from ui.contact_dialog import ContactDialog

log = logging.getLogger(__name__)

ALL = "Tümü"
REPLIED = "Cevap geldi"
WAITING = "Cevapsız"
# Satır rengi: önce cevap durumu, yoksa gönderim durumu
ROW_COLORS = {PENDING: "#333333", SENT: "#1e8e3e", ERROR: "#c5221f", SERVER: "#7b3fb5",
              "replied": "#1a56c4", "bounced": "#b05a00"}
SERVER_BLOCK = ("Seçtiklerinizin arasında Google'da planlı firmalar var. Bunlar Google sunucusundan gidecek.\n"
                "Değiştirmek için önce Gönderim sekmesinden 'Google planını iptal et'e basın.")
COLUMNS = [
    ("no", "#", 40, "center"),
    ("firma", "Firma", 180, "w"),
    ("yetkili", "Yetkili", 130, "w"),
    ("email", "Email", 200, "w"),
    ("durum", "Durum", 95, "center"),
    ("detay", "Tarih / Hata mesajı", 150, "w"),
    ("cevap", "Cevap", 185, "w"),
    ("gmail", "", 95, "center"),
    ("duzenle", "", 90, "center"),
]
COLUMN_IDS = {key: f"#{i}" for i, (key, *_rest) in enumerate(COLUMNS, start=1)}  # Treeview sütun kimlikleri
EDIT_TEXT = "✎ Düzenle"
GMAIL_TEXT = "Gmail'de aç ↗"


def reply_text(c):
    """Cevap sütununda görünecek metin."""
    if c["status"] != SENT:
        return ""
    reminders = c.get("reminder_count") or 0
    suffix = f"  •  {reminders} hatırlatma" if reminders else ""
    if c.get("manual_reply"):
        return "✓ Cevap alındı (elle)" + suffix
    status = c.get("reply_status")
    if status == REPLY_YES:
        return f"✓ Cevap geldi ({display_time(c.get('reply_at'))[:-6]})" + suffix
    if status == REPLY_BOUNCED:
        return "✗ Ulaşmadı (adres hatalı?)"
    if status == REPLY_AUTO:
        return "Otomatik yanıt" + suffix
    if not c.get("thread_id"):
        return "Takip edilmiyor"
    return "Cevap yok" + suffix


def row_tag(c):
    if c["status"] == SENT and has_reply(c):
        return "replied"
    if c["status"] == SENT and c.get("reply_status") == REPLY_BOUNCED:
        return "bounced"
    return c["status"]


def _short_list(items, limit=10):
    items = list(items)
    text = ", ".join(items[:limit])
    if len(items) > limit:
        text += f" ... ve {len(items) - limit} tane daha"
    return text


class ContactsTab(ctk.CTkFrame):
    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.db = app.db
        self._filter = ALL

        # Üst araç çubuğu
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            bar, text="+ Firma ekle", width=110, height=34, command=lambda: self.open_editor(None),
            font=ctk.CTkFont(size=13, weight="bold"), fg_color="#1a3c6e", hover_color="#12294c",
        ).pack(side="left", padx=(0, 8))
        self.import_button = ctk.CTkButton(
            bar, text="İçe aktar (Excel / CSV)", width=190, height=34, command=self.import_file,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.import_button.pack(side="left")
        ctk.CTkButton(
            bar, text="CSV dışa aktar", width=120, height=34, command=self.export_file,
            fg_color="#5f6b7a", hover_color="#4a5462",
        ).pack(side="left", padx=8)
        ctk.CTkButton(
            bar, text="Excel şablonu indir", width=140, height=34, command=self.download_template,
            fg_color="#1e8e3e", hover_color="#17712f",
        ).pack(side="left")

        filter_bar = ctk.CTkFrame(self, fg_color="transparent")
        filter_bar.pack(fill="x", pady=(0, 6))
        self.search_entry = ctk.CTkEntry(filter_bar, placeholder_text="Ara: firma, yetkili, email", width=220)
        self.search_entry.pack(side="left")
        self.search_entry.bind("<KeyRelease>", lambda e: self.refresh())
        self.filter_buttons = ctk.CTkSegmentedButton(
            filter_bar, values=[ALL, PENDING, SERVER, SENT, ERROR, REPLIED, WAITING], command=self._on_filter
        )
        self.filter_buttons.set(ALL)
        self.filter_buttons.pack(side="left", padx=8)
        ctk.CTkLabel(
            filter_bar,
            text="Gmail'de aç ↗: konuşmayı (gönderilen + gelen cevaplar) açar   •   ✎ Düzenle   •   Çift tık: önizle",
            text_color="gray35", anchor="e",
        ).pack(side="right")

        # Tablo
        table_frame = ctk.CTkFrame(self)
        table_frame.pack(fill="both", expand=True)
        self._setup_style()
        self.tree = ttk.Treeview(
            table_frame, columns=[c[0] for c in COLUMNS], show="headings", style="Firma.Treeview",
            selectmode="extended",
        )
        for key, title, width, anchor in COLUMNS:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=int(width * self._scale), anchor=anchor,
                             stretch=key in ("firma", "email", "detay", "cevap"))
        for tag, color in ROW_COLORS.items():
            self.tree.tag_configure(tag, foreground=color)
        yscroll = ctk.CTkScrollbar(table_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.pack(side="right", fill="y", pady=4)
        self.tree.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<ButtonRelease-1>", self._on_click)
        self.tree.bind("<Motion>", self._on_motion)
        self.tree.bind("<Delete>", lambda e: self.delete_selected())

        # Alt bar
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", pady=(8, 0))
        self.count_label = ctk.CTkLabel(bottom, text="", font=ctk.CTkFont(size=13, weight="bold"))
        self.count_label.pack(side="left")
        self.action_buttons = [
            ctk.CTkButton(bottom, text="Tüm listeyi sil", width=120, command=self.delete_all,
                          fg_color="#c5221f", hover_color="#a31b17"),
            ctk.CTkButton(bottom, text="Seçilileri sil", width=110, command=self.delete_selected,
                          fg_color="#5f6b7a", hover_color="#4a5462"),
            ctk.CTkButton(bottom, text="Seçilileri 'Bekliyor' yap", width=170, command=self.reset_selected,
                          fg_color="#5f6b7a", hover_color="#4a5462"),
            ctk.CTkButton(bottom, text="Hatalıları tekrar dene", width=160, command=self.retry_errors,
                          fg_color="#e37400", hover_color="#b85e00"),
        ]
        for button in self.action_buttons:
            button.pack(side="right", padx=(8, 0))

    def _setup_style(self):
        try:
            scale = self._get_widget_scaling()
        except Exception:
            scale = 1.0
        self._scale = scale
        # Negatif boyut = piksel. Nokta cinsinden verilince DPI ölçeklemesiyle boyut tutarsız çıkabiliyor.
        self._row_font = tkfont.Font(family="Segoe UI", size=-int(14 * scale))
        self._heading_font = tkfont.Font(family="Segoe UI", size=-int(14 * scale), weight="bold")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Firma.Treeview", rowheight=int(30 * scale), font=self._row_font,
            background="white", fieldbackground="white", borderwidth=0,
        )
        style.configure(
            "Firma.Treeview.Heading", font=self._heading_font, background="#e3e9f1",
            relief="flat", padding=(4, 6),
        )
        style.map("Firma.Treeview", background=[("selected", "#1f6aa5")], foreground=[("selected", "white")])
        style.map("Firma.Treeview.Heading", background=[("active", "#d3dce8")])

    # ---------- Tablo ----------

    @staticmethod
    def _row_values(number, c):
        if c["status"] == SENT:
            detail = display_time(c["sent_at"])
        elif c["status"] == SERVER:
            try:
                detail = "Gidecek: " + describe(datetime.strptime(c["scheduled_for"], TIME_FORMAT))
            except (TypeError, ValueError):
                detail = ""
        else:
            detail = c["error"] or ""
        gmail = GMAIL_TEXT if c.get("thread_id") else ""
        return (number, c["firma"], c["yetkili"], c["email"], c["status"], detail, reply_text(c), gmail, EDIT_TEXT)

    def _matches_filter(self, c):
        if self._filter == ALL:
            return True
        if self._filter == REPLIED:
            return c["status"] == SENT and has_reply(c)
        if self._filter == WAITING:
            return awaiting_reply(c)
        return c["status"] == self._filter

    def refresh(self):
        contacts = self.db.list_contacts()
        self._numbers = {c["id"]: i for i, c in enumerate(contacts, start=1)}
        query = self.search_entry.get().strip().casefold()
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for c in contacts:
            if not self._matches_filter(c):
                continue
            if query and query not in f"{c['firma']} {c['yetkili']} {c['email']}".casefold():
                continue
            iid = str(c["id"])
            self.tree.insert("", "end", iid=iid, values=self._row_values(self._numbers[c["id"]], c), tags=(row_tag(c),))
        keep = [iid for iid in selected if self.tree.exists(iid)]
        if keep:
            self.tree.selection_set(keep)
        self._update_counts()

    def update_contact_row(self, contact_id):
        """Gönderim sırasında sadece değişen satırı günceller."""
        contact = self.db.get_contact(contact_id)
        iid = str(contact_id)
        if contact and self.tree.exists(iid):
            number = self._numbers.get(contact_id, "")
            self.tree.item(iid, values=self._row_values(number, contact), tags=(row_tag(contact),))
            self.tree.see(iid)
        self._update_counts()

    def _update_counts(self):
        c = self.db.counts()
        replied = sum(1 for x in self.db.list_contacts() if x["status"] == SENT and has_reply(x))
        self.count_label.configure(
            text=f"Toplam {c['total']}   •   Bekliyor {c[PENDING]}   •   Google'da {c[SERVER]}   •   "
                 f"Gönderildi {c[SENT]}   •   "
                 f"Hata {c[ERROR]}   •   Cevap gelen {replied}"
        )

    def _selected_ids(self):
        return [int(iid) for iid in self.tree.selection()]

    def _on_filter(self, value):
        self._filter = value
        self.refresh()

    def show_filter(self, value):
        self.filter_buttons.set(value)
        self._on_filter(value)

    def _on_select(self, _event):
        ids = self._selected_ids()
        if len(ids) == 1:
            self.app.select_contact(ids[0])

    def _clicked_column(self, event):
        """Tıklanan hücre Düzenle ya da Gmail sütunuysa onun adını döner."""
        if self.tree.identify_region(event.x, event.y) != "cell" or not self.tree.identify_row(event.y):
            return None
        column = self.tree.identify_column(event.x)
        if column == COLUMN_IDS["duzenle"]:
            return "duzenle"
        if column == COLUMN_IDS["gmail"] and self.tree.set(self.tree.identify_row(event.y), "gmail"):
            return "gmail"
        return None

    def _is_edit_cell(self, event):
        return self._clicked_column(event) == "duzenle"

    def _on_click(self, event):
        column = self._clicked_column(event)
        if column == "duzenle":
            self.open_editor(int(self.tree.identify_row(event.y)))
        elif column == "gmail":
            self.open_in_gmail(int(self.tree.identify_row(event.y)))

    def _on_motion(self, event):
        self.tree.configure(cursor="hand2" if self._clicked_column(event) else "")

    def open_in_gmail(self, contact_id):
        contact = self.db.get_contact(contact_id)
        if contact and contact.get("thread_id"):
            webbrowser.open(self.app.gmail.thread_link(contact["thread_id"]))

    def open_editor(self, contact_id):
        contact = self.db.get_contact(contact_id) if contact_id else None
        if contact_id and not contact:
            self.refresh()
            return
        ContactDialog(self, self.app, contact)

    def _on_double_click(self, event):
        if self._clicked_column(event):
            return
        iid = self.tree.identify_row(event.y)
        if iid:
            self.app.show_preview(int(iid))

    def set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.import_button.configure(state=state)
        for button in self.action_buttons:
            button.configure(state=state)

    # ---------- İçe / dışa aktarma ----------

    def import_file(self):
        path = filedialog.askopenfilename(
            title="Firma listesini seçin",
            filetypes=[("Excel veya CSV", "*.xlsx *.xlsm *.csv"), ("Tüm dosyalar", "*.*")],
        )
        if not path:
            return
        try:
            result = read_contacts(path)
        except ImportFailed as exc:
            messagebox.showerror("İçe aktarılamadı", str(exc))
            return
        except Exception:
            log.exception("İçe aktarma hatası: %s", path)
            messagebox.showerror("İçe aktarılamadı", "Dosya okunamadı. Ayrıntılar uygulama.log dosyasında.")
            return

        if result.missing_columns:
            messagebox.showerror(
                "Eksik sütun",
                "Dosyada şu zorunlu sütun(lar) bulunamadı: " + ", ".join(result.missing_columns) + "\n\n"
                "İlk satırda sütun başlıkları olmalı: Email, Firma, Yetkili (diğer sütunlar serbest).\n\n"
                "Dosyada bulunan başlıklar: " + (", ".join(result.headers) or "(yok)"),
            )
            return

        added, existing = self.db.add_contacts(result.rows)
        log.info("İçe aktarıldı: %s (%d eklendi, %d zaten vardı)", path, added, len(existing))
        lines = [f"{added} firma listeye eklendi."]
        warnings = False
        if existing:
            warnings = True
            lines.append(f"\nZaten listede olduğu için eklenmeyen {len(existing)} adres:\n{_short_list(existing)}")
        if result.duplicates_in_file:
            warnings = True
            lines.append(
                f"\nDosyada iki kez geçen {len(result.duplicates_in_file)} adres (sadece ilki alındı):\n"
                f"{_short_list(result.duplicates_in_file)}"
            )
        if result.invalid_emails:
            warnings = True
            items = [f"satır {no}: {email}" for no, email in result.invalid_emails]
            lines.append(f"\nEmail adresi geçersiz olduğu için atlanan {len(items)} satır:\n{_short_list(items)}")
        if result.skipped_examples:
            lines.append(f"\nŞablondaki {result.skipped_examples} örnek satır (@example.com) atlandı.")
        fields = ["Firma", "Yetkili", "Email"] + [h for h in self.db.extra_field_names()]
        lines.append("\nMail metninde kullanabileceğiniz alanlar:\n" + ", ".join("{{" + f + "}}" for f in fields))

        self.app.contacts_changed()
        (messagebox.showwarning if warnings else messagebox.showinfo)("İçe aktarma tamamlandı", "\n".join(lines))

    def download_template(self):
        path = filedialog.asksaveasfilename(
            title="Excel şablonunu kaydet", defaultextension=".xlsx",
            initialfile="firma_listesi_sablonu.xlsx", filetypes=[("Excel dosyası", "*.xlsx")],
        )
        if not path:
            return
        try:
            create_template_xlsx(path)
        except PermissionError:
            messagebox.showerror("Kaydedilemedi", "Dosya başka bir programda (Excel?) açık. Kapatıp tekrar deneyin.")
            return
        except OSError:
            log.exception("Şablon oluşturulamadı")
            messagebox.showerror("Kaydedilemedi", "Dosya kaydedilemedi. Ayrıntılar uygulama.log dosyasında.")
            return
        if messagebox.askyesno(
            "Şablon kaydedildi",
            f"Şablon kaydedildi:\n{path}\n\nGri örnek satırları silip firmalarınızı yazın, sonra "
            "'Dosyadan içe aktar' ile yükleyin.\n\nDosya şimdi açılsın mı?",
        ):
            try:
                os.startfile(path)
            except OSError:
                log.exception("Şablon açılamadı")

    def export_file(self):
        contacts = self.db.list_contacts()
        if not contacts:
            messagebox.showinfo("Dışa aktar", "Liste boş.")
            return
        path = filedialog.asksaveasfilename(
            title="Listeyi kaydet", defaultextension=".csv",
            initialfile=f"firma_listesi_{datetime.now():%Y-%m-%d}.csv",
            filetypes=[("CSV dosyası", "*.csv")],
        )
        if not path:
            return
        try:
            export_csv(path, contacts, self.db.extra_field_names())
        except PermissionError:
            messagebox.showerror("Kaydedilemedi", "Dosya başka bir programda (Excel?) açık. Kapatıp tekrar deneyin.")
            return
        except OSError:
            log.exception("Dışa aktarma hatası")
            messagebox.showerror("Kaydedilemedi", "Dosya kaydedilemedi. Ayrıntılar uygulama.log dosyasında.")
            return
        messagebox.showinfo("Dışa aktarıldı", f"{len(contacts)} firma kaydedildi:\n{path}")

    # ---------- Liste işlemleri ----------

    def _has_server_planned(self, ids):
        return any(c and c["status"] == SERVER for c in (self.db.get_contact(i) for i in ids))

    def retry_errors(self):
        count = self.db.counts()[ERROR]
        if not count:
            messagebox.showinfo("Hatalıları tekrar dene", "Hatalı firma yok.")
            return
        self.db.retry_errors()
        self.app.contacts_changed()
        messagebox.showinfo(
            "Hatalıları tekrar dene",
            f"{count} firma tekrar 'Bekliyor' yapıldı. Gönderim sekmesinden gönderebilirsiniz.\n"
            "(Hata 'Eksik alan' ise önce listedeki bilgiyi düzeltin.)",
        )

    def reset_selected(self):
        ids = self._selected_ids()
        if not ids:
            messagebox.showinfo("Seçim yok", "Önce tablodan firma seçin (Ctrl veya Shift ile birden fazla seçebilirsiniz).")
            return
        if self._has_server_planned(ids):
            messagebox.showwarning("Google'da planlı", SERVER_BLOCK)
            return
        already_sent = [c for c in (self.db.get_contact(i) for i in ids) if c and c["status"] == SENT]
        if already_sent and not messagebox.askyesno(
            "Tekrar gönderilecek",
            f"Seçtiklerinizden {len(already_sent)} firmaya daha önce mail gönderildi.\n"
            "'Bekliyor' yaparsanız bir sonraki gönderimde bu firmalara TEKRAR mail gider. Emin misiniz?",
        ):
            return
        self.db.set_pending(ids)
        self.app.contacts_changed()

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids or self.app.busy:
            return
        if self._has_server_planned(ids):
            messagebox.showwarning("Google'da planlı", SERVER_BLOCK)
            return
        if messagebox.askyesno("Sil", f"Seçili {len(ids)} firma listeden silinsin mi?"):
            self.db.delete_contacts(ids)
            self.app.contacts_changed()

    def delete_all(self):
        total = self.db.counts()["total"]
        if not total:
            return
        if self.db.counts()[SERVER]:
            messagebox.showwarning("Google'da planlı", SERVER_BLOCK)
            return
        if messagebox.askyesno(
            "Tüm listeyi sil",
            f"Listedeki {total} firmanın TAMAMI ve gönderim durumları silinecek.\n"
            "İsterseniz önce 'CSV olarak dışa aktar' ile yedek alın.\n\nSilinsin mi?",
            icon="warning",
        ):
            self.db.delete_all_contacts()
            self.app.contacts_changed()
