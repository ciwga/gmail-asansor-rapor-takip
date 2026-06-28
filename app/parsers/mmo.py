"""Makina Mühendisleri Odası PDF raporları için ayrıştırıcı modülü."""

import re
from typing import Optional, List, Dict, cast

from app.parsers.base import BaseParser


class MmoParser(BaseParser):
    """Makina Mühendisleri Odası formatındaki asansör raporlarını ayrıştıran sınıf.

    Attributes:
        provider_name (str): Sağlayıcı adı (Örn: "MMO").
    """

    provider_name: str = "MMO"

    def _parse_decisions(self) -> None:
        """PDF metninden muayene kararlarını ve kusur listesini ayıklar.
        
        Metin içindeki belirli numaralandırma ve yıldız (* veya **) desenlerini 
        kullanarak her bir muayene kararını bulur, kategorisine göre etiketler 
        (K, S, M) ve sınıfın _decisions listesine kaydeder.
        """
        self._decisions: List[Dict[str, str]] = []
        
        if not self._text:
            return

        lines: List[str] = self._text.split("\n")
        i: int = 0
        
        while i < len(lines):
            line: str = lines[i].strip()
            
            if re.match(r"^\d+\)\d+(?:\.\d+)+", line):
                cat: str = "K" if "-**" in line else ("S" if "-*" in line else "M")
                full_content: str = line
                i += 1
                
                while i < len(lines) and not re.match(r"^\d+\)\d+", lines[i].strip()):
                    full_content += " " + lines[i].strip()
                    i += 1

                cleaned_text: str = re.sub(r"^\d+\)\d+(?:\.\d+)+-?\\*?\\*?\\s*", "", full_content).strip()
                
                if cleaned_text:
                    self._decisions.append({"category": cat, "content": cleaned_text})
                
                i -= 1
            i += 1

    def extract_building_name(self) -> Optional[str]:
        """PDF metninden bina adını ayıklar.

        Returns:
            Optional[str]: Temizlenmiş bina adı. Eğer eşleşme veya metin bulunamazsa None döner.
        """
        if not self._text:
            return None

        anchor: Optional[re.Match[str]] = re.search(
            r"ASANSÖRE\s*İLİŞKİN\s*BİLGİLER", self._text, re.IGNORECASE
        )
        
        if not anchor:
            return None

        start_index: int = anchor.end()
        search_area: str = self._text[start_index : start_index + 500]
        
        bp: str = self._building_pattern()
        m: Optional[re.Match[str]] = re.search(r"\b" + bp + r"\b", search_area, re.IGNORECASE)
        
        if m:
            return self._clean_building_name(cast(str, m.group(1)))

        return None