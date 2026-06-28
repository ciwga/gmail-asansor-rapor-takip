"""Kent Grup ve Asansör Kontrol PDF raporları için ayrıştırıcı modülü."""

import re
from typing import Optional, List, Dict, Set, Pattern, Match

from app.parsers.base import BaseParser


class AdetsisParser(BaseParser):
    """Adetsis formatındaki asansör periyodik kontrol raporlarını ayrıştırır.

    Attributes:
        provider_name (str): Sağlayıcı kuruluş adı.
    """

    provider_name: str = "Adetsis"

    def _parse_decisions(self) -> None:
        """PDF içerisindeki kararları ayrıştırır.
        
        Kırmızı, Sarı ve Mavi etiketlerinin haricinde; Yeşil etiketli 
        raporlar için özel onay kutusu ve uygunluk kelimesi tespiti yapar.
        """
        self._decisions: List[Dict[str, str]] = []
        
        if not self._text:
            return

        standalone: List[str] = re.findall(r"^\s*(\([KSM]\).*?)$", self._text, re.MULTILINE)

        blocks: List[str] = re.split(r"(^\d+\s*-\s*)", self._text, flags=re.MULTILINE)
        numbered: List[str] = []
        i: int = 1
        
        while i < len(blocks):
            if i + 1 < len(blocks):
                numbered.append(blocks[i] + blocks[i + 1])
            i += 2

        item: str
        for item in standalone + numbered:
            cat: str = "K" if "(K)" in item else "S" if "(S)" in item else "M" if "(M)" in item else ""
            if not cat:
                continue

            parts: List[str] = item.split(" - ", 1)
            cleaned: str = parts[1] if re.match(r"^\d+\s*-", item) and len(parts) > 1 else item
            cleaned = cleaned.replace("(K)", "").replace("(S)", "").replace("(M)", "").strip()
            
            cleaned = re.split(r"\d{2}\s*/\s*\d{2}\s*/\s*\d{4}", cleaned)[0].strip()

            if cleaned and "RAPOR" not in cleaned.upper():
                self._decisions.append({"category": cat, "content": cleaned})

        if not self._decisions:
            if re.search(r"(?:X|☑)[\s\S]{1,60}UYGUN", self._text, re.IGNORECASE) or \
               re.search(r"UYGUN[\s\S]{1,60}(?:X|☑)", self._text, re.IGNORECASE):
                self._decisions.append({"category": "Y", "content": "Uygun (Kusursuz)"})
            
            elif re.search(r"PER[İI\s]*YOD[İI\s]*K[\s\S]{1,100}SONUCUNUN\s+TANIMI", self._text, re.IGNORECASE):
                if not re.search(r"\([KSM]\)", self._text):
                    self._decisions.append({"category": "Y", "content": "Uygun (Kusursuz)"})

    @property
    def label_color(self) -> str:
        """Ayrıştırılan kusurlara göre raporun nihai etiket rengini belirler.
        
        Returns:
            str: Belirlenen etiket rengi.
        """
        self._parse_decisions()
        
        if not self._decisions:
            return "Etiket Bulunamadı"
            
        categories: Set[str] = {d["category"] for d in self._decisions}
        
        if "K" in categories:
            return "Kırmızı"
        if "S" in categories:
            return "Sarı"
        if "M" in categories:
            return "Mavi"
        if "Y" in categories:
            return "Yeşil"
            
        return "Etiket Bulunamadı"

    def extract_building_name(self) -> Optional[str]:
        """PDF metni içerisinden bina adını ayıklar.
        
        Adres çıkarımı için pdf_base_extractor içerisindeki gelişmiş mantık referans alınmıştır.
        Bu strateji ID'lerin ve Blok bilgisinin güvenli bir şekilde metinden sıyrılmasını sağlar.

        Returns:
            Optional[str]: Temizlenmiş ve standartlaştırılmış bina adı veya None.
        """
        if not self._text:
            return None

        bp: str = self._building_pattern()

        addr_regex: Pattern[str] = re.compile(
            r'\(\s*'
            r'(?:\([^)]+\)\s*)?'           # Opsiyonel iç parantez: (xxxxx/xx)
            r'(?:\d+\s*/\s*\d+\s+)?'       # Opsiyonel düz ID: xxxxx/x
            r'(?P<bina_adi>' + bp + r')'
            r'\s*(?:/[^)]*)?'              # Opsiyonel blok bilgisi
            r'\s*\)',
            re.IGNORECASE
        )
        
        m: Optional[Match[str]] = addr_regex.search(self._text)
        raw_name: str = ""

        if m:
            raw_name = m.group("bina_adi")
        else:
            general_regex: Pattern[str] = re.compile(r'\b' + bp + r'\b', re.IGNORECASE)
            gm: Optional[Match[str]] = general_regex.search(self._text)
            if gm:
                raw_name = gm.group(1)

        if raw_name:
            cleaned: str = self._clean_building_name(raw_name)
            if cleaned:
                return cleaned

        return None