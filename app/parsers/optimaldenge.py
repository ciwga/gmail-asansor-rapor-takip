"""Optimal Denge Teknik Denetim A.Ş. PDF raporları için ayrıştırıcı modülü."""

import re
from typing import Optional, List, Dict, Set, Match, Pattern, cast, Tuple

from app.parsers.base import BaseParser


class OptimalDengeParser(BaseParser):
    """Optimal Denge formatındaki asansör periyodik kontrol raporlarını ayrıştırır.

    Attributes:
        provider_name (str): Sağlayıcı kuruluş adı (Örn: "Optimal Denge").
    """

    provider_name: str = "Optimal Denge"

    def _parse_decisions(self) -> None:
        """PDF metninden kontrol sonuçlarını ve kusur maddelerini ayıklar."""
        self._decisions: List[Dict[str, str]] = []
        
        if not self._text:
            return

        inline_pattern: Pattern[str] = re.compile(
            r"(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s*\(([KMS])\)\s*(.*?)(?=\n\s*\d{1,2}\.\d{1,2}|$)",
            re.DOTALL | re.MULTILINE,
        )
        
        seen_codes: Set[str] = set()
        
        code: str
        cat: str
        content: str
        
        for code, cat, content in inline_pattern.findall(self._text):
            clean_content: str = re.sub(r"\s+", " ", content).strip()
            clean_content = re.sub(r"Sayfa \d+\s*/\s*\d+", "", clean_content).strip()
            
            if clean_content and code not in seen_codes:
                seen_codes.add(code)
                self._decisions.append({
                    "category": cat,
                    "content": f"{code} - {clean_content}"
                })

        if not self._decisions:
            pattern2: Pattern[str] = re.compile(
                r"\(([KMS])\)\s*(\d{1,2}\.\d{1,2}(?:\.\d{1,2})?)\s+(.*?)"
                r"(?=\n\s*(?:\([KMS]\)|\d{1,2}\.\d{1,2})|Total|Toplam|$)",
                re.DOTALL | re.MULTILINE,
            )
            for cat, code, content in pattern2.findall(self._text):
                clean_content = re.sub(r"\s+", " ", content).strip()
                if clean_content and code not in seen_codes:
                    seen_codes.add(code)
                    self._decisions.append({
                        "category": cat,
                        "content": f"{code} - {clean_content}"
                    })

    @property
    def label_color(self) -> str:
        """Ayıklanan kusurların ciddiyetine göre rapor etiket rengini belirler.
        
        Returns:
            str: Belirlenen etiket rengi ("Kırmızı", "Sarı", "Mavi" veya "Etiket Bulunamadı").
        """
        if not self._decisions:
            return "Etiket Bulunamadı"
            
        categories: Set[str] = {d["category"] for d in self._decisions}
        
        if "K" in categories:
            return "Kırmızı"
        if "S" in categories:
            return "Sarı"
        if "M" in categories:
            return "Mavi"
            
        return "Etiket Bulunamadı"

    def extract_building_name(self) -> Optional[str]:
        """Adres satırı verisinden bina adını ayıklar.

        Returns:
            Optional[str]: Temizlenmiş bina adı veya bulunamazsa None.
        """
        if not self._text:
            return None

        match: Optional[Match[str]] = re.search(
            r"ADRES:\s*(.*?)(?=\n|ADA[\u2010\u2013\- ]PARSEL|BİNA SORUMLUSU|$)",
            self._text, re.IGNORECASE | re.DOTALL,
        )
        
        if not match:
            return None

        full_address: str = re.sub(r"\s+", " ", cast(str, match.group(1)).strip())

        suffix_match: Optional[Match[str]] = re.search(
            r"^(.*?(?:\b(?:APARTMANI|SİTESİ|KONUTLARI|EVLERİ|LOJMANLARI|MERKEZİ|"
            r"İŞ HANI|HANI|PLAZA|REZİDANS|PALAS|OKULU|HASTANESİ|KOLEJİ)\b"
            r"|\bAPT\.?(?=\s|$)))",
            full_address, re.IGNORECASE,
        )
        
        raw_name: str = ""
        
        if suffix_match:
            raw_name = cast(str, suffix_match.group(1)).strip()
        else:
            separator_match: Optional[Match[str]] = re.search(
                r"\sMAH\b|\sMAHALLESİ|\sCAD\b|\sCD\b|\sSOK\b|\sSK\b|\sNO\b|\sNO:",
                full_address, re.IGNORECASE,
            )
            raw_name = full_address[:separator_match.start()].strip() if separator_match else full_address

        raw_name = re.sub(r"\s*\([^)]+\)\s*", " ", raw_name).strip()
        
        return self._clean_building_name(raw_name) if raw_name else None

    def extract_elevator_number(self) -> Optional[str]:
        """Asansör kimlik numarasını ayıklar.

        Returns:
            Optional[str]: Temizlenmiş numara formatı (örn: 1234567/12) veya bulunamazsa
                           üst sınıftan (BaseParser) dönen değer veya None.
        """
        if not self._text:
            return None

        match: Optional[Match[str]] = re.search(
            r"KİMLİK\s*NUMARASI\s*\n*\s*(\d{7,12})\s*([/\-\u2010\u2013])\s*(\d{1,2})",
            self._text, re.IGNORECASE | re.DOTALL,
        )
        
        if match:
            return f"{cast(str, match.group(1))}/{cast(str, match.group(3))}"

        match2: Optional[Match[str]] = re.search(r"(\d{7,12})\s*[\u2010\u2013]\s*(\d{1,2})", self._text)
        
        if match2:
            return f"{cast(str, match2.group(1))}/{cast(str, match2.group(2))}"

        return super().extract_elevator_number()

    def extract_uuid(self) -> Optional[str]:
        """Rapor benzersiz kimlik bilgisini (UUID) ayıklar.

        Returns:
            Optional[str]: Standart tireli benzersiz kimlik (UUID) veya bulunamazsa 
                           üst sınıftan (BaseParser) dönen değer.
        """
        if not self._text:
            return None
            
        uuid_match: Optional[Match[str]] = re.search(
            r"([0-9a-fA-F]{8})[\-\u2010\u2013]([0-9a-fA-F]{4})[\-\u2010\u2013]([0-9a-fA-F]{4})[\-\u2010\u2013]([0-9a-fA-F]{4})[\-\u2010\u2013]([0-9a-fA-F]{12})",
            self._text,
        )
        
        if uuid_match:
            return "-".join(cast(Tuple[str, ...], uuid_match.groups()))
            
        return super().extract_uuid()

    def extract_inspection_date(self) -> Optional[str]:
        """Rapor içerisinden muayene tarihini ayıklar.

        Returns:
            Optional[str]: Formatlanmış tarih veya bulunamazsa üst sınıftan 
                           (BaseParser) dönen değer.
        """
        if not self._text:
            return None

        def format_date(match_obj: Match[str]) -> str:
            """Tarih dizgisini standart formata (gg/aa/yyyy) getirir.
            
            Args:
                match_obj (Match[str]): Regex eşleşme objesi.
                
            Returns:
                str: Sıfırlarla doldurulmuş ve bölü (/) ile ayrılmış tarih.
            """
            raw_date: str = cast(str, match_obj.group(1)).replace(".", "/")
            parts: List[str] = raw_date.split("/")
            
            if len(parts) == 3:
                return f"{parts[0].zfill(2)}/{parts[1].zfill(2)}/{parts[2]}"
            return raw_date

        follow_up_match: Optional[Match[str]] = re.search(
            r"TAK[İI]P\s*KONTROL[ÜU]\s*TAR[İI]H[İI]\s*:?\s*\n*\s*(\d{1,2}[./]\d{1,2}[./]\d{4})", 
            self._text, re.IGNORECASE
        )
        
        if follow_up_match:
            return format_date(follow_up_match)

        date_patterns: List[str] = [
            r"DEN[Ee]T[İI]M\s*TAR[İI]H[İI]\s*:?\s*\n*\s*(\d{1,2}[./]\d{1,2}[./]\d{4})",
            r"PER[İI]YOD[İI]K\s+KONTROL\s+TAR[İI]H[İI]\s*:?\s*\n*\s*(\d{1,2}[./]\d{1,2}[./]\d{4})",
        ]
        
        pattern: str
        for pattern in date_patterns:
            inspection_match: Optional[Match[str]] = re.search(pattern, self._text, re.IGNORECASE)
            
            if inspection_match:
                return format_date(inspection_match)

        return super().extract_inspection_date()