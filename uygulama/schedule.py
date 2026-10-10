"""Gönderim saatleri: mailler yalnızca belirlenen saatlerde (ör. 09:00 ve 13:30) gider.

Gmail API'de planlı gönderim olmadığı için zamanlamayı uygulama yapar: plan kaydedilir,
saat gelince (uygulama açıksa) gönderim kendiliğinden başlar.
"""
import ctypes
import logging
import re
import sys
from datetime import datetime, time, timedelta

log = logging.getLogger(__name__)

DEFAULT_TIMES = "09:30, 13:30"
# Saat geçtikten sonra bu süre içinde uygulama açılırsa gönderim yine başlar; daha geçse sonraki saat beklenir.
START_WINDOW = timedelta(minutes=15)
DAY_NAMES = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]


def parse_times(text):
    """'09:00, 13:30' -> [time(9, 0), time(13, 30)]. Hatalıysa ValueError."""
    times = set()
    for token in re.split(r"[,;\s]+", text or ""):
        if not token:
            continue
        match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", token)
        if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
            raise ValueError(f"Gönderim saati anlaşılamadı: '{token}'. Örnek yazım: 09:00, 13:30")
        times.add(time(int(match.group(1)), int(match.group(2))))
    if not times:
        raise ValueError("En az bir gönderim saati yazın (ör. 09:00, 13:30).")
    return sorted(times)


def format_times(times):
    return ", ".join(t.strftime("%H:%M") for t in times)


def _is_send_day(day, skip_weekends):
    return not (skip_weekends and day.weekday() >= 5)


def latest_slot(now, times, skip_weekends):
    """Bugün, şu ana kadar gelmiş en son gönderim saati (yoksa None)."""
    if not _is_send_day(now, skip_weekends):
        return None
    passed = [datetime.combine(now.date(), t) for t in times if datetime.combine(now.date(), t) <= now]
    return passed[-1] if passed else None


def next_slot(now, times, skip_weekends):
    """Şu andan sonraki ilk gönderim saati."""
    for offset in range(8):
        day = now + timedelta(days=offset)
        if not _is_send_day(day, skip_weekends):
            continue
        for t in times:
            candidate = datetime.combine(day.date(), t)
            if candidate > now:
                return candidate
    return None


def slot_key(slot):
    return slot.strftime("%Y-%m-%d %H:%M")


def describe(slot, now=None):
    """'Bugün 13:30', 'Yarın 09:00', 'Pazartesi 09:00'"""
    now = now or datetime.now()
    days = (slot.date() - now.date()).days
    if days == 0:
        day = "Bugün"
    elif days == 1:
        day = "Yarın"
    elif days < 7:
        day = DAY_NAMES[slot.weekday()]
    else:
        day = slot.strftime("%d.%m")
    return f"{day} {slot:%H:%M}"


def keep_awake(enabled):
    """Planlı gönderim varken Windows'un uykuya geçmesini engeller (ekran kapanabilir)."""
    if sys.platform != "win32":
        return
    ES_CONTINUOUS = 0x80000000
    ES_SYSTEM_REQUIRED = 0x00000001
    try:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if enabled else 0))
    except Exception:
        log.warning("Uyku modu ayarı değiştirilemedi", exc_info=True)
