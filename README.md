# Sponsorluk Mail Gönderici

Kulübün sponsorluk maillerini kendi Gmail hesabınızdan, firmaya özel doldurulmuş olarak gönderen masaüstü uygulaması.

- Excel / CSV'den firma listesi alır (zorunlu sütunlar: **Email, Firma, Yetkili**; diğer sütunlar da kullanılabilir)
- Metinde `{{Firma}}`, `{{Yetkili}}`, `{{Sektör}}` gibi alanlar her firma için otomatik dolar
- **Sabit CC listesi** her maile otomatik eklenir (ör. YK Google Grubu)
- Birden fazla ek (PDF, Word, Excel, görsel...), şablon kaydetme, canlı önizleme, kendine test maili
- Ayarlardan düzenlenen **imza** (isteğe bağlı logo ile) her maile otomatik eklenir
- **Gönderim saatleri:** mailler yalnızca belirlenen saatlerde (varsayılan 09:30 ve 13:30) gider
- **Google sunucusuyla planlama:** günde 100 alıcıya kadar olan kısım, bilgisayar kapalıyken de Google'ın sunucusundan gider
- Kimin gönderildiği / hata aldığı kaydedilir; uygulama kapansa bile **kaldığı yerden devam eder**
- Günlük limit (CC dahil) ve mailler arası bekleme ile Gmail'e takılmadan gönderir
- **Cevap takibi:** hangi firmanın cevap verdiğini otomatik bulur, konuşmayı tek tıkla Gmail'de açar
- **Hatırlatma:** cevap vermeyenlere, ilk mailin devamı olarak hatırlatma gönderir
- **Otomatik güncelleme:** yeni sürüm çıkınca uygulama haber verir, tek tıkla güncellenir

---

## 1. Kurulum

