"""
Proje kurulum ve dinamik bağımlılık yönetimi scripti.

Bu modül, projenin yapılandırılması ve özellikle Termux gibi kısıtlı
ortamlarda problem çıkartan bağımlılıkların güvenlibir biçimde 
filtrelenmesi işlemlerini üstlenir. Ayrıca Termux algılandığında
ilgili kütüphaneyi otomatik olarak sistem paket yöneticisi ile kurar.
"""

import os
import sys
import subprocess
from typing import List
from setuptools import setup, find_packages


def _is_termux_environment() -> bool:
    """
    Sistemin Termux ortamında çalışıp çalışmadığını tespit eder.
    
    Termux ortamı genellikle 'PREFIX' isimli ortam değişkeninde 
    '/data/data/com.termux/files/usr' gibi bir yol barındırır.
    
    Returns:
        bool: Eğer sistem Termux ise True, aksi takdirde False döner.
    """
    prefix: str = os.environ.get("PREFIX", "")
    return "com.termux" in prefix


def _get_requirements() -> List[str]:
    """
    requirements.txt dosyasını güvenli şekilde okur ve bağımlılıkları listeler.
    
    Eğer sistem Termux ise, 'cryptography' paketini listeden dinamik olarak
    çıkartır ve derleme hatalarını önlemek adına bu paketi arka planda 
    Termux'un kendi paket yöneticisi ile otomatik olarak kurar.
    
    Returns:
        List[str]: Yüklenmesi gereken Python paketlerinin filtrelenmiş listesi.
    """
    requirements: List[str] = []
    
    current_dir: str = os.path.dirname(os.path.abspath(__file__))
    req_file_path: str = os.path.join(current_dir, "requirements.txt")
    
    if not os.path.exists(req_file_path):
        print("⚠️ UYARI: requirements.txt dosyası bulunamadı!")
        return requirements

    try:
        with open(req_file_path, "r", encoding="utf-8") as file:
            for line in file:
                clean_line: str = line.strip()
                
                if not clean_line or clean_line.startswith("#"):
                    continue
                
                if _is_termux_environment() and "cryptography" in clean_line.lower():
                    print("\n" + "="*60)
                    print("⚙️  Termux Ortamı Algılandı.")
                    print("⚙️  'cryptography' paketinin pip ile kurulumu atlanıyor.")
                    print("⚙️  Sistem paket yöneticisi ile otomatik kurulum başlatılıyor...")
                    print("="*60 + "\n")
                    
                    try:
                        subprocess.run(
                            ["pkg", "install", "-y", "python-cryptography"],
                            check=True,
                            stdout=sys.stdout,
                            stderr=sys.stderr
                        )
                        print("✅ BAŞARILI: 'python-cryptography' sistemi üzerinden otomatik kuruldu.")
                    except subprocess.CalledProcessError as e:
                        print(f"❌ HATA: Termux üzerinden paket kurulumu başarısız oldu. İşlem kodu: {e.returncode}")
                        sys.exit(1)
                    except FileNotFoundError:
                        print("❌ KRİTİK HATA: 'pkg' komutu sistemde bulunamadı. Lütfen Termux ortamınızı kontrol edin.")
                        sys.exit(1)
                    
                    continue
                
                requirements.append(clean_line)
                
    except IOError as e:
        print(f"❌ HATA: Bağımlılıklar okunurken bir sorun oluştu: {e}")
        sys.exit(1)

    return requirements


setup(
    name="asansor-denetcisi",
    version="1.0.0",
    description="Gmail üzerinden A tipi muayene kuruluşlarından (MMO, ARTIBEL, ASANSÖR KONTROL, KENT GRUP BELGELENDİRME, OPTİMAL DENGE) gelen asansör raporu maillerini işleyen, etiketleyen ve WhatsApp'tan paylaşılabilir takip listesi oluşturan otomasyon.",
    author="ciwga",
    
    packages=find_packages(include=["app", "app.*"]),
    
    include_package_data=True,
    
    package_data={
        "app": [
            "web/templates/*.html",
            "web/static/css/*.css",
            "web/static/js/*.js",
            "downloaders/*.json"
        ]
    },
    
    py_modules=["run"],
    
    install_requires=_get_requirements(),
    
    python_requires=">=3.9",
)