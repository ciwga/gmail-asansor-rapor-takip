"""
Türkçe karakter duyarlı metin yardımcı araçları.
Standart kütüphanenin hatalı işlediği Türkçe karakterleri ve 
dosya sistemi güvenliği işlemlerini yönetir.
"""

import os
import re
from urllib.parse import unquote
from typing import Dict, Any

_TR_UPPER_TO_LOWER: Dict[int, Any] = str.maketrans("İIĞÜŞÖÇ", "iığüşöç")


def to_lower_tr(text: str) -> str:
    """Türkçe karakterleri doğru şekilde küçük harfe dönüştürür.

    Args:
        text (str): Dönüştürülecek metin.

    Returns:
        str: Türkçe kurallarına uygun olarak küçük harfe çevrilmiş metin.
    """
    if not text:
        return ""
        
    return text.translate(_TR_UPPER_TO_LOWER).lower()


def sanitize_filename(filename: str) -> str:
    """Dosya adındaki güvenli olmayan karakterleri temizler.

    Args:
        filename (str): Temizlenecek ham dosya adı veya yolu.

    Returns:
        str: İşletim sistemi için güvenli hale getirilmiş dosya adı.
    """
    name: str = os.path.basename(unquote(filename))
    
    return re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", name)


BUILDING_SUFFIXES: str = (
    r"APARTMANI|\bAPT\.?|SİTESİ|KONUTLARI|EVLERİ|LOJ\.?|LOJMANLARI|"
    r"\bOTEL\b|PANSİYON|VİLLALARI|KÖŞKÜ|KÖŞKÜSÜ|BİNASI|BİNA|YURDU|"
    r"\bYURT\b|KAMPÜSÜ|KAMPÜS|REZİDANS|DAİRELERİ|DAİRESİ|APARTMAN|"
    r"KONUT|\bEV\b|VİLLA|PLAZA|PLAZASI|İŞ MERKEZİ|İŞ HANI|\bHANI\b|"
    r"BLOK|BLOĞU|KONAK|KONAĞI|SARAY|SARAYI|YALI|YALISI|PASAJ|PASAJI|"
    r"PALAS|PALASI|APART|OTELİ|REZİDANSI|LİSESİ|OKULU|KOLEJİ|"
    r"HASTANESİ|\bMERKEZİ\b"
)