**Kurmadan önce:** Gmail adresinizi kulüp yönetimine iletin. Yönetici sizi uygulamanın kullanıcıları arasına ekler (bkz. [Yönetici için](#5-yönetici-için-google-cloud-ayarları)). Eklenmemiş bir hesapla giriş yapılamaz.

1. **Başlat** menüsüne `PowerShell` yazıp **Windows PowerShell**'i açın.
2. Aşağıdaki satırı kopyalayıp yapıştırın ve **Enter**'a basın:

```powershell
irm https://raw.githubusercontent.com/AloneDark7658/sponsorluk-mail/main/kurulum.ps1 | iex
```

3. Birkaç dakika bekleyin. Bilgisayarınızda Python yoksa kendisi kurar, uygulamayı indirir, **masaüstüne ve Başlat menüsüne "Sponsorluk Mail" kısayolu** ekler ve uygulamayı açar.

Kurulum hiçbir .exe çalıştırmadığı için Windows uyarı vermez. *Akıllı Uygulama Denetimi* açık bilgisayarlarda da çalışır. Uygulama `%LOCALAPPDATA%\SponsorlukMail` klasörüne kurulur, yönetici şifresi istemez.

**Kaldırmak için:** Masaüstündeki ve Başlat menüsündeki kısayolu silin, `%LOCALAPPDATA%\SponsorlukMail` klasörünü silin.

## 2. Güncelleme

Uygulama her açılışta yeni sürüm olup olmadığına bakar. Varsa üstte turuncu **"⬆ vX hazır — Güncelle"** butonu çıkar. Butona basınca neler değiştiğini görürsünüz. **Şimdi güncelle** dediğinizde uygulama indirir, kapanır ve birkaç saniye içinde yeni sürümle açılır.

- **Verileriniz** (firma listesi, şablonlar, imza, Gmail oturumu) güncellemeden etkilenmez.
- Bir sorun olursa önceki sürüme geri döner. Gönderim sürerken güncelleme yapılmaz.
- Elle kontrol etmek için üstteki sürüm numarasına (ör. `v1.5.0`) tıklayın.

## 3. İlk açılış

1. Sağ üstte **Gmail ile bağlan**'a basın, tarayıcı açılır ve hesabınızı seçin.
2. **"Google bu uygulamayı doğrulamadı"** uyarısı normaldir (kulübün kendi uygulaması): **Gelişmiş → Sponsorluk Mail'e git (güvenli değil)**. İzin ekranındaki **tüm kutuları işaretleyip** onaylayın.
3. Sağ üstte `Bağlı hesap: ...` yazısını görmelisiniz.
4. **Mail Metni** sekmesinde **İmzayı düzenle** ile kendi imzanızı (ad, unvan, telefon...) doldurun.

> Google, "test" modundaki uygulamalarda oturumu **7 günde bir** sıfırlar. "Oturum süresi dolmuş" görürseniz **Hesabı değiştir** ile tekrar bağlanmanız yeterli.

Herkes kendi Gmail hesabıyla giriş yapar ve kendi hesabından gönderir. Kimse kimsenin maillerini göremez.

---

## 4. Kullanım

**1) Firma Listesi**
- **Boş Excel şablonu indir** ile hazır şablonu alın. Gri örnek satırları silip firmaları yazın. Unutursanız sorun olmaz, `@example.com` adresli örnek satırlar otomatik atlanır.
- **İçe aktar (Excel / CSV)** ile dosyayı seçin. İlk satır başlık olmalı: `Email`, `Firma`, `Yetkili` (+ istediğiniz ek sütunlar, ör. `Sektör`). Ek sütunlar metinde `{{Sütun Adı}}` ile kullanılabilir.
- Listede zaten olan adresler eklenmez ve size bildirilir. Geçersiz adresler de atlanır.
- **+ Firma ekle** ile tek tek elle firma ekleyebilirsiniz. Her satırın sonundaki **✎ Düzenle** ile firmanın bilgilerini değiştirebilir ya da silebilirsiniz. 'Hata' durumundaki bir firmayı düzenleyip kaydedince (ör. eksik Yetkili'yi yazınca) otomatik olarak tekrar 'Bekliyor' olur.
- Tabloda her firmanın durumu görünür: **Bekliyor / Gönderildi (tarih) / Hata (sebep)**.
- **Hatalıları tekrar dene** hatalı firmaları yeniden "Bekliyor" yapar.

**2) Mail Metni ve Önizleme**
- Konu ve metni yazın. Metnin yanındaki **Değişkenler** listesinde kullanabileceğiniz tüm alanlar, önizlemedeki firmanın değerleriyle görünür. Tıklayınca imlecin olduğu yere eklenir. Ya da metinde istediğiniz yere **sağ tık → Değişken ekle** ile ekleyin (konu ve hatırlatma metninde de çalışır).
- **Sabit CC:** adresi yazıp **Enter**'a (ya da **+ Ekle**'ye) basın; istediğiniz kadar adres ekleyebilirsiniz. Her adres altta ayrı bir etiket olarak görünür, **✕** ile silinir. Bu adresler her maile eklenir ve kalıcı olarak kaydedilir. Not: Her CC adresi Gmail'in günlük limitinde ayrı alıcı sayılır; YK için tek bir Google Grubu adresi en verimlisidir.
- **+ Dosya ekle** ile istediğiniz kadar ek seçin (PDF, Word, Excel, PowerPoint, görsel...). Toplam en fazla 18 MB olabilir. Gmail'in engellediği türler (.exe, .bat vb.) eklenemez. Büyük dosyalar için Google Drive linkini metne yazın.
- **İmzayı düzenle** (ya da Gönderim sekmesindeki **İmza ayarları**): **Kartvizit şablonu** seçiliyken sadece bilgileri doldurun (ad soyad, unvan, telefon, e-posta, adres, web sitesi, sosyal medya linkleri) ve kulüp logosunu seçin. Solda logo, sağda bilgiler ve sosyal medya ikonları olan imza otomatik oluşur. **Tarayıcıda önizle** ile mailde nasıl görüneceğini görün. İsterseniz **Düz metin** imza da seçebilirsiniz. Her mailin ve hatırlatmanın sonuna eklenir; web adresleri ve mailler tıklanabilir link olur. Önizlemede imza da görünür.
- **Yeni şablon olarak kaydet** ile metni saklayıp sonra listeden tekrar seçebilirsiniz. Yazdıklarınız ayrıca otomatik kaydedilir.
- Sağda seçili firma için doldurulmuş mail görünür (`<` `>` ile firmalar arasında gezin). Boş kalan alan varsa kırmızı uyarı çıkar. **Eksik alanı olan firmaya mail gönderilmez**, "Hata: Eksik alan" olarak işaretlenir. Bu sayede "Sayın ,"  gibi bozuk mailler gitmez.

