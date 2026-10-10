# Sponsorluk Mail Gonderici - kurulum / guncelleme
#
# Kullanim: Baslat'a "PowerShell" yazip acin, asagidaki satiri yapistirip Enter'a basin:
#   irm https://raw.githubusercontent.com/AloneDark7658/sponsorluk-mail/main/kurulum.ps1 | iex
#
# Ne yapar: Python yoksa kurar (winget ile, Microsoft'un kendi araci), uygulamanin son surumunu
# GitHub'dan indirip %LOCALAPPDATA%\SponsorlukMail klasorune kurar, masaustune ve Baslat menusune
# kisayol koyar. Tekrar calistirilirsa guncelleme yapar; 'veriler' klasorune dokunmaz.
# Bu betik exe calistirmaz (Python resmi ve imzalidir), bu yuzden Windows engellemez.

& {
    $ErrorActionPreference = "Stop"
    $ProgressPreference = "SilentlyContinue"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

    $Repo = "AloneDark7658/sponsorluk-mail"
    $AppName = "Sponsorluk Mail"
    $InstallDir = Join-Path $env:LOCALAPPDATA "SponsorlukMail"
    $TestMode = [bool]$env:SPONSORLUK_TEST_DIZINI  # deneme: her sey bu klasore, masaustune dokunulmaz
    if ($TestMode) { $InstallDir = $env:SPONSORLUK_TEST_DIZINI }
    $AppDir = Join-Path $InstallDir "uygulama"

    function Step($message) { Write-Host ""; Write-Host "==> $message" -ForegroundColor Cyan }
    function Fail($message) {
        Write-Host ""
        Write-Host "HATA: $message" -ForegroundColor Red
        Write-Host "Sorun devam ederse bu pencerenin ekran goruntusunu kulup yonetimine gonderin."
    }

    function Test-Python($exe, $prefix) {
        # Yol, kullanici adinda Turkce karakter (O, S, I...) olsa da bozulmasin diye UTF-8 baytlarinin
        # onaltilik (hex) hali olarak alinir; Windows PowerShell konsol kodlamasindan etkilenmez.
        try {
            $out = & $exe @prefix -c "import sys, tkinter; print(sys.version_info >= (3, 10)); print(sys.executable.encode('utf-8').hex())" 2>$null
        } catch { return $null }
        if ($LASTEXITCODE -ne 0 -or -not $out -or $out[0] -ne "True") { return $null }
        $hex = "$($out[1])".Trim()
        $bytes = [byte[]]@(for ($i = 0; $i -lt $hex.Length; $i += 2) { [Convert]::ToByte($hex.Substring($i, 2), 16) })
        $path = [Text.Encoding]::UTF8.GetString($bytes)
        if (Test-Path -LiteralPath $path) { return $path }
        return $null
    }

    function Get-PythonPath {
        foreach ($candidate in @(@("py", @("-3")), @("python", @()), @("python3", @()))) {
            if (Get-Command $candidate[0] -ErrorAction SilentlyContinue) {
                $found = Test-Python $candidate[0] $candidate[1]
                if ($found) { return $found }
            }
        }
        $paths = @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python3*\python.exe" -ErrorAction SilentlyContinue) +
                 @(Get-ChildItem "$env:ProgramFiles\Python3*\python.exe" -ErrorAction SilentlyContinue)
        foreach ($p in $paths) {
            $found = Test-Python $p.FullName @()
            if ($found) { return $found }
        }
        return $null
    }

    try {
        Write-Host ""
        Write-Host "  $AppName - kurulum" -ForegroundColor Green
        Write-Host "  Kurulum klasoru: $InstallDir"

        Step "Python kontrol ediliyor"
        $python = Get-PythonPath
        if (-not $python) {
            if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
                Fail "Python bulunamadi. python.org adresinden Python kurun (kurarken 'Add Python to PATH' kutusunu isaretleyin), sonra bu komutu tekrar calistirin."
                return
            }
            Write-Host "Python kuruluyor (birkac dakika surebilir)..."
            winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements | Out-Host
            $python = Get-PythonPath
            if (-not $python) {
                Fail "Python kuruldu ama bulunamadi. Bilgisayari yeniden baslatip bu komutu tekrar calistirin."
                return
            }
        }
        $pythonw = Join-Path (Split-Path $python) "pythonw.exe"
        Write-Host "Python: $python"

        Step "Son surum indiriliyor"
        $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" -Headers @{ "User-Agent" = "SponsorlukMail-Kurulum" }
        $asset = $release.assets | Where-Object { $_.name -like "SponsorlukMail-*.zip" } | Select-Object -First 1
        if (-not $asset) { Fail "GitHub'da kurulum paketi bulunamadi."; return }
        Write-Host "Surum: $($release.tag_name)"
        $tmp = Join-Path $env:TEMP ("sponsorluk_kurulum_" + [guid]::NewGuid().ToString("N"))
        New-Item -ItemType Directory -Path $tmp | Out-Null
        $zip = Join-Path $tmp "paket.zip"
        Invoke-WebRequest $asset.browser_download_url -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath (Join-Path $tmp "yeni") -Force
        if (-not (Test-Path (Join-Path $tmp "yeni\main.py"))) { Fail "Indirilen paket beklenen yapida degil."; return }

        Step "Uygulama kuruluyor"
        New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
        if (Test-Path $AppDir) { Remove-Item $AppDir -Recurse -Force }
        Copy-Item (Join-Path $tmp "yeni") $AppDir -Recurse
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue

        Step "Gerekli paketler kuruluyor (ilk kurulumda birkac dakika surebilir)"
        $requirements = Join-Path $AppDir "requirements.txt"
        & $python -m pip install -q --disable-pip-version-check --no-warn-script-location -r $requirements
        if ($LASTEXITCODE -ne 0) {
            & $python -m pip install -q --disable-pip-version-check --no-warn-script-location --user -r $requirements
            if ($LASTEXITCODE -ne 0) { Fail "Paketler kurulamadi. Internet baglantinizi kontrol edip tekrar deneyin."; return }
        }

        Step "Kisayollar olusturuluyor"
        $shell = New-Object -ComObject WScript.Shell
        $places = @([Environment]::GetFolderPath("Desktop"), (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"))
        if ($TestMode) { $places = @($InstallDir) }
        foreach ($place in $places) {
            $shortcut = $shell.CreateShortcut((Join-Path $place "$AppName.lnk"))
            $shortcut.TargetPath = $pythonw
            $shortcut.Arguments = "`"$AppDir\main.py`""
            $shortcut.WorkingDirectory = $InstallDir
            $shortcut.IconLocation = "$AppDir\simge.ico"
            $shortcut.Description = "Sponsorluk Mail Gonderici"
            $shortcut.Save()
        }

        Write-Host ""
        Write-Host "TAMAM! '$AppName' masaustune ve Baslat menusune eklendi. Uygulama aciliyor..." -ForegroundColor Green
        Write-Host "Sonraki guncellemeler uygulamanin icinden yapilir."
        if (-not $TestMode) { Start-Process $pythonw -ArgumentList "`"$AppDir\main.py`"" -WorkingDirectory $InstallDir }
    } catch {
        Fail $_.Exception.Message
    }
}
