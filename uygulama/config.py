"""Uygulama genelindeki sabitler ve dosya yolları."""
import sys
from pathlib import Path

APP_NAME = "Sponsorluk Mail Gönderici"
APP_VERSION = "1.6.3"
# Güncellemelerin kontrol edildiği GitHub deposu (sürümler: https://github.com/<depo>/releases)
GITHUB_REPO = "AloneDark7658/sponsorluk-mail"

# Klasör düzeni:
#   mail yollama/
#     Uygulamayi Ac.bat
#     uygulama/   <- kod ve uygulamanın kendi dosyaları (ikonlar)
#     veriler/    <- veritabanı, Gmail oturumu, credentials.json, log, imza logosu
if getattr(sys, "frozen", False):
    # .exe: exe ana klasörde durur, ikonlar exe'nin içine paketlenir.
    ROOT_DIR = Path(sys.executable).resolve().parent
    ASSET_DIR = Path(getattr(sys, "_MEIPASS", ROOT_DIR))
else:
    ASSET_DIR = Path(__file__).resolve().parent
    ROOT_DIR = ASSET_DIR.parent

DATA_DIR = ROOT_DIR / "veriler"
DATA_DIR.mkdir(exist_ok=True)
ICON_DIR = ASSET_DIR / "imza_ikonlar"

# Google'ın uygulamayı tanıması için "istemci kimliği" (şifre değildir; herkes kendi Gmail'iyle giriş yapar).
# Uygulamanın içinde gelir; 'veriler' klasörüne ayrı bir credentials.json konursa o kullanılır.
BUNDLED_CREDENTIALS = ASSET_DIR / "google_istemci.json"
_custom_credentials = DATA_DIR / "credentials.json"
CREDENTIALS_FILE = _custom_credentials if _custom_credentials.exists() else BUNDLED_CREDENTIALS
TOKEN_FILE = DATA_DIR / "token.json"
DB_FILE = DATA_DIR / "veriler.db"
LOG_FILE = DATA_DIR / "uygulama.log"

DEFAULT_DELAY_SECONDS = 5
DEFAULT_DAILY_LIMIT = 200  # tavsiye edilen
MAX_DAILY_LIMIT = 500  # Gmail'in günlük alıcı sınırı; ayarda daha fazlası kabul edilmez
# Gmail toplam ~25 MB'a izin veriyor; ekler gönderimde ~%33 büyüdüğü için ham boyut sınırı daha düşük.
MAX_TOTAL_ATTACHMENT_MB = 18
# Gmail'in güvenlik nedeniyle reddettiği dosya türleri
BLOCKED_EXTENSIONS = {
    ".ade", ".adp", ".apk", ".appx", ".bat", ".cab", ".chm", ".cmd", ".com", ".cpl", ".dll", ".dmg", ".exe",
    ".hta", ".ins", ".iso", ".isp", ".jar", ".js", ".jse", ".lib", ".lnk", ".mde", ".msc", ".msi", ".msix",
    ".msp", ".mst", ".nsh", ".pif", ".ps1", ".scr", ".sct", ".shb", ".sys", ".vb", ".vbe", ".vbs", ".vhd",
    ".vxd", ".wsc", ".wsf", ".wsh",
}
