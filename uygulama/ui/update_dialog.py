"""Güncelleme penceresi: yeni sürümün notları, indirme ilerlemesi, kurulum."""
import logging
import webbrowser
from tkinter import messagebox

import customtkinter as ctk

import updater
from config import APP_VERSION

log = logging.getLogger(__name__)


class UpdateDialog(ctk.CTkToplevel):
    def __init__(self, master, app, info):
        super().__init__(master)
        self.app = app
        self.info = info
        self.title("Güncelleme")
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())

        ctk.CTkLabel(self, text=f"Yeni sürüm hazır: v{info['version']}", font=ctk.CTkFont(size=17, weight="bold")).pack(
            anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(self, text=f"Şu an kullandığınız: v{APP_VERSION}. Verileriniz (liste, şablonlar, imza, Gmail "
                                "oturumu) güncellemeden etkilenmez.",
                     text_color="gray35", wraplength=520, justify="left").pack(anchor="w", padx=20)
        ctk.CTkLabel(self, text="Neler yeni:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=20, pady=(12, 2))
        notes = ctk.CTkTextbox(self, width=520, height=200, wrap="word")
        notes.pack(padx=20)
        notes.insert("1.0", info["notes"] or "(Sürüm notu yok)")
        notes.configure(state="disabled")

        self.status = ctk.CTkLabel(self, text="", text_color="gray35", anchor="w")
        self.status.pack(fill="x", padx=20, pady=(10, 0))
        self.progress = ctk.CTkProgressBar(self, width=520)
        self.progress.set(0)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=20, pady=16)
        self.update_button = ctk.CTkButton(buttons, text="Şimdi güncelle", width=140, command=self.start,
                                           fg_color="#1e8e3e", hover_color="#17712f")
        self.update_button.pack(side="right")
        ctk.CTkButton(buttons, text="Sonra", width=90, command=self.destroy, fg_color="#5f6b7a",
                      hover_color="#4a5462").pack(side="right", padx=8)
        ctk.CTkButton(buttons, text="GitHub sayfası", width=120, command=lambda: webbrowser.open(info["page"]),
                      fg_color="transparent", text_color=("#1a3c6e", "#9ec3ff"), hover_color=("gray90", "gray25")
                      ).pack(side="left")
        self.after(150, self._bring_to_front)

    def _bring_to_front(self):
        self.lift()
        self.focus_force()
        self.grab_set()

    def start(self):
        if not updater.can_self_update():
            webbrowser.open(self.info["page"])
            return
        if self.app.busy:
            messagebox.showwarning("Gönderim sürüyor", "Gönderim bitince ya da durdurunca güncelleyin.", parent=self)
            return
        self.update_button.configure(state="disabled", text="İndiriliyor...")
        self.progress.pack(padx=20, after=self.status)

        def progress(done, total):
            def show():
                if self.winfo_exists():
                    self.progress.set(done / total if total else 0)
                    self.status.configure(text=f"İndiriliyor: {done / 1024 / 1024:.1f} MB"
                                               + (f" / {total / 1024 / 1024:.1f} MB" if total else ""))
            self.app.call_in_ui(show)

        def failed(message):
            if self.winfo_exists():
                self.update_button.configure(state="normal", text="Tekrar dene")
                self.status.configure(text=message, text_color="#c5221f")

        self.app.run_background(lambda: updater.download(self.info, progress), on_done=self._install,
                                on_error=failed)

    def _install(self, staged_dir):
        self.status.configure(text="Kuruluyor... Uygulama kapanıp birkaç saniye içinde yeni sürümle açılacak.")
        self.update()
        try:
            updater.apply_and_restart(staged_dir)
        except OSError:
            log.exception("Güncelleme başlatılamadı")
            self.status.configure(text="Güncelleme başlatılamadı. Ayrıntılar uygulama.log dosyasında.",
                                  text_color="#c5221f")
            self.update_button.configure(state="normal", text="Tekrar dene")
            return
        self.app.close_for_update()
