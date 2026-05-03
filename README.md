<div align="center">

# 🏢 Asansör Denetçisi & Rapor Takip Otomasyonu

**Periyodik Asansör Muayene Raporlarını Otomatikleştiren, Analiz Eden ve Yöneten Sistem**

[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue.svg?style=flat-square&logo=python)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-Web_UI-green.svg?style=flat-square&logo=flask)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-ORM-red.svg?style=flat-square&logo=sqlite)](https://www.sqlalchemy.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux%20%7C%20Termux-lightgrey.svg?style=flat-square)]()
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg?style=flat-square)](https://www.gnu.org/licenses/gpl-3.0)

[Özellikler](#özellikler) • [Mimari & Teknolojiler](#mimari-ve-teknolojiler) • [Kurulum](#kurulum) • [Kullanım](#kullanım) • [Desteklenen Firmalar](#firmalar)

</div>

---

## 📖 Proje Hakkında

**Asansör Denetçisi**, Gmail (veya yerel klasörler) üzerinden gelen periyodik asansör kontrol raporlarını (PDF) ve randevu e-postalarını otomatik olarak indiren, regex algoritmalarıyla ayrıştıran ve veritabanında (SQLite) indeksleyen bir otomasyondur.

Bina adını, asansör kimlik numarasını, muayene tarihini ve **etiket rengini (Kırmızı, Sarı, Mavi, Yeşil)** tespit eder. Yasal sürelere göre bir sonraki muayene tarihini hesaplayarak bir Web Arayüzü  ve CLI üzerinden kullanıcıya sunar.

---

<a id="ozellikler"></a>
## ✨ Özellikler ve Teknik Yetenekler

* 🛡️ **AES-256 Veri Güvenliği:** Google OAuth2 jetonları ve sistem yapılandırmaları, `cryptography.fernet` modülü kullanılarak veritabanında **şifrelenmiş** olarak saklanır.
* ⚡ **Çoklu İş Parçacığı:** E-posta indirme, PDF okuma ve etiketleme süreçleri Python `threading` ve `queue` mimarisi ile asenkron yürütülür; büyük veri setlerinde dahi anında tepki verir.
* 🧠 **Akıllı Çözümleme Filtresi:** Aynı asansöre ait yeni tarihli olumlu (Yeşil/Mavi) bir rapor varsa, sistem eski olumsuz raporları işlemeyi atlar, performansı artırır.
* 📱 **Termux (Android) Optimizasyonu:** Kurulum scripti ([`setup.py`](setup.py)), çalışma ortamını dinamik analiz eder. Termux ortamında `cryptography` modülü derleme hatalarını önlemek için sistem paket yöneticisini (`pkg`) arka planda otonom olarak kullanır.
* 🌐 **Canlı Web Arayüzü:** Flask ve `flask-socketio` tabanlı; canlı log akışı, dark/light tema, grid/liste görünümü ve gelişmiş JSON ayar editörü sunan hızlı panel.
* 🧹 **Otonom Gmail Bakımı:** Yanlış etiketleri temizler, eski mailleri çöpe atar ve hatalı (ulaşılamamış) PDF'leri karantinaya alır.
* 📊 **Çoklu Dışa Aktarma:** Sonuçları Terminal, `TXT`, `CSV` ve günlük raporlama için **WhatsApp (`WA`)** uyumlu mesaj formatlarında dışa aktarır.

---

<a id="firmalar"></a>
## 🏢 Desteklenen Firmalar (Ayrıştırıcılar)

Sistem, muayene kuruluşlarının kendilerine ait PDF şablonlarını otomatik tanır ([`registry.py`](app/parsers/registry.py)) ve ilgili `Parser` sınıfını otonom olarak devreye sokar:

* **TMMOB Makina Mühendisleri Odası (MMO)**
* **Optimal Denge**
* **Adetsis / Kent Grup Belgelendirme / Asansör Kontrol**
* **Artıbel Belgelendirme**

---

<a id="kurulum"></a>
## 🚀 Kurulum

### 1. Gereksinimler
Sisteminizde **Python 3.9 veya üzeri** yüklü olmalıdır. Android cihazlarda kullanmak için **Termux** kurmanız önerilir.

### 2. Projeyi Klonlayın
```bash
git clone https://github.com/ciwga/gmail-asansor-rapor-takip.git
cd gmail-asansor-rapor-takip
```

### 3. Bağımlılıkları Yükleyin
*(Sanal ortam oluşturulması tavsiye edilir.)*
```bash
# Sanal ortam oluşturun ve aktif edin:
python -m venv .venv
source .venv/bin/activate  # Windows için: .venv\Scripts\activate

# Projeyi ve bağımlılıklarını kurun:
pip install -e .
```
> **Not (Termux Kullanıcıları):** Yüklemeden önce depolama izni vermek için `termux-setup-storage` komutunu çalıştırdığınızdan emin olun. `setup.py` gerekli Android bağımlılıklarını otomatik çözecektir.

### 4. Google API Kimlik Bilgileri
1. [Google Cloud Console](https://console.cloud.google.com/)'dan **Gmail API**'yi aktifleştirin.
2. Bir **Masaüstü Uygulaması** için OAuth 2.0 İstemci Kimlikleri (Credentials) oluşturun ve dosyayı indirin.
3. İndirdiğiniz dosyayı `credentials.json` adıyla projenin ana dizinine bırakın veya Web Arayüzü -> **⚙️ Ayarlar** kısmından yükleyin.

---

<a id="kullanım"></a>
## 💻 Kullanım

Uygulamanın merkez kontrol noktası [`run.py`](run.py) dosyasıdır. İster komut satırından ister modern arayüzden yönetebilirsiniz.

### 🌐 Web Arayüzünü Başlatmak (Önerilen)
En iyi deneyim için web sunucusunu başlatın:
```bash
python run.py --web
```
*Tarayıcınızdan `http://127.0.0.1:5001` giderek sistemi kullanabilirsiniz.*

### 🔄 İzleme (Watch) Modu
E-postaları arka planda belirtilen aralıklarla (örn: 30 dakikada bir) taramak için:
```bash
python run.py --watch -i 30
```

### 🖥️ Komut Satırı (CLI) Modu
Sistemi bir defaya mahsus çalıştırıp terminal üzerinden özet almak için:
```bash
python run.py
```

### 🛠️ Gelişmiş CLI Komutları
```bash
# Sadece belirli etiketlere sahip okunmamış mailleri ara ve işleyince arşive taşı
python run.py --by-label -l "Kırmızı Etiketli" "Sarı Etiketli" --read --archive

# Veritabanındaki tüm PDF kayıtlarını tablo şeklinde listele
python run.py -L

# Veritabanında 15 ID'sine sahip PDF dosyasını dışa aktar
python run.py -E 15 -O ./DışaAktarılanlar

# Tüm veritabanını zorla yeniden analiz et ve mükerrerleri atlama
python run.py --force --dups
```

---

<a id="mimari-ve-teknolojiler"></a>
## 🏗️ Mimari ve Dizin Yapısı

Proje SOLID prensiplerine uygun, MVC benzeri modüler bir hiyerarşide tasarlanmıştır:

```text
📦 gmail-asansor-rapor-takip
 ┣ 📂 app/                 # Uygulama ana paketi
 ┃ ┣ 📂 core/              # SQLAlchemy Modelleri, AES-256 DB, Multi-Thread Engine ve Resolution Filtresi
 ┃ ┣ 📂 downloaders/       # Dinamik İndirme Motoru, Scraping Profilleri ve HTTP Yardımcıları
 ┃ ┣ 📂 gmail/             # OAuth2 Kimlik Doğrulama, Rate-Limit Korumalı API Client ve Bakım
 ┃ ┣ 📂 parsers/           # Firmalara özel PDF Okuma Sınıfları (Artibel, MMO, Optimal, Adetsis)
 ┃ ┣ 📂 reporters/         # Tarih hesaplamaları (dates.py) ve Çıktı Üreticiler (writers.py)
 ┃ ┣ 📂 utils/             # Regex Desenleri (patterns.py), Renkli Loglama ve String Normalizasyon
 ┃ ┣ 📂 web/               # Flask Server, Socket.IO, HTML/JS/CSS Canlı Arayüz Kodları
 ┃ ┣ 📜 config.py          # Akıllı Konfigürasyon Yöneticisi ve Varsayılan Ayarlar
 ┃ ┗ 📜 paths.py           # İşletim Sisteminden Bağımsız Güvenli Dizin Sabitleri
 ┣ 📂 data/                # Veritabanı ve loglar için ayrılmış alan
 ┃ ┗ 📜 .gitkeep           # Klasörün Git tarafından takip edilmesini sağlayan boş dosya
 ┣ 📂 tests/               # Birim Testleri
 ┃ ┗ 📜 test_core.py       # Çekirdek modüller, db işlemleri ve regex örüntü testleri
 ┣ 📜 run.py               # Ana Tetikleyici ve Parametre Yönlendirici
 ┣ 📜 setup.py             # Dinamik Bağımlılık ve Termux Çözümleyici (Kurulum Scripti)
 ┣ 📜 requirements.txt     # Gerekli Python kütüphaneleri listesi
 ┣ 📜 pyproject.toml       # Modern Python paket inşa yapılandırması
 ┣ 📜 MANIFEST.in          # Statik dosyaların (HTML/CSS) paketlemeye dahil edilme kuralları
 ┣ 📜 README.md            # Proje dokümantasyonu ve kullanım rehberi
 ┣ 📜 LICENSE              # GNU GPLv3 Açık Kaynak Lisans Dosyası
 ┗ 📜 .gitignore           # Git tarafından takip edilmeyecek dosyalar
```

---

## ⚙️ Yapılandırma Sistemi

[`config.py`](app/config.py) modülü, güvenli klasör yapılarını işletim sisteminize göre otomatik tanımlar. Konfigürasyon veritabanında tutulur. Hiyerarşik (Ağaç) Gmail etiketleri, hariç tutulacak kelimeler, özel çöp kutusu kuralları, manuel veri yolları gibi ince ayarlar, Web Arayüzündeki **⚙️ Ayarlar** sekmesinden gerçek zamanlı olarak düzenlenebilir.

---

## 🤝 Katkıda Bulunma

Bu proje asansör bakım firmaları, yöneticiler ve denetçilerin iş yükünü hafifletmek amacıyla geliştirilmiştir. Yeni bir firmanın PDF şablonunu sisteme eklemek çok kolaydır!

1. Projeyi fork'layın.
2. Yeni özelliğiniz için bir branch açın (`git checkout -b feature/YeniFirmaParser`).
3. Kodunuzu PEP8 standartlarına uygun olarak yazıp commit'leyin.
4. Branch'inizi gönderin (`git push origin feature/YeniFirmaParser`).
5. Bir Pull Request oluşturun.

---

## 📝 Lisans

Bu proje **GNU GENERAL PUBLIC LICENSE Version 3, 29 June 2007** altında lisanslanmıştır. Daha fazla bilgi için [`lisans`](LICENSE) dosyasına göz atabilirsiniz.
