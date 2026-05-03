"""PDF rapor ayrıştırıcı temel sınıfı."""

import re
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Set, Any, Tuple

from app.utils.text import BUILDING_SUFFIXES


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
        m: Optional[re.Match]
        for p in patterns:
            m = re.search(p, self._text, re.IGNORECASE)
            if m:
                return m.group(1).strip().replace("/", ".")
                
        return None

    def _clean_building_name(self, raw: str) -> Optional[str]:
        """Bina adındaki gürültü verileri temizler.
        
        Args:
            raw (str): Ham metinden ayıklanan bina adı.
            
        Returns:
            Optional[str]: Standartlaştırılmış ve temizlenmiş bina adı veya None.
        """
        if not raw:
            return None
            
        name: str = raw.strip()
        name = re.sub(r"^\d+\s*[/-]\s*\d+\s+", "", name)
        
        if " / " in name:
            name = name.split(" / ")[0].strip()
            
        if len(name) > 8:
            name = re.sub(r"\s+\d+\.?\s*BLOK$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s+[A-Z]\s*BLOK$", "", name, flags=re.IGNORECASE)
            name = re.sub(r"\s+(?:NO|KAPI NO|DAİRE)[:.]\s*\d+.*$", "", name, flags=re.IGNORECASE)
            
        replacements: List[Tuple[str, str]] = [
            (r"APT\.?", "APARTMANI"), 
            (r"\bAPARTMAN\b", "APARTMANI"),
            (r"KONUTLAR$", "KONUTLARI"), 
            (r"SİTE$", "SİTESİ"),
            (r"EVLER$", "EVLERİ"), 
            (r"LOJ\.", "LOJMANLARI")
        ]
        
        pat: str
        rep: str
        for pat, rep in replacements:
            name = re.sub(pat, rep, name, flags=re.IGNORECASE)
            
        name = name.strip(" /-.\\")
        
        if 3 < len(name) < 60:
            return name.upper()
            
        return None

    def _building_pattern(self) -> str:
        """Bina adını yakalamak için son ekleri kullanan dinamik düzenli ifade.
        
        Returns:
            str: Bina adını tespit etmek için kullanılan düzenli ifade örüntüsü.
        """
        return rf"([A-ZĞÜŞİÖÇ0-9][A-ZĞÜŞİÖÇ0-9.\-/ \t]{{0,50}}?(?:{BUILDING_SUFFIXES}))"