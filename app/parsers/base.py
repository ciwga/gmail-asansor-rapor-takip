"""PDF rapor ayrıştırıcı temel sınıfı."""

import re
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Set, Match

from app.utils.text import BUILDING_FULL_PATTERN


class BaseParser(ABC):
    """Farklı sağlayıcılardan gelen PDF raporlarını işlemek için soyut temel sınıf.

    Attributes:
        provider_name (str): Raporu sağlayan kuruluşun adı.
        _text (str): PDF dosyasından ayıklanmış ham metin içeriği.
        _decisions (List[Dict[str, str]]): Rapordan ayıklanan kusur ve karar maddeleri.
    """

    provider_name: str = "Bilinmeyen"

    def __init__(self, text: str) -> None:
        """BaseParser örneğini ham metin ile başlatır ve kararları ayrıştırır.

        Args:
            text (str): PDF'den ayıklanmış metin.
        """
        self._text: str = text
        self._decisions: List[Dict[str, str]] = []
        self._parse_decisions()

    @abstractmethod
    def _parse_decisions(self) -> None:
        """PDF metninden kusurları ayıklar."""
        pass

    @abstractmethod
    def extract_building_name(self) -> Optional[str]:
        """PDF metninden bina adını çıkarır.

        Returns:
            Optional[str]: Bulunan bina adı veya bulunamazsa None.
        """
        pass

    @property
    def label_color(self) -> str:
        """Ayıklanan kararlara göre raporun etiket rengini belirler.
        
        Returns:
            str: Etiket rengi.
        """
        if not self._decisions:
            return "Yeşil"
        
        categories: Set[str] = {d["category"] for d in self._decisions}
        
        if "K" in categories:
            return "Kırmızı"
        if "S" in categories:
            return "Sarı"
        if "M" in categories:
            return "Mavi"
            
        return "Yeşil"

    def extract_elevator_number(self) -> Optional[str]:
        """Metin içerisinden asansör kimlik numarasını ayıklar.
        
        Returns:
            Optional[str]: Bulunan asansör numarası veya None.
        """
        clean_text: str = self._text
        uuid_pattern: str = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        
        clean_text = re.sub(uuid_pattern, "", clean_text)
        
        matches: List[str] = re.findall(r"\b\d{7,12}\s*[/-]\s*\d{1,2}\b", clean_text)
        return matches[0] if matches else None

    def extract_uuid(self) -> Optional[str]:
        """Raporun benzersiz doğrulama kodunu ayıklar.
        
        Returns:
            Optional[str]: Bulunan doğrulama kodu dizgesi veya None.
        """
        pattern: str = r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}"
        matches: List[str] = re.findall(pattern, self._text)
        return matches[0] if matches else None

    def extract_inspection_date(self) -> Optional[str]:
        """Muayene tarihini metin içerisinde arayıp çıkarır.
        
        Returns:
            Optional[str]: Formatlanmış tarih veya None.
        """
        patterns: List[str] = [
            r"R\.[A-Z]{3}\.\d{2}\.\d+[\s\S]{,100}?(\d{2}[./]\d{2}[./]\d{4})",
            r"PER[İI\s]*YOD[İI\s]*K\s*KONTROL\s*TAR[İI\s]*H[İI\s]*[\s\S]{,150}?(\d{2}[./]\d{2}[./]\d{4})",
            r"TAK[İI\s]*P\s*KONTROL[ÜU\s]*TAR[İI\s]*H[İI\s]*[\s\S]{,150}?(\d{2}[./]\d{2}[./]\d{4})",
            r"PER[İI]YOD[İI]K\s+KONTROL\s+TAR[İI]H[İI][\s\S]{,100}?(\d{2}[./]\d{2}[./]\d{4})",
            r"PER[İI]YOD[İI]K\s+KONTROL\s*[\n\s]*(\d{2}[./]\d{2}[./]\d{4})",
        ]
        
        p: str
        m: Optional[Match[str]]
        for p in patterns:
            m = re.search(p, self._text, re.IGNORECASE)
            if m:
                return m.group(1).strip().replace("/", ".")
                
        return None

    def _clean_building_name(self, raw_name: str) -> str:
        """Ham bina adını temizler ve standartlaştırır.
        
        Tüm extractor'lar tarafından paylaşılan ortak temizleme mantığı:
        1. Başta gelen ID numaralarını (xxxxx/x) temizler.
        2. " / " sonrası blok bilgilerini temizler.
        3. Sondaki BLOK/NO detaylarını temizler.
        4. APT -> APARTMANI vb. standartlaştırma yapar.
        
        Args:
            raw_name (str): Regex ile yakalanan ham bina veya kurum adı.
            
        Returns:
            str: Temizlenmiş ve büyük harfe dönüştürülmüş bina adı veya hatalıysa boş string.
        """
        if not raw_name:
            return ""
        
        cleaned: str = raw_name.strip()
        
        cleaned = re.sub(r'^\d+\s*[\/-]\s*\d+\s+', '', cleaned)
        
        if " / " in cleaned:
            parts: List[str] = cleaned.split(" / ")
            cleaned = parts[0].strip()
        
        if len(cleaned) > 8:
            cleaned = re.sub(r'\s+\d+\.?\s*BLOK$', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+[A-Z]\s*BLOK$', '', cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r'\s+(?:NO|KAPI NO|DAİRE)[:\.]?\s*\d+.*$', '', cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"APT\.?", "APARTMANI", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\bAPARTMAN\b", "APARTMANI", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"KONUTLAR$", "KONUTLARI", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"SİTE$", "SİTESİ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"EVLER$", "EVLERİ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"LOJ\.", "LOJMANLARI", cleaned, flags=re.IGNORECASE)
        
        cleaned = re.sub(r"İNŞ\.\s*$", "İNŞ.", cleaned, flags=re.IGNORECASE)
        
        cleaned = cleaned.strip(" /-.\\")
        
        if 3 < len(cleaned) < 150:
            return cleaned.upper()
        
        return ""

    def _building_pattern(self) -> str:
        """Bina adını yakalamak için son ekleri ve zincir yapısını kullanan dinamik düzenli ifade.
        
        Returns:
            str: Zincirleme kurum/bina adını tespit etmek için kullanılan düzenli ifade örüntüsü.
        """
        return BUILDING_FULL_PATTERN