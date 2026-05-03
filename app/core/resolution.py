"""Çözümleme filtresi: Hangi bina/asansörlerin halihazırda daha yeni ve olumlu bir rapora
sahip olduğunu takip eder, böylece eski olumsuz raporların işlenmesi atlanabilir.
"""

import re
from typing import Dict, Optional, Any

from app.utils.text import to_lower_tr


class ResolutionFilter:
    """Olumlu (Yeşil veya Mavi etiketli) raporların bellek içi bir dizinini tutar.

    Bir aday rapor kontrol edilirken, eğer aynı bina veya asansör için sistemde 
    daha yeni tarihli bir çözümleme (olumlu rapor) mevcutsa, aday raporun 
    işlenmesi atlanır.

    Attributes:
        _id_map (Dict[str, float]): Bina kimlik anahtarı -> zaman damgası eşleşmesi.
        _name_map (Dict[str, float]): Bina isim anahtarı -> zaman damgası eşleşmesi.
    """

    def __init__(self) -> None:
        """ResolutionFilter sınıfını boş haritalarla başlatır."""
        self._id_map: Dict[str, float] = {}
        self._name_map: Dict[str, float] = {}

    @property
    def resolved_map(self) -> Dict[str, float]:
        """Kimlik bazlı çözümlenmiş rapor haritasını döndürür.

        Returns:
            Dict[str, float]: Kimlik anahtarları ve zaman damgaları.
        """
        return self._id_map

    @property
    def resolved_names_map(self) -> Dict[str, float]:
        """İsim bazlı çözümlenmiş rapor haritasını döndürür.

        Returns:
            Dict[str, float]: İsim anahtarları ve zaman damgaları.
        """
        return self._name_map

    def add_resolved(self, subject: str, snippet: str, sender: str, date_ms: int) -> None:
        """Çözümlenmiş (olumlu) bir rapor olayını sisteme kaydeder.

        Args:
            subject (str): E-posta konu başlığı.
            snippet (str): E-posta içeriğinden kısa bir kesit.
            sender (str): E-posta gönderen adresi.
            date_ms (int): Milisaniye cinsinden e-posta tarihi.
        """
        meta: Dict[str, Any] = self._extract_meta(subject, snippet, sender)
        ts: float = date_ms / 1000.0

        if meta.get("id"):
            if meta["id"] not in self._id_map or ts > self._id_map[meta["id"]]:
                self._id_map[meta["id"]] = ts

        if meta.get("name"):
            if meta["name"] not in self._name_map or ts > self._name_map[meta["name"]]:
                self._name_map[meta["name"]] = ts

    def is_resolved(self, subject: str, snippet: str, sender: str, date_ms: int) -> bool:
        """Bu rapor için sistemde daha yeni bir çözümleme olup olmadığını kontrol eder.

        Args:
            subject (str): E-posta konu başlığı.
            snippet (str): E-posta içeriğinden kısa bir kesit.
            sender (str): E-posta gönderen adresi.
            date_ms (int): Milisaniye cinsinden kontrol edilecek raporun tarihi.

        Returns:
            bool: Eğer daha yeni bir olumlu rapor varsa True, aksi halde False.
        """
        meta: Dict[str, Any] = self._extract_meta(subject, snippet, sender)
        ts: float = date_ms / 1000.0

        if meta.get("id") and meta["id"] in self._id_map:
            if self._id_map[meta["id"]] > ts:
                return True

        if meta.get("name") and meta["name"] in self._name_map:
            if self._name_map[meta["name"]] > ts:
                return True

        return False

    @staticmethod
    def _extract_meta(subject: str, snippet: str, sender: str) -> Dict[str, Any]:
        """E-posta üstbilgilerinden bina kimliğini ve adını ayıklar.

        Args:
            subject (str): E-posta konu başlığı.
            snippet (str): E-posta içeriğinden kısa bir kesit.
            sender (str): E-posta gönderen adresi.

        Returns:
            Dict[str, Any]: Ayıklanan 'id' ve 'name' bilgilerini içeren sözlük.
        """
        meta: Dict[str, Any] = {"id": None, "name": None}
        combined: str = f"{subject.strip()} {snippet.strip()}".upper()
        sender_lower: str = sender.lower()

        if "KIMLIKNO:" in combined:
            m: Optional[re.Match] = re.search(r"KIMLIKNO:([\d\-]+)", combined)
            if m:
                meta["id"] = f"AK-{m.group(1)}"

        if not meta["id"]:
            m = re.search(r"^(\d+/\d+)", subject.strip())
            if m:
                meta["id"] = f"KENT-{m.group(1)}"

        if not meta["id"] and "artibel" in sender_lower:
            m = re.search(r"\(([\d/]+)\)", combined)
            if m:
                meta["id"] = f"ART-{m.group(1)}"

        if not meta["id"] and ("mmo" in sender_lower or "BINA ID:" in combined):
            m = re.search(r"BINA ID:\s*(\d+)", combined)
            if m:
                meta["id"] = f"MMO-{m.group(1)}"

        bina_match: Optional[re.Match] = re.search(
            r"B[Iİ]NA ADI:\s*(.*?)(?:CADDE/SOKAK:|MAHALLE/KÖY:|$)", combined
        )
        
        if bina_match:
            clean: str = re.sub(r"[^A-ZĞÜŞİÖÇ0-9]", "", bina_match.group(1))
            if len(clean) > 3:
                meta["name"] = clean
                return meta

        clean_text: str = subject.strip().upper()
        clean_text = re.sub(r"KIMLIKNO:[\d\-]+", "", clean_text)
        clean_text = re.sub(r"QR:[a-fA-F0-9\-]+", "", clean_text)
        clean_text = re.sub(r"^\d+/\d+", "", clean_text)

        for noise in [
            "DENETIM RAPORU",
            "ONAYLANMIS RAPORUNUZ HAKKINDA",
            "ONAYLANMIŞ RAPORUNUZ HAKKINDA",
            "ASANSOR PERIYODIK MUAYENE RAPORU",
            "ASANSÖR PERİYODİK MUAYENE RAPORU",
        ]:
            clean_text = clean_text.replace(noise, "")

        clean_text = re.sub(r"[^A-ZĞÜŞİÖÇ0-9]", "", clean_text)
        
        if len(clean_text) > 5:
            meta["name"] = clean_text[:50]

        return meta