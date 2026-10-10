@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul || (
  echo Python bulunamadi. python.org'dan kurun ^(kurarken "Add Python to PATH" isaretleyin^).
  pause
  exit /b 1
)

rem Eksik paket varsa (ilk calistirma ya da guncelleme sonrasi) otomatik kur.
python -c "import customtkinter, googleapiclient, google_auth_oauthlib, openpyxl" >nul 2>nul || (
  echo Gerekli paketler kuruluyor, bir kereye mahsus biraz surebilir...
  python -m pip install -q --disable-pip-version-check -r "%~dp0uygulama\requirements.txt" || (
    echo Paketler kurulamadi. Internet baglantinizi kontrol edin.
    pause
    exit /b 1
  )
)

start "" pythonw "%~dp0uygulama\main.py"
