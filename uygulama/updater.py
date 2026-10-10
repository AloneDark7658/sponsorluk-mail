"""Uygulama içinden güncelleme (G-Helper benzeri).

1. GitHub'daki son sürümü sorar (https://github.com/<GITHUB_REPO>/releases/latest).
2. Daha yeniyse 'SponsorlukMail-<sürüm>.zip' paketini indirip geçici klasöre açar ve doğrular.
3. Küçük bir yardımcı betik başlatır; betik uygulamanın kapanmasını bekler, 'uygulama' klasörünü
   yedekleyip yenisini koyar, gerekirse paketleri kurar ve uygulamayı yeniden açar.
   Bir adım başarısız olursa yedekten geri döner. 'veriler' klasörüne hiç dokunulmaz.
"""
import json
import logging
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

from config import APP_VERSION, ASSET_DIR, DATA_DIR, GITHUB_REPO, ROOT_DIR

log = logging.getLogger(__name__)

API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{GITHUB_REPO}/releases"
PACKAGE_PREFIX = "SponsorlukMail-"
BACKUP_SUFFIX = ".eski"
HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "SponsorlukMail-Guncelleme"}


class UpdateError(Exception):
    pass


def can_self_update():
    """Kaynak koddan (pythonw main.py) çalışıyorsa kendini güncelleyebilir; .exe sürümünde güncelleme sayfası açılır."""
    return not getattr(sys, "frozen", False)


def parse_version(text):
    numbers = [int(n) for n in re.findall(r"\d+", text or "")[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def check_latest(timeout=10):
    """Daha yeni sürüm varsa {'version', 'notes', 'url', 'size', 'page'} döner, yoksa None."""
    request = urllib.request.Request(API_URL, headers=HEADERS)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:  # henüz hiç sürüm yayınlanmamış
            return None
        raise UpdateError(f"GitHub'a ulaşılamadı ({exc.code}).") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Güncelleme kontrolü yapılamadı (internet bağlantısı?).") from exc

    version = (data.get("tag_name") or "").lstrip("vV")
    if parse_version(version) <= parse_version(APP_VERSION):
        return None
    package = next((a for a in data.get("assets", [])
                    if a["name"].startswith(PACKAGE_PREFIX) and a["name"].endswith(".zip")), None)
    if not package:
        log.warning("Sürüm %s bulundu ama güncelleme paketi yok", version)
        return None
    return {"version": version, "notes": (data.get("body") or "").strip(), "url": package["browser_download_url"],
            "size": package.get("size") or 0, "page": data.get("html_url") or RELEASES_URL}


def download(info, progress=None):
    """Paketi indirip açar, doğrular. Yeni kodun bulunduğu klasörü döner."""
    work = Path(tempfile.mkdtemp(prefix="sponsorluk_guncelleme_"))
    archive = work / "paket.zip"
    request = urllib.request.Request(info["url"], headers={"User-Agent": HEADERS["User-Agent"]})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, open(archive, "wb") as out:
            total = int(response.headers.get("Content-Length") or info.get("size") or 0)
            done = 0
            while chunk := response.read(64 * 1024):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Güncelleme indirilemedi. İnternet bağlantınızı kontrol edip tekrar deneyin.") from exc

    target = work / "yeni"
    try:
        with zipfile.ZipFile(archive) as package:
            package.extractall(target)
    except zipfile.BadZipFile as exc:
        raise UpdateError("İndirilen güncelleme paketi bozuk. Tekrar deneyin.") from exc

    # Paket 'main.py' kökte olacak şekilde hazırlanır; tek klasör içindeyse onu kullan.
    if not (target / "main.py").exists():
        inner = [p for p in target.iterdir() if p.is_dir() and (p / "main.py").exists()]
        if len(inner) != 1:
            raise UpdateError("Güncelleme paketi beklenen yapıda değil.")
        target = inner[0]
    if not (target / "config.py").exists():
        raise UpdateError("Güncelleme paketi eksik.")
    return target


HELPER = r'''
import ctypes, os, shutil, subprocess, sys, time
pid, app_dir, staged, python, pythonw, root, log_path = sys.argv[1:8]
pid = int(pid)
backup = app_dir + "{backup_suffix}"
NO_WINDOW = 0x08000000

def log(message):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")

def retry(action, what, attempts=30):
    # OneDrive gibi programlar dosyaları kısa süre kilitleyebilir; birkaç kez dene.
    for i in range(attempts):
        try:
            return action()
        except OSError as exc:
            if i == attempts - 1:
                raise
            time.sleep(1)

try:
    handle = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, 60000)
        ctypes.windll.kernel32.CloseHandle(handle)
    time.sleep(1)
    log("Güncelleme başladı")
    if os.path.exists(backup):
        retry(lambda: shutil.rmtree(backup), "eski yedek silme")
    retry(lambda: os.rename(app_dir, backup), "yedekleme")
    try:
        retry(lambda: shutil.copytree(staged, app_dir), "yeni sürümü kopyalama")
    except Exception as exc:
        log("Kopyalama başarısız, eski sürüme dönülüyor: %r" % exc)
        if os.path.exists(app_dir):
            shutil.rmtree(app_dir, ignore_errors=True)
        retry(lambda: os.rename(backup, app_dir), "geri alma")
        raise
    requirements = os.path.join(app_dir, "requirements.txt")
    if os.path.exists(requirements):
        result = subprocess.run([python, "-m", "pip", "install", "-q", "--disable-pip-version-check", "-r",
                                 requirements], creationflags=NO_WINDOW, capture_output=True, text=True)
        if result.returncode:
            log("Paket kurulumu uyarısı: " + (result.stderr or "")[-500:])
    log("Güncelleme tamam")
except Exception as exc:
    log("Güncelleme başarısız: %r" % exc)
finally:
    subprocess.Popen([pythonw, os.path.join(app_dir, "main.py")], cwd=root,
                     creationflags=0x00000008 | NO_WINDOW)  # DETACHED_PROCESS
'''


def apply_and_restart(staged_dir):
    """Yardımcı betiği başlatır. Çağıran taraf hemen ardından uygulamayı kapatmalı."""
    executable = Path(sys.executable)
    python = executable.with_name("python.exe")
    pythonw = executable.with_name("pythonw.exe")
    if not python.exists():
        python = executable
    if not pythonw.exists():
        pythonw = executable
    helper = Path(staged_dir).parent / "guncelle.py"
    helper.write_text(HELPER.replace("{backup_suffix}", BACKUP_SUFFIX), encoding="utf-8")
    import os
    args = [str(python), str(helper), str(os.getpid()), str(ASSET_DIR), str(staged_dir), str(python), str(pythonw),
            str(ROOT_DIR), str(DATA_DIR / "guncelleme.log")]
    subprocess.Popen(args, cwd=str(Path(staged_dir).parent), creationflags=0x08000000 | 0x00000008)
    log.info("Güncelleme yardımcısı başlatıldı: %s", staged_dir)


def cleanup_backup():
    """Yeni sürüm sorunsuz açıldıysa önceki sürümün yedeğini siler."""
    backup = Path(str(ASSET_DIR) + BACKUP_SUFFIX)
    if backup.exists():
        import shutil
        shutil.rmtree(backup, ignore_errors=True)
        log.info("Önceki sürümün yedeği silindi")
