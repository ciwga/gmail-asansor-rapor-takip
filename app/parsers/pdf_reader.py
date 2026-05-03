"""
PDF metin ayıklama modülü: Birden fazla yedek strateji ile dayanıklı veri çekimi sağlar.
Bozuk dosyalar, hatalı işaretçiler ve kodlama sorunlarını yönetir.
"""

import io
import os
import re
from contextlib import redirect_stderr
from typing import Optional, List, Any

from pypdf import PdfReader

from app.utils.logging import get_logger

log: Any = get_logger(__name__)

try:
    import pdfplumber
except ImportError:
    pdfplumber: Any = None


def extract_text(file_path: str) -> Optional[str]:
    """Bir PDF dosyasından metin içeriğini ayıklar.
    
    Aşağıdaki stratejileri sırasıyla dener:
      1. Standart okuma.
      2. İşaretçi temizliği sonrası okuma.
      3. Alternatif kütüphane ile okuma.

    Args:
        file_path (str): Metni ayıklanacak PDF dosyasının tam yolu.

    Returns:
        Optional[str]: Normalleştirilmiş metin içeriği veya tüm yöntemler başarısız olursa None.
    """
    if not os.path.exists(file_path):
        log.error(f"Dosya bulunamadı: {file_path}")
        return None

    basename: str = os.path.basename(file_path)

    text: Optional[str] = _try_pypdf(file_path)
    if text:
        return _normalize(text)

    log.warning(f"Standart okuma başarısız oldu ({basename}), onarım deneniyor...")

    text = _try_eof_repair(file_path)
    if text:
        log.info(f"Onarım başarılı oldu: {basename}")
        return _normalize(text)

    if pdfplumber:
        text = _try_pdfplumber(file_path)
        if text:
            log.info(f"Alternatif yöntem ile başarıyla kurtarıldı: {basename}")
            return _normalize(text)

    log.error(f"Tüm PDF okuma stratejileri başarısız oldu: {basename}")
    return None


def _try_pypdf(path: str) -> Optional[str]:
    """Standart kütüphane kullanarak metin ayıklamayı dener.

    Args:
        path (str): Dosya yolu.

    Returns:
        Optional[str]: Ayıklanan metin veya hata durumunda None.
    """
    try:
        with open(path, "rb") as f, open(os.devnull, "w") as null:
            with redirect_stderr(null):
                reader: PdfReader = PdfReader(f)
                pages: List[str] = [p.extract_text() for p in reader.pages]
                pages = [p for p in pages if p]
                return "\n".join(pages) if pages else None
    except Exception as e:
        log.debug(f"Okuma hatası: {e}")
        return None


def _try_eof_repair(path: str) -> Optional[str]:
    """PDF dosyasının sonundaki bozuk verileri temizleyerek okumayı dener.

    Args:
        path (str): Dosya yolu.

    Returns:
        Optional[str]: Onarılmış metin veya başarısız olursa None.
    """
    try:
        with open(path, "rb") as f:
            content: bytes = f.read()

        eof_marker: bytes = b"%%EOF"
        
        if eof_marker not in content:
            return None

        clean_content: bytes = content[: content.rfind(eof_marker) + len(eof_marker)]

        with io.BytesIO(clean_content) as stream, open(os.devnull, "w") as null:
            with redirect_stderr(null):
                reader: PdfReader = PdfReader(stream)
                pages: List[str] = [p.extract_text() for p in reader.pages]
                pages = [p for p in pages if p]
                return "\n".join(pages) if pages else None
    except Exception as e:
        log.debug(f"Onarım hatası: {e}")
        return None


def _try_pdfplumber(path: str) -> Optional[str]:
    """Alternatif kütüphane kullanarak metin ayıklamayı dener.

    Args:
        path (str): Dosya yolu.

    Returns:
        Optional[str]: Ayıklanan metin veya hata durumunda None.
    """
    try:
        if not pdfplumber:
            return None
            
        with pdfplumber.open(path) as pdf:
            pages: List[str] = [p.extract_text() for p in pdf.pages]
            pages = [p for p in pages if p]
            return "\n".join(pages) if pages else None
    except Exception as e:
        log.debug(f"Alternatif okuma hatası: {e}")
        return None


def _normalize(text: str) -> str:
    """Metin içerisindeki yapısal boşlukları temizler.

    Args:
        text (str): İşlenecek ham metin.

    Returns:
        str: Temizlenmiş ve düzenlenmiş metin.
    """
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    
    return text.strip()