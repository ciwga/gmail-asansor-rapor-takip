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
    r'ÜNİVERSİTESİ|İŞ MERKEZİ|LOJMANLARI|DAİRELERİ|HASTANESİ|REKTÖRLÜĞÜ|'
    r'BAŞKANLIĞI|APARTMANI|KONUTLARI|VİLLALARI|MÜDÜRLÜĞÜ|ENSTİTÜSÜ|BAKANLIĞI|'
    r'TESİSLERİ|FAKÜLTESİ|ORTAOKULU|REZİDANSI|PANSİYON|APARTMAN|İLKOKULU|'
    r'ANAOKULU|KAMPÜSÜ|REZİDANS|DAİRESİ|PLAZASI|İŞ HANI|KÖŞKÜSÜ|ŞEFLİĞİ|KOLEJİ|'
    r'KURUMU|BİNASI|MERKEZİ|LİSESİ|SARAYI|YALISI|PASAJI|PALASI|SİTESİ|EVLERİ|'
    r'KÖŞKÜ|KAMPÜS|PLAZA|BLOĞU|KONAK|KONAĞI|SARAY|PASAJ|PALAS|OTELİ|CAMİSİ|'
    r'YURDU|HANI|BLOK|YALI|YURT|OTEL|BİNA|APT\.?|LOJ\.?|İNŞ\.?|CAMİİ|KONUT|'
    r'VİLLA|APART|OKULU|EV'
)
BUILDING_FULL_PATTERN: str = rf"([A-ZĞÜŞİÖÇa-zğüşıöç0-9][A-ZĞÜŞİÖÇa-zğüşıöç0-9.\-/ \t]{{1,150}}(?:{BUILDING_SUFFIXES}))"