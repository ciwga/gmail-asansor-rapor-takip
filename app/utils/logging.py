"""Günlükleme sistemi: Çıktıları terminal, yerel dosya ve canlı akış kanallarına yönlendirir."""

import logging
import queue
import re
from typing import Optional, List, Dict, Any, Tuple

try:
    from colorama import init, Fore, Style, Back
    init(autoreset=True)
except ImportError:
    class _Dummy:
        """Kütüphane bulunmadığında hata oluşmasını engelleyen yardımcı sınıf."""
        def __getattr__(self, name: str) -> str:
            return ""
            
    Fore: Any = _Dummy()
    Style: Any = _Dummy()
    Back: Any = _Dummy()

logging.getLogger("pypdf").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.ERROR)

_log_queue: queue.Queue = queue.Queue(maxsize=5000)
_socketio: Optional[Any] = None
_logging_configured: bool = False


def set_socketio(sio: Any) -> None:
    """Gerçek zamanlı log akışını etkinleştirmek için sunucu tarafından çağrılır.

    Args:
        sio (Any): Aktif sunucu örneği.
    """
    global _socketio
    _socketio = sio


class ColorFormatter(logging.Formatter):
    """Terminal çıktıları için renk kodlarını kullanan biçimlendirici.

    Attributes:
        _COLORS (Dict[int, Any]): Log seviyeleri ve renk eşleşmeleri.
    """
    _COLORS: Dict[int, Any] = {
        logging.DEBUG: Fore.CYAN,
        logging.INFO: Fore.WHITE,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Back.RED + Fore.WHITE + Style.BRIGHT,
    }

    def format(self, record: logging.LogRecord) -> str:
        """Log kaydını renklendirerek biçimlendirir.

        Args:
            record (logging.LogRecord): İşlenecek log kaydı nesnesi.

        Returns:
            str: Renklendirilmiş log satırı.
        """
        color: Any = self._COLORS.get(record.levelno, Fore.WHITE)
        record.levelname = f"{color}{record.levelname:<8}{Style.RESET_ALL}"
        
        if record.levelno >= logging.WARNING:
            record.msg = f"{color}{record.msg}{Style.RESET_ALL}"
            
        return super().format(record)


class WebSocketHandler(logging.Handler):
    """Log kayıtlarını bellek içi kuyruk üzerinden istemcilere iletir."""

    _IGNORE_PATTERNS: Tuple[str, ...] = (
        "socket.io", "GET /socket", "POST /socket", "polling",
        "Invalid session", "Session is disconnected", "engineio"
    )

    def emit(self, record: logging.LogRecord) -> None:
        """Gelen log kaydını web arayüzüne gönderilmek üzere işler.

        Args:
            record (logging.LogRecord): Yayınlanacak log kaydı.
        """
        try:
            msg: str = record.getMessage()
            
            if any(p in msg for p in self._IGNORE_PATTERNS):
                return

            _update_server_progress(msg)

            entry: Dict[str, str] = {
                "time": self.format(record).split("|")[0].strip(),
                "level": record.levelname.upper(),
                "message": msg,
            }
            
            try:
                _log_queue.put_nowait(entry)
            except queue.Full:
                try:
                    _log_queue.get_nowait()
                    _log_queue.put_nowait(entry)
                except queue.Empty:
                    pass

            if _socketio:
                _socketio.emit("log", entry, namespace="/logs")
        except Exception:
            pass


def _update_server_progress(msg: str) -> None:
    """Log mesajlarını analiz ederek sunucu tarafındaki işlem sayacını günceller.

    Args:
        msg (str): Analiz edilecek log mesajı metni.
    """
    try:
        from app.web import server as srv
        p: Dict[str, Any] = srv._progress

        if "e-posta içeriği çekiliyor" in msg:
            m: Optional[re.Match] = re.search(r"(\d+)\s*e-posta", msg)
            if m:
                p["total"] = int(m.group(1))
                p["done"] = 0
                p["phase"] = "fetch"

        elif "Worker başlatılıyor" in msg:
            m = re.search(r"\((\d+)\s*e-posta\)", msg)
            if m:
                p["total"] = int(m.group(1))
                p["done"] = 0
                p["phase"] = "process"

        elif "İndirme (" in msg and any(x in msg for x in ["mevcut", "indirildi", "başarısız"]):
            p["done"] = p.get("done", 0) + 1
            p["phase"] = "process"

        elif "RANDEVU:" in msg:
            p["done"] = p.get("done", 0) + 1
            p["phase"] = "process"

        elif "İşlem tamamlandı" in msg:
            p["done"] = p.get("total", 0)
            p["phase"] = "done"

        elif "Sonuç bulunamadı" in msg:
            p["phase"] = "done"

    except Exception:
        pass


def get_recent_logs(count: int = 200) -> List[Dict[str, str]]:
    """Arayüz yüklendiğinde gösterilmek üzere son log kayıtlarını döndürür.

    Args:
        count (int): Döndürülecek maksimum kayıt sayısı.

    Returns:
        List[Dict[str, str]]: Log kayıtlarını içeren sözlük listesi.
    """
    items: List[Dict[str, str]] = list(_log_queue.queue)
    return items[-count:]


def setup_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Kök günlükleyiciyi konsol, dosya ve bağlantı kanalları için yapılandırır.

    Args:
        level (str): Günlükleme seviyesi.
        log_file (Optional[str]): Logların yazılacağı yerel dosya yolu.
    """
    global _logging_configured
    if _logging_configured:
        return
        
    _logging_configured = True

    root: logging.Logger = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    fmt: str = "%(asctime)s | %(levelname)-8s | %(message)s"
    datefmt: str = "%Y-%m-%d %H:%M:%S"

    console: logging.StreamHandler = logging.StreamHandler()
    console.setFormatter(ColorFormatter(fmt, datefmt=datefmt))
    root.addHandler(console)

    if log_file:
        import os
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_h: logging.FileHandler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        file_h.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
        root.addHandler(file_h)

    ws_handler: WebSocketHandler = WebSocketHandler()
    ws_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(ws_handler)

    class _SocketIOFilter(logging.Filter):
        _NOISE: Tuple[str, ...] = ("socket.io", "/socket.io/", "Invalid session", "Session is disconnected")
        
        def filter(self, record: logging.LogRecord) -> bool:
            msg: str = record.getMessage()
            return not any(p in msg for p in self._NOISE)

    wz_logger: logging.Logger = logging.getLogger("werkzeug")
    wz_logger.addFilter(_SocketIOFilter())
    
    logging.getLogger("engineio").setLevel(logging.CRITICAL)
    logging.getLogger("socketio").setLevel(logging.CRITICAL)


def get_logger(name: str = "") -> logging.Logger:
    """Belirtilen isimle bir günlükleyici nesnesi döndürür.

    Args:
        name (str): Günlükleyici adı.

    Returns:
        logging.Logger: Günlükleme işlemlerinde kullanılacak nesne.
    """
    return logging.getLogger(name)