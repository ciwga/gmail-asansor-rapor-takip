"""
Ortak indirme yardımcıları: HTTP üzerinden dosya indirme ve kaydetme işlemlerini yönetir.
"""

import os
import re
from typing import Optional, Tuple, Dict, Any

import requests

from app.utils.text import sanitize_filename
from app.utils.logging import get_logger

log: Any = get_logger(__name__)

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS: Dict[str, str] = {"User-Agent": USER_AGENT}
DEFAULT_TIMEOUT: int = 30


def save_pdf(
    response: requests.Response,
    default_name: str,
    folder: str,
) -> Tuple[Optional[str], str]:
    """HTTP yanıt içeriğini PDF dosyası olarak belirtilen klasöre kaydeder.

    İşlem sırasında içerik başlığından dosya adını çekmeye çalışır,
    başarısız olursa varsayılan ismi kullanır. Dosya zaten mevcutsa yazma işlemini atlar.

    Args:
        response (requests.Response): İndirme isteğinden dönen HTTP yanıt nesnesi.
        default_name (str): Dosya adı bulunamazsa kullanılacak varsayılan isim.
        folder (str): Dosyanın kaydedileceği hedef klasör yolu.

    Returns:
        Tuple[Optional[str], str]: Dosya yolu ve durum ikilisi. 
            Durum şunlardan biri olabilir: 'downloaded', 'skipped', 'failed'.
    """
    try:
        os.makedirs(folder, exist_ok=True)

        fname: str = default_name
        cd: str = response.headers.get("content-disposition", "")
        
        if cd:
            m: Optional[re.Match] = re.search(r'filename="?([^"]+)"?', cd)
            if m:
                try:
                    fname = m.group(1).encode("latin1").decode("utf-8", errors="ignore")
                except Exception:
                    pass

        safe: str = sanitize_filename(fname)
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"

        path: str = os.path.join(folder, safe)

        if os.path.exists(path):
            return path, "skipped"

        with open(path, "wb") as f:
            f.write(response.content)

        return path, "downloaded"

    except Exception as e:
        log.error(f"PDF kaydetme hatası '{default_name}': {e}")
        return None, "failed"


def is_pdf_response(response: requests.Response) -> bool:
    """HTTP yanıtının geçerli bir PDF içeriği olup olmadığını kontrol eder.

    Args:
        response (requests.Response): Kontrol edilecek HTTP yanıtı.

    Returns:
        bool: Eğer içerik tipi başlığı PDF belirtiyorsa True, aksi halde False.
    """
    return "application/pdf" in response.headers.get("Content-Type", "")