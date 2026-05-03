"""
Gmail OAuth2 kimlik doğrulama modülü.

İki çalışma modunu destekler:
  1. CLI Modu: Yetkilendirme bağlantısını terminale basar ve yönlendirme bekler.
  2. Web Modu: Yetkilendirme bağlantısını SocketIO aracılığıyla web arayüzüne gönderir.
"""

import json
import socket
import threading
import os
import base64
from typing import Optional, Dict, Any, List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build, Resource

from app.utils.logging import get_logger
from app.core.database import get_secure_config, set_secure_config

log: Any = get_logger(__name__)

SCOPES: List[str] = ["https://www.googleapis.com/auth/gmail.modify"]

_auth_url: Optional[str] = None
_auth_event: threading.Event = threading.Event()


def _get_db_config(key: str) -> Optional[Dict[str, Any]]:
    """Veritabanından güvenli JSON yapılandırmasını okur.
    
    Eğer veritabanında henüz bir kayıt yoksa, kullanıcının proje klasöründe bulunan 
    eski kimlik dosyalarını diskten okuyup doğrudan veritabanına şifreleyerek aktarır.
    
    Args:
        key (str): Aranacak konfigürasyon anahtarı.
        
    Returns:
        Optional[Dict[str, Any]]: Bulunursa yapılandırma sözlüğü, aksi halde None.
    """
    try:
        db_data: Optional[Dict[str, Any]] = get_secure_config(key)
        if db_data:
            return db_data
            
        fname: Optional[str] = "credentials.json" if key == "auth_credentials" else "token.json" if key == "auth_token" else None
        
        if fname and os.path.exists(fname):
            try:
                with open(fname, "r", encoding="utf-8") as f:
                    disk_data: Dict[str, Any] = json.load(f)
                    
                set_secure_config(key, disk_data)
                log.info(f"✨ Geçiş: Diskteki '{fname}' okundu, şifrelendi ve güvenli veritabanına gömüldü.")
                return disk_data
            except Exception as e:
                log.warning(f"Diskteki '{fname}' dosyası okunamadı: {e}")
                
        return None
    except Exception as e:
        log.error(f"Veritabanından kimlik okuma hatası ({key}): {e}")
        return None


def _set_db_config(key: str, value: Dict[str, Any]) -> None:
    """Veritabanına güvenli JSON yapılandırması kaydeder.
    
    Args:
        key (str): Kaydedilecek konfigürasyon anahtarı.
        value (Dict[str, Any]): Kaydedilecek JSON uyumlu veri.
    """
    try:
        set_secure_config(key, value)
    except Exception as e:
        log.error(f"Veritabanına kimlik yazma hatası ({key}): {e}")


def get_pending_auth_url() -> Optional[str]:
    """Web arayüzü tarafından kontrol edilen, bekleyen yetkilendirme bağlantısını döndürür.

    Returns:
        Optional[str]: Bekleyen bir bağlantı varsa karakter dizisi, yoksa None.
    """
    return _auth_url