**3) Gönderim**
- Önce **Kendime test maili gönder**. Önizlemedeki firmanın bilgileriyle doldurulmuş mail sadece size gider (CC'ye gitmez).
- **Gönderim saatleri:** Ayarlardaki "Gönderim saatleri" (varsayılan `09:30, 13:30`) ve "Sadece bu saatlerde gönder" açıkken buton **GÖNDERİMİ PLANLA** olur. Basınca mailler hemen gitmez; sıradaki saat gelince kendiliğinden başlar. Üstte "⏰ Planlı gönderim: Yarın 09:00" gibi görünür. **O saatte uygulama açık olmalı.** Plan varken bilgisayar uykuya geçmez, ama dizüstünün kapağını kapatırsanız uyur.
  - Saat geçtikten sonraki 15 dakika içinde uygulamayı açarsanız gönderim yine başlar. Daha geç açarsanız sıradaki saati bekler.
  - "Hafta sonu gönderme" açıksa Cumartesi ve Pazar atlanır.
  - "Bir seferde en fazla firma" ile her saatte kaç firmaya gideceğini sınırlayabilirsiniz (ör. 50: sabah 50, öğlen 50). Kalanlar sonraki saatlerde otomatik devam eder.
  - Plan, uygulama kapanıp açılsa da korunur. **Planı iptal et** ile vazgeçebilirsiniz.
  - Saat kısıtını kapatırsanız buton **GÖNDERİMİ BAŞLAT** olur ve hemen gönderir. Test maili her zaman hemen gider.
- Gönderim sadece "Bekliyor" olanlara yapılır. Başlamadan önce kaç firmaya gideceğini gösterip onay ister.
- **Durdur** ile istediğiniz an durdurabilirsiniz. Uygulamayı kapatıp açtığınızda tekrar Başlat'a basınca kaldığı yerden devam eder.
- **Günlük limit** CC'ler dahil sayılır. Örneğin 2 CC varsa her mail 3 alıcıdır ve 200 limitle günde en fazla 66 firma gider. Limit dolunca gönderim durur, kalanlar bekler. Sayım son 24 saate göre yapılır (Gmail de öyle sayar).
- **Dışa aktarma:** Firma Listesi sekmesinde **CSV dışa aktar**. Excel'de açılır ve durumları içerir.

**Google sunucusuyla planlama (bilgisayar kapalıyken gönderim)**

Gmail'in kendi "gönderme zamanını planla" özelliği dışarıdan (API ile) kullanılamıyor. Bunun yerine uygulama mailleri Gmail'inize **taslak** olarak koyar, Google hesabınızda çalışan küçük bir kod da bunları seçtiğiniz saatte gönderir. Akşam planlayıp bilgisayarı kapatabilirsiniz.

- **Kurulum (bir kez):** Gönderim sekmesi → **Kurulum**. Pencerede 5 adım var: kodu kopyala, script.google.com'da yeni projeye yapıştır, `kurulum` fonksiyonunu çalıştırıp izin ver, sonra **Test maili planla**. 5-10 dakika içinde kendinize test maili gelirse kurulum tamamdır. Uygulama bunu kendisi fark eder.
- **Planlama:** **Google'da planla** → saati seçin (`09:30`, `13:30` ya da **İkiye böl**). Google'ın günlük **100 alıcı** sınırına (CC dahil; 1 CC ile 50 firma) sığan kısım Google'a verilir, kalanlar "Bekliyor"da kalır. Kalanları uygulamadan kendiniz gönderin (normal **GÖNDERİMİ PLANLA / BAŞLAT**).
- Google'daki kod 5 dakikada bir bakar; mailler saatten sonraki birkaç dakika içinde gider. O saatte gidemeyenler (ör. kota dolduysa) sonraki gönderim saatinde gider. Hafta sonu ayarına uyar.
- Kod sadece uygulamanın işaretlediği taslaklara dokunur; sizin kendi taslaklarınıza dokunmaz. Planlı taslakları Gmail'deki **Taslaklar** klasöründe görebilirsiniz; **silmeyin**, silerseniz o firma gitmez.
- Uygulamayı açtığınızda Google'ın gönderdikleri otomatik olarak "Gönderildi" yapılır, cevap takibi normal çalışır.
- Vazgeçmek için **Google planını iptal et**: taslaklar silinir, firmalar "Bekliyor"a döner. Google'da planlı bir firma, plan iptal edilmeden düzenlenemez ya da "Bekliyor" yapılamaz (iki kez gitmesin diye).
- Not: Google'ın 100 alıcı sınırı ile Gmail'in genel ~500 alıcı sınırı aynı hesapta birlikte geçerlidir.

**4) Cevaplar ve Hatırlatma**
- Uygulama her açıldığında ve açıkken 15 dakikada bir, gönderdiğiniz maillere cevap gelip gelmediğine Gmail'den bakar. **Bilgisayarın sürekli açık olması gerekmez.** Cevaplar Gmail'de durduğu için, kapalıyken gelenler de bir sonraki açılışta bulunur.
- Firma listesindeki **Cevap** sütununda durumlar görünür: *Cevap geldi*, *Cevap yok*, *Otomatik yanıt* (ofis dışında vb.), *Ulaşmadı* (adres hatalı, mail geri döndü).
- **Gmail'de aç ↗** ile o firmayla olan konuşma (gönderdiğiniz mail + gelen cevaplar) tarayıcıda açılır. Cevabı oradan okuyup yanıtlayabilirsiniz.
- Üstteki sarı bildirime tıklayınca yeni cevaplar ya da hatırlatma bekleyenler açılır.
- CC'deki ekip adreslerinin (ör. YK grubu) konuşmaya yazdıkları cevap sayılmaz.
- Firma telefonla ya da başka bir adresten döndüyse: **✎ Düzenle → "Cevap alındı olarak işaretle"**. İşaretli firmalara hatırlatma gitmez.
- **Hatırlatma:** Ayarladığınız gün sayısı (varsayılan 7) geçmiş ve cevap vermemiş firmalara, ilk mailin cevabı olarak (aynı konuşmada, "Re: ..." konusuyla) hatırlatma gönderilir. Sabit CC eklenir; günlük limit ve bekleme süresi geçerlidir. Göndermeden hemen önce her firmanın cevabı tekrar kontrol edilir. Hatırlatmalar otomatik gitmez, siz butona basınca gider. Saat kısıtı açıksa onlar da planlanır ve gönderim saatinde (aynı saatte ilk mail de varsa onun hemen ardından) gider.
- Not: Firma ilk mailinizi yanıtlamak yerine **yeni bir mail** yazarsa otomatik algılanamayabilir. O durumda elle işaretleyin.

