"""Sponsorluk Mail Gönderici - giriş noktası."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from tkinter import Tk, messagebox

import customtkinter as ctk

from config import APP_NAME, CREDENTIALS_FILE, DB_FILE, LOG_FILE, TOKEN_FILE


def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # Google kütüphanelerinin ayrıntılı çıktısını kısalt.
    logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)


def main():
    setup_logging()
    log = logging.getLogger("main")
    log.info("Uygulama başlatıldı")
    try:
        # Ağır Google kütüphaneleri logging kurulduktan sonra yüklensin ki hatalar log'a düşsün.
        from database import Database
        from gmail_client import GmailClient
        from ui.app import App

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")
        app = App(Database(DB_FILE), GmailClient(CREDENTIALS_FILE, TOKEN_FILE))
        app.mainloop()
    except Exception:
        log.exception("Uygulama başlatılamadı")
        root = Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, f"Uygulama başlatılamadı. Ayrıntılar şu dosyada:\n{LOG_FILE}")
        root.destroy()
        sys.exit(1)


if __name__ == "__main__":
    main()