def _find_free_port() -> int:
    """Yerel sunucu için boş bir TCP bağlantı noktası bulur.

    Returns:
        int: Kullanılabilir bağlantı noktası numarası. Hata durumunda varsayılan 8080 döner.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 0))
            return s.getsockname()[1]
    except OSError:
        return 8080


def needs_auth() -> bool:
    """Mevcut erişim anahtarının geçerliliğini doğrudan veritabanından kontrol eder.

    Yetkilendirme gerekip gerekmediğini belirlemek için veritabanındaki anahtarı ve 
    geçerlilik sürelerini kontrol eder. Bu fonksiyon çalıştığında veri aktarımı tetiklenebilir.

    Returns:
        bool: Eğer yeni bir yetkilendirme gerekiyorsa True, aksi halde False.
    """
    client_config: Optional[Dict[str, Any]] = _get_db_config("auth_credentials")
    if not client_config:
        return True
        
    token_info: Optional[Dict[str, Any]] = _get_db_config("auth_token")
    if not token_info:
        return True
        
    try:
        creds: Optional[Credentials] = Credentials.from_authorized_user_info(token_info, SCOPES)
        
        if creds and creds.valid:
            return False
            
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _set_db_config("auth_token", json.loads(creds.to_json()))
            return False
    except Exception as e:
        log.debug(f"Kimlik doğrulama kontrolü sırasında hata: {e}")
        pass
        
    return True


def authenticate() -> Optional[Resource]:
    """Gmail API servisini veritabanındaki anahtarlarla başlatır ve döndürür.

    Gerektiğinde OAuth2 akışını başlatarak kullanıcıdan izin ister.
    Tüm veriler diskten değil, şifresi çözülmüş bellek sözlükleri aracılığıyla okunur.

    Returns:
        Optional[Resource]: Başarılı olursa Gmail API servis nesnesi, aksi halde None.
    """
    global _auth_url
    creds: Optional[Credentials] = None

    token_info: Optional[Dict[str, Any]] = _get_db_config("auth_token")
    if token_info:
        try:
            creds = Credentials.from_authorized_user_info(token_info, SCOPES)
        except Exception as e:
            log.warning(f"Jeton verisi veritabanından okunamadı veya bozuk: {e}")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                log.info("Erişim jetonunun süresi dolmuş, veritabanı üzerinden arka planda yenileniyor...")
                creds.refresh(Request())
            except Exception as e:
                log.warning(f"Jeton yenileme başarısız oldu: {e}")
                creds = None

        if not creds:
            client_config: Optional[Dict[str, Any]] = _get_db_config("auth_credentials")
            if not client_config:
                log.critical("Kimlik yapılandırması (auth_credentials) bulunamadı! Lütfen web arayüzünden yükleyin.")
                return None
            
            creds = _run_oauth_flow(client_config)

        if creds:
            try:
                _set_db_config("auth_token", json.loads(creds.to_json()))
                log.info("Yeni erişim jetonu başarıyla şifreli veritabanına kaydedildi.")
                _auth_url = None
            except Exception as e:
                log.error(f"Jeton veritabanına kaydedilemedi: {e}")

    if not creds:
        return None

    try:
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        log.critical(f"Gmail servisi oluşturulurken hata: {e}")
        return None


def _run_oauth_flow(client_config: Dict[str, Any]) -> Optional[Credentials]:
    """OAuth2 akışını tamamen bellek üzerinden yürütür.

    Bağlantıyı hem terminale basar hem de aktifse SocketIO üzerinden web arayüzüne gönderir.
    Güvenlik uyumsuzluğunu önlemek için tek bir sabit durum değeri üretilir ve kullanılır.

    Args:
        client_config (Dict[str, Any]): İstemci sırlarını barındıran sözlük.

    Returns:
        Optional[Credentials]: Yetkilendirme başarılıysa kimlik bilgileri, değilse None.
    """
    global _auth_url

    try:
        flow: InstalledAppFlow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        port: int = _find_free_port()
        flow.redirect_uri = f"http://localhost:{port}/"

        auth_state: str = base64.urlsafe_b64encode(os.urandom(16)).decode('utf-8').rstrip('=')

        auth_url: str
        auth_url, _ = flow.authorization_url(prompt="consent", state=auth_state)
        _auth_url = auth_url

        from app.utils.logging import _socketio
        if _socketio:
            _socketio.emit("auth_required", {"url": auth_url}, namespace="/logs")
            log.info("🔐 Yetkilendirme gerekiyor — Web arayüzüne bağlantı gönderildi")
        else:
            log.info("🔐 Yetkilendirme gerekiyor — Lütfen terminaldeki bağlantıyı kullanın")

        print("\n" + "=" * 60)
        print("GMAIL YETKİLENDİRMESİ GEREKİYOR")
        print(f"Lütfen aşağıdaki bağlantıyı tarayıcınızda açın:\n\n  {auth_url}\n")
        print("=" * 60 + "\n")

        log.info(f"Yönlendirme bekleniyor (Port: {port})...")

        creds: Optional[Credentials] = flow.run_local_server(
            host="localhost",
            port=port,
            open_browser=False,
            authorization_prompt_message="[SİSTEM] Tarayıcı onayı bekleniyor...",
            success_message="Doğrulama başarılı! Bu sekmeyi artık kapatıp programa dönebilirsiniz.",
            timeout_seconds=600,
            prompt="consent",
            state=auth_state
        )

        _auth_url = None
        if _socketio:
            _socketio.emit("auth_complete", {}, namespace="/logs")

        return creds

    except Exception as e:
        log.warning(f"Otomatik yetkilendirme akışı başarısız oldu: {e}. Manuel moda geçiliyor...")

    try:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
        flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
        
        auth_url, _ = flow.authorization_url(prompt="consent")
        _auth_url = auth_url
        
        from app.utils.logging import _socketio
        if _socketio:
            _socketio.emit("auth_required", {"url": auth_url, "manual": True}, namespace="/logs")

        print(f"\nMANUEL DOĞRULAMA GEREKLİ\nLütfen bu URL'yi ziyaret edin: {auth_url}\n")
        code: str = input("Tarayıcıdan aldığınız kodu buraya yapıştırın: ").strip()
        
        if code:
            flow.fetch_token(code=code)
            _auth_url = None
            return flow.credentials
            
    except Exception as e:
        log.critical(f"Manuel yetkilendirme de başarısız oldu: {e}")

    _auth_url = None
    return None