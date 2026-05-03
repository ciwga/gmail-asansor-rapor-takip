"""Artibel Belgelendirme PDF raporları için ayrıştırıcı modülü."""

import re
from typing import Optional, List, Dict, Any

from app.parsers.base import BaseParser


class ArtibelParser(BaseParser):
    """Artibel Belgelendirme formatındaki asansör periyodik kontrol raporlarını ayrıştırır.

    Attributes:
        provider_name (str): Sağlayıcı kuruluş adı.
    """

    provider_name: str = "Artibel"

    def _parse_decisions(self) -> None:
        """Rapor metninden kontrol sonuçlarını ayıklar."""
        self._decisions: List[Dict[str, str]] = []

        pattern: str = r"\(([KSM])\)\s+[\d.]+\s+(.*?)(?=\s*\([KSM]\)|$)"
        m: re.Match
        for m in re.finditer(pattern, self._text, re.DOTALL | re.IGNORECASE):
            if "REPORT" not in m.group(2).upper():
                content: str = re.sub(r"\s*\d+\s*-.*$", "", m.group(2).strip(), flags=re.DOTALL)
                self._decisions.append({
                    "category": m.group(1).upper(),
                    "content": content.strip(),
                })

        if not self._decisions:
            upper: str = self._text.upper()
            if "GÜVENSİZ" in upper or "GUVENSIZ" in upper:
                self._decisions.append({"category": "K", "content": "Güvensiz"})
            elif "KUSURLU" in upper and "HAFİF KUSURLU" not in upper and "HAFIF KUSURLU" not in upper:
                self._decisions.append({"category": "S", "content": "Kusurlu"})
            elif "HAFİF KUSURLU" in upper or "HAFIF KUSURLU" in upper:
                self._decisions.append({"category": "M", "content": "Hafif Kusurlu"})
            elif "UYGUN" in upper:
                self._decisions.append({"category": "M", "content": "Uygun"})

    def extract_inspection_date(self) -> Optional[str]:
        """Raporun muayene tarihini ayıklar.

        Returns:
            Optional[str]: Bulunan tarih veya bulunamazsa None.
        """
        if self._text:
            m: Optional[re.Match] = re.search(
                r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\s+(\d{2}[./]\d{2}[./]\d{4})",
                self._text, re.IGNORECASE,
            )
            if m:
                return m.group(1).strip()
        
        return super().extract_inspection_date()

    def extract_building_name(self) -> Optional[str]:
        """Rapor metninden bina adını ayıklar.

        Returns:
            Optional[str]: Temizlenmiş bina adı veya bulunamazsa None.
        """
        if not self._text:
            return None

        m: Optional[re.Match] = re.search(r"-\s*(?P<name>[^-]+?)\s*-\s*Tesis", self._text, re.IGNORECASE)
        if m:
            return self._clean_building_name(m.group("name"))

        section_match: Optional[re.Match] = re.search(
            r"BİNA\s*SORUMLUSUNA\s*İLİŞKİN\s*BİLGİLER(.*?)(?:YETKİLİ|SERVİSE)",
            self._text, re.DOTALL | re.IGNORECASE,
        )
        
        area: str = section_match.group(1) if section_match else self._text
        
        bp: str = self._building_pattern()
        g: Optional[re.Match] = re.search(r"\b" + bp + r"\b", area, re.IGNORECASE)
        
        if g:
            return self._clean_building_name(g.group(1))

        return None