**Hatalar:** Kısa Türkçe mesaj gösterilir. Teknik ayrıntı `veriler\uygulama.log` dosyasına yazılır, sorun olursa bu dosyayı yöneticiye gönderin.

---

## 5. Yönetici için: Google Cloud ayarları

Uygulamanın Gmail'e erişebilmesi için kulübün bir Google Cloud projesi var (bir kez kurulur). Uygulamanın içindeki `uygulama/google_istemci.json` bu projenin **istemci kimliğidir**. Bu dosya şifre değildir: masaüstü uygulamalarında Google bu dosyayı gizli saymaz ve giriş yapan herkes kendi Gmail hesabını kullanır.

### Yeni bir kullanıcı eklemek (her arkadaş için)
1. https://console.cloud.google.com/auth/audience adresine projenin sahibi hesabıyla girin (üstte doğru projenin seçili olduğundan emin olun).
2. **Test kullanıcıları (Test users)** → **+ Add users** → kişinin Gmail adresini yazın → **Kaydet**.

En fazla 100 kişi eklenebilir. Eklenmeyen biri girişte "Erişim engellendi (403)" hatası alır.

### Projeyi sıfırdan kurmak (sadece ilk kez)
### 1.1 Proje açın
1. https://console.cloud.google.com adresine mail göndereceğiniz Gmail hesabıyla girin.
2. Üstteki proje seçiciden **Yeni Proje (New Project)** → ad: `Sponsorluk Mail` → **Oluştur**.
3. Üstte yeni projenin seçili olduğundan emin olun.

### 1.2 Gmail API'yi açın
1. Sol menü → **API'ler ve Hizmetler → Kitaplık** (APIs & Services → Library).
2. Arama kutusuna `Gmail API` yazın → tıklayın → **Etkinleştir (Enable)**.

### 1.3 Onay ekranını ayarlayın
Sol menü → **API'ler ve Hizmetler → OAuth izin ekranı** (yeni arayüzde adı **Google Auth Platform**).
1. **Başlayın (Get started)** butonuna basın.
2. Uygulama adı: `Sponsorluk Mail`, destek maili: kendi adresiniz → İleri.
3. Kitle (Audience): **Harici (External)** → İleri.
4. İletişim bilgisi: kendi adresiniz → İleri → şartları onaylayıp **Oluştur**.

### 1.4 Kendinizi test kullanıcısı olarak ekleyin (önemli!)
1. Aynı bölümde **Kitle (Audience)** sekmesine gidin.
2. **Test kullanıcıları (Test users)** → **+ Kullanıcı ekle (Add users)** → mail göndereceğiniz Gmail adresini yazın → **Kaydet**.

