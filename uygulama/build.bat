@echo off
chcp 65001 >nul
rem Bu dosya "uygulama" klasorunde durur; exe ana klasore (bir ust klasor) konur.
cd /d "%~dp0.."
title Sponsorluk Mail - exe uretimi

echo ============================================
echo   Sponsorluk Mail - exe uretimi / guncelleme
echo   Verileriniz ("veriler" klasoru) korunur.
echo ============================================
echo.

where python >nul 2>nul || (
  echo HATA: Python bulunamadi. python.org'dan kurun ^(kurarken "Add Python to PATH" isaretleyin^).
  goto :error
)

rem --- Uygulama aciksa exe degistirilemez ---
tasklist /FI "IMAGENAME eq SponsorlukMail.exe" | find /I "SponsorlukMail.exe" >nul
if not errorlevel 1 (
  echo Uygulama su an acik. Lutfen kapatip bu dosyayi tekrar calistirin.
  goto :error
)

rem --- Guncellemeden once veritabani yedegi ---
if exist "veriler\veriler.db" (
  if not exist "veriler\yedekler\" mkdir "veriler\yedekler"
  for /f %%T in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd_HHmm"') do (
    copy /Y "veriler\veriler.db" "veriler\yedekler\veriler_%%T.db" >nul
    echo Veritabani yedeklendi: veriler\yedekler\veriler_%%T.db
  )
)

echo.
echo === Gerekli paketler kontrol ediliyor ===
python -m pip install -q --disable-pip-version-check -r "%~dp0requirements.txt" pyinstaller || goto :error

rem Kodda hata varsa derlemeye gecme; eski exe bozulmasin.
python -m compileall -q "%~dp0." >nul || (
  echo HATA: Kaynak kodda bir hata var, guncelleme yapilmadi.
  goto :error
)

echo.
echo === Uygulama derleniyor (1-3 dakika surebilir) ===
rem Gecici derleme dosyalari OneDrive disinda tutulur (OneDrive senkronu dosyalari kilitleyebiliyor).
set "BUILD_DIR=%TEMP%\SponsorlukMail_build"
if exist "%BUILD_DIR%\dist\SponsorlukMail.exe" del /Q "%BUILD_DIR%\dist\SponsorlukMail.exe"
python -m PyInstaller --noconfirm --log-level WARN --onefile --windowed ^
  --name "SponsorlukMail" ^
  --collect-data customtkinter ^
  --collect-data googleapiclient ^
  --add-data "%~dp0imza_ikonlar;imza_ikonlar" ^
  --add-data "%~dp0google_istemci.json;." ^
  --icon "%~dp0simge.ico" ^
  --distpath "%BUILD_DIR%\dist" --workpath "%BUILD_DIR%\work" --specpath "%BUILD_DIR%" ^
  "%~dp0main.py" || goto :error

rem Yeni exe once gecici klasorde uretilir; basariliysa ana klasore konur.
copy /Y "%BUILD_DIR%\dist\SponsorlukMail.exe" "SponsorlukMail.exe" >nul || goto :error

echo.
echo ============================================
echo   TAMAM! SponsorlukMail.exe ana klasore kondu.
echo ============================================
if not exist "veriler\credentials.json" echo UYARI: veriler\credentials.json yok. README'deki adimlara bakin.
pause
exit /b 0

:error
echo.
echo Islem tamamlanamadi. Yukaridaki mesajlara bakin. Verileriniz yerinde duruyor.
pause
exit /b 1
