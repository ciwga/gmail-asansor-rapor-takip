"""
Merkezi düzenli ifade ve örüntü tanımları modülü.

Bu modül, uygulama genelinde kullanılan metin temizleme, veri ayıklama ve 
firma tespit işlemlerinde kullanılan tüm örüntüleri tek bir noktadan yönetir.

Düzenleme Kuralları:
  1. Yeni bir desen eklerken hangi modül tarafından kullanıldığını açıklayın.
  2. Desen değişikliklerinden sonra mutlaka ilgili testleri çalıştırın.
  3. Türkçe karakter hassasiyeti nedeniyle 're.I' bayrağını dikkatli kullanın.
"""

import re
from typing import List, Tuple, Dict, Pattern

BUILDING_SUFFIXES: List[str] = [
    "MUAYENE RAPORU", "ASANSÖR PERİYODİK KONTROL RAPORU",
    "PERİYODİK KONTROL RAPORU", "KONTROL RAPORU",
    "RAPORU", "MUAYENE",
]

BUILDING_CLEANUP_PATTERNS: List[Tuple[Pattern[str], str]] = [
    (re.compile(r"QR\s*:\s*[\w-]+", re.I), ""),
    (re.compile(r"\b\d{10,}\b"), ""),
    (re.compile(r"\s+"), " "),
]

DATE_PATTERN_DMY: Pattern[str] = re.compile(
    r"(\d{2})\s*[.\-]\s*(\d{2})\s*[.\-]\s*(\d{4})",
    re.I,
)

ILCE_PATTERN: Pattern[str] = re.compile(
    r"(?:ALTINDA[ĞG]|ÇANKAYA|KEÇİÖREN|ETİMESGUT|SİNCAN|MAMAK|YENİMAHALLE|PURSAKLAR|GÖLBAŞI|AKYURT|BALA|BEYPAZARI|ÇAMLIDERE|ÇUBUK|ELMADAĞ|EVREN|GÜDÜL|HAYMANA|KALECİK|KAZAN|KIZILCAHAMAM|NALLIHAN|POLATLI|ŞEREFLIKOÇHISAR)",
    re.I,
)

ILCE_KNT_PATTERN: Pattern[str] = re.compile(
    ILCE_PATTERN.pattern + r"\s+\d+\s*KNT",
    re.I,
)

PHONE_PATTERN: Pattern[str] = re.compile(r"\b\d[\d\s]{8,12}\d\b")
PHONE_PATTERN_10_11: Pattern[str] = re.compile(r"\b\d{10,11}\b")

PERSON_ASN_PATTERN: Pattern[str] = re.compile(
    r"[a-zA-ZÇĞİÖŞÜçğıöşü]+\s+[a-zA-ZÇĞİÖŞÜçğıöşü]+\s+ASN\s*",
    re.I,
)

KID_PATTERN_PAREN: Pattern[str] = re.compile(r"\((\d+/\d+)\)")
KID_PATTERN_BARE: Pattern[str] = re.compile(r"(?:^|\s)(\d+/\d+)\s+[A-ZÇĞİÖŞÜ]")
KID_PATTERN_NUMERIC: Pattern[str] = re.compile(r"(\d+/\d+)")

ARTIBEL_BUILDING_PATTERN: Pattern[str] = re.compile(
    r"([\wÇĞİÖŞÜçğışöü ]{4,}(?:APT|APARTMANI?|BLOĞU|SİTESİ|KONUTLARI|LOJ\.)[\wÇĞİÖŞÜçğışöü ]*(?:\([\d/]+\))?)",
    re.I,
)

MMO_BINA_ID_PATTERN: Pattern[str] = re.compile(r"Bina\s*Id\s*:\s*(\d+)", re.I)
MMO_BASVURU_ID_PATTERN: Pattern[str] = re.compile(r"Basvuru\s*Id\s*:\s*(\d+)", re.I)
MMO_BINA_ADI_PATTERN: Pattern[str] = re.compile(r"Bina\s*Ad[ıi]\s*:\s*(.+?)(?:\n|Mahalle|$)", re.I)
MMO_KONTROL_TARIHI_PATTERN: Pattern[str] = re.compile(
    r"Kontrol\s*Tarihi(?:/Saati)?\s*:?\]?\s*(\d{4}-\d{2}-\d{2})",
    re.I,
)

LABEL_COLOR_MAP: Dict[str, str] = {
    "K": "Kırmızı",
    "S": "Sarı",
    "M": "Mavi",
    "Y": "Yeşil",
}

PDF_DATE_PATTERN: Pattern[str] = re.compile(r"(\d{2})[./](\d{2})[./](\d{4})")
PDF_ASANSOR_NO_PATTERN: Pattern[str] = re.compile(r"(?:Asansör\s*(?:Tescil\s*)?No|Sicil\s*No)\s*:?\s*([\d/\s]+)", re.I)

ADETSIS_URL_PATTERN: Pattern[str] = re.compile(
    r"https?://(?:www\.)?(?:adetsis\.net|raporkentbelgelendirme\.com|asansorkontrol\.net)/[^\s<>\"']+",
    re.I,
)

ARTIBEL_URL_PATTERN: Pattern[str] = re.compile(
    r"https?://(?:www\.)?artibel\.com\.tr/[^\s<>\"']+\.pdf",
    re.I,
)

OPTIMAL_URL_PATTERN: Pattern[str] = re.compile(
    r"https?://(?:www\.)?optimaldenge\.pro/asansor_denetim_rapor_print\.aspx\?[^\s\"'<>]+",
    re.I,
)

OPTIMAL_BINA_ADI_PATTERN: Pattern[str] = re.compile(r"Bina\s*Ad[ıi]\s*:?\s*(.+?)(?:\n|$)", re.I)
OPTIMAL_BINA_NO_PATTERN: Pattern[str] = re.compile(r"Bina\s*No\s*:?\s*(\d+)", re.I)
OPTIMAL_ETIKET_PATTERN: Pattern[str] = re.compile(r"Etiket\s*:?\s*((?:KIRMIZI|SARI|MAVİ|YEŞİL)\s*ETİKET)", re.I)
OPTIMAL_DENETIM_TARIHI_PATTERN: Pattern[str] = re.compile(r"Denetim\s*Tarihi\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
OPTIMAL_ASANSOR_NO_PATTERN: Pattern[str] = re.compile(r"Bakanlık\s*Asansör\s*No\s*:?\s*([0-9A-Fa-f-]{36})", re.I)

OPTIMAL_SENDERS: List[str] = [
    "optimaldenge.com",
    "optimaldenge.app",
    "optimaldenge.pro",
    "milenyum.pro",
    "optimal.arsiv@gmail.com",
]