> Bunu yapmazsanız girişte "Erişim engellendi" hatası alırsınız.

### İstemci kimliği
1. **İstemciler (Clients)** → **+ İstemci oluştur** → uygulama türü **Masaüstü uygulaması (Desktop app)** → **Oluştur** → **JSON'u indir**.
2. Dosyanın içeriğini GitHub deposunda **Settings → Secrets and variables → Actions → New repository secret** ile `GOOGLE_ISTEMCI_JSON` adıyla kaydedin. Kod deposuna girmez; her sürüm paketine otomatik eklenir. Kaynak koddan çalıştırırken dosyayı `uygulama/google_istemci.json` olarak koyun. Bir bilgisayarda farklı bir kimlik kullanmak isterseniz dosyayı o bilgisayarda `veriler/credentials.json` olarak koyun; o öncelikli olur.

---

## 6. Geliştirici için: yeni sürüm yayınlama

1. `uygulama/config.py` içindeki `APP_VERSION` değerini artırın (ör. `"1.6.0"`).
2. Değişiklikleri gönderin, ardından sürüm notlarıyla etiket oluşturup gönderin:

```bash
git tag -a v1.6.0 -m "Neler yeni: ..."
```

```bash
git push origin main --follow-tags
```

3. GitHub Actions (`.github/workflows/surum-yayinla.yml`) `uygulama` klasörünü `SponsorlukMail-1.6.0.zip` olarak paketleyip **Releases**'a koyar. Uygulamalar bir sonraki açılışta güncellemeyi görür. Etiket ile `APP_VERSION` uyuşmazsa yayın durdurulur.

Kaynak koddan çalıştırmak için: Python 3.10+ kurulu iken `Uygulamayi Ac.bat` (eksik paketleri kendisi kurar).

---

## Dosya yapısı

```
sponsorluk-mail/
├── kurulum.ps1                 Tek satırlık kurulum / güncelleme betiği
├── Uygulamayi Ac.bat           Kaynak koddan çalıştırma
├── uygulama/                   Uygulamanın kendisi (güncellemelerde değişir)
└── veriler/                    Kişisel veriler (GitHub'a yüklenmez, güncellemede korunur)
    ├── veriler.db              Firmalar, şablonlar, ayarlar, gönderim kaydı
    ├── token.json              Gmail oturumu
    └── uygulama.log            Hata kayıtları
```

| Dosya | Görevi |
|---|---|
| `main.py` | Uygulamayı başlatır, log ayarları |
| `config.py` | Dosya yolları ve varsayılan ayarlar |
| `gmail_client.py` | Google girişi (OAuth), mail oluşturma ve gönderme, hata çevirisi |
| `database.py` | SQLite: firmalar, şablonlar, ayarlar, gönderim kaydı |
| `template_engine.py` | `{{Alan}}` doldurma ve eksik alan tespiti |
| `importer.py` | Excel/CSV okuma, CSV dışa aktarma, email doğrulama |
| `sender.py` | Arka planda toplu gönderim ve hatırlatma (bekleme, limit, durdurma) |
| `mail_format.py` | Ek dosya kontrolleri, HTML mail ve imza (kartvizit / düz metin) |
| `schedule.py` | Gönderim saatleri ve planlı gönderim hesapları |
| `server_plan.py` | Google sunucusuyla planlama: taslaklar, sunucu kodu (Apps Script), senkronizasyon |
| `replies.py` | Cevap takibi: cevap / otomatik yanıt / ulaşmadı tespiti, hatırlatma zamanı |
| `ui/` | Arayüz: ana pencere ve dört sekme |
| `imza_ikonlar/` | İmzadaki sosyal medya ikonları |
| `updater.py` | Uygulama içinden güncelleme (GitHub Releases) |
| `google_istemci.json` | Uygulamanın Google istemci kimliği (şifre değildir) |
| `build.bat` | İsteğe bağlı .exe üretir (veriyi yedekleyip korur) |

**İzinler hakkında:** Uygulama Google'dan dört izin ister:
- `gmail.send`: mail göndermek için.
- `gmail.compose`: Google sunucusunun göndereceği taslakları oluşturmak / silmek için.
- `gmail.metadata`: cevap takibi için. Sadece mail **başlıklarını** (kimden, konu, tarih) görebilir; mail **içeriklerini ve ekleri okuyamaz**.
- `userinfo.email`: bağlı hesabın adresini göstermek için.
