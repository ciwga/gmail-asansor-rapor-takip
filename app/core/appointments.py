"""
Randevu e-posta ayrıştırıcı modülü.
PDF eki içermeyen randevu bildirim e-postalarından bina adı ve kontrol tarihi verilerini ayıklar.
"""

import re
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any, Set

from app.utils.logging import get_logger
from app.utils.patterns import (
    DATE_PATTERN_DMY, ILCE_PATTERN, ILCE_KNT_PATTERN,
    PHONE_PATTERN_10_11, PERSON_ASN_PATTERN,
    KID_PATTERN_NUMERIC, ARTIBEL_BUILDING_PATTERN,
    MMO_BINA_ADI_PATTERN, MMO_KONTROL_TARIHI_PATTERN, MMO_BINA_ID_PATTERN,
)

log: logging.Logger = get_logger(__name__)

_ILCE_PAT: str = str(ILCE_PATTERN.pattern)


def parse_appointment(content: str, subject: str, sender: str, date_ms: int) -> Optional[List[Dict[str, Any]]]:
    """Randevu e-postasını metin içeriğinden ayrıştırarak verileri çıkarır.
    
    Args:
        content (str): E-posta gövdesinin ham metin içeriği.
        subject (str): E-posta konu başlığı.
        sender (str): Gönderici e-posta adresi.
        date_ms (int): E-postanın alınma zamanı (milisaniye).
        
    Returns:
        Optional[List[Dict[str, Any]]]: Bulunan randevu verilerinin listesi veya hiçbir şey bulunamazsa None.
    """
    try:
        sender_lower: str = str(sender).lower()
        results: List[Dict[str, Any]] = []

        if "mmo.org.tr" in sender_lower:
            results = _parse_mmo(content)
        elif "asansorkontrol" in sender_lower:
            results = _parse_asansor_kontrol(content)
        elif "artibel" in sender_lower:
            results = _parse_artibel(content)
        elif "optimaldenge" in sender_lower or "milenyum" in sender_lower:
            results = _parse_optimal_denge(content, subject)

        return results if len(results) > 0 else None
    except Exception as e:
        log.error(f"Randevu ayrıştırma genel hatası: {e}", exc_info=True)
        return None


def _parse_mmo(content: str) -> List[Dict[str, Any]]:
    """MMO (Makina Mühendisleri Odası) randevu formatını ayrıştırır.

    Args:
        content (str): E-posta metni.

    Returns:
        List[Dict[str, Any]]: Ayrıştırılmış randevu listesi.
    """
    results: List[Dict[str, Any]] = []
    
    bina_m: Optional[re.Match[str]] = MMO_BINA_ADI_PATTERN.search(content)
    tarih_m: Optional[re.Match[str]] = MMO_KONTROL_TARIHI_PATTERN.search(content)
    bid_m: Optional[re.Match[str]] = MMO_BINA_ID_PATTERN.search(content)

    if bina_m and tarih_m:
        building: str = str(re.sub(r"<[^>]+>", "", str(bina_m.group(1)))).strip()
        raw: str = str(tarih_m.group(1)).strip()
        tarih: str
        
        try:
            tarih = datetime.strptime(raw, "%Y-%m-%d").strftime("%d.%m.%Y")
        except ValueError:
            tarih = raw
            
        bid: str = str(bid_m.group(1)) if bid_m else "N/A"
        
        safe_b: str = str(re.sub(r'[^A-Za-z0-9]', '', building))[:20]
        
        idx: int = 1
        uid: str = f"RANDEVU-MMO-{bid}-{safe_b}-{tarih.replace('.', '')}-{idx}"
        file_name: str = f"RANDEVU_MMO_{bid}_{safe_b}_{idx}"
        
        results.append(_make_randevu(
            file_name, "MMO (Randevu)", building,
            tarih, uid, elevator_number=f"Asansör #{idx}"
        ))
        
    return results


def _parse_asansor_kontrol(content: str) -> List[Dict[str, Any]]:
    """Asansör Kontrol firmasının randevu formatını ayrıştırır.

    Args:
        content (str): E-posta metni.

    Returns:
        List[Dict[str, Any]]: Ayrıştırılmış randevu listesi.
    """
    results: List[Dict[str, Any]] = []

    tarih_m: Optional[re.Match[str]] = DATE_PATTERN_DMY.search(content)
    
    if not tarih_m:
        tarih_m = re.search(r"(\d{1,2})[\.\-/](\d{1,2})[\.\-/](\d{4})", content)
        
    if not tarih_m:
        log.warning("Asansör Kontrol e-postasında geçerli bir tarih bulunamadı, işlem atlanıyor.")
        return results
        
    tarih: str = f"{str(tarih_m.group(1)).zfill(2)}.{str(tarih_m.group(2)).zfill(2)}.{str(tarih_m.group(3))}"
    
    wrap_pattern: str = r'[\r\n]+\s*(KNT\b|KONT\b|MAH|CAD|SOK|SİT|BLOK|NO:?|BİNA|APT|APART)'
    content_fixed: str = str(re.sub(wrap_pattern, r' \1', content, flags=re.IGNORECASE))
    
    lines: List[str] = content_fixed.splitlines()
    seen: Set[str] = set()

    idx: int = 1

    for line in lines:
        normalized: str = str(re.sub(r"[\t ]+", " ", line)).strip()
        if not normalized:
            continue

        is_match: bool = bool(ILCE_KNT_PATTERN.search(normalized))
        if not is_match:
            has_ilce: bool = bool(re.search(_ILCE_PAT, normalized, flags=re.IGNORECASE))
            has_kid: bool = bool(KID_PATTERN_NUMERIC.search(normalized))
            if has_ilce and has_kid:
                is_match = True
                
        if not is_match:
            continue

        before_ilce: str = str(re.split(_ILCE_PAT, normalized, flags=re.IGNORECASE)[0])
        kid_m: Optional[re.Match[str]] = KID_PATTERN_NUMERIC.search(before_ilce)
        kid: str = str(kid_m.group(1)).replace("/", "-") if kid_m else "N/A"

        clean: str = before_ilce
        clean = str(PERSON_ASN_PATTERN.sub("", clean))
        clean = str(re.sub(r"\(?\d+/\d+\)?\s*", "", clean))
        clean = str(re.sub(r"\b0?\s*\d{3}\s*\d{3}\s*\d{2}\s*\d{2}\b", "", clean))
        clean = str(PHONE_PATTERN_10_11.sub("", clean))
        
        clean = str(re.sub(r"^\s*\d+[\)\.-]\s*", "", clean))
        clean = str(re.sub(r"^\s*\d+\s+", "", clean))
        clean = str(re.sub(r"^\s*[\)\.-]+\s*", "", clean))
        clean = str(re.sub(r"\s+\d+\s*$", "", clean))
        
        if "/" in clean:
            parts: List[str] = clean.split("/")
            if str(parts[0]).strip() and not str(parts[-1]).strip().isdigit():
                clean = str(parts[0])
                
        clean = str(re.sub(r"\s+", " ", clean)).strip()

        if len(clean) < 3 or clean in seen:
            continue

        seen.add(clean)
        
        safe_b: str = str(re.sub(r'[^A-Za-z0-9]', '', clean))[:20]
        
        uid: str = f"RANDEVU-ASK-{kid}-{safe_b}-{tarih.replace('.', '')}-{idx}"
        file_name: str = f"RANDEVU_ASK_{kid}_{safe_b}_{tarih.replace('.', '')}_{idx}"
        
        results.append(_make_randevu(
            file_name,
            "Asansör Kontrol (Randevu)", clean, tarih, uid,
            elevator_number=f"Asansör #{idx}"
        ))
        
        idx += 1

    return results

def _parse_artibel(content: str) -> List[Dict[str, Any]]:
    """Artıbel firmasının randevu formatını ayrıştırır.

    Args:
        content (str): E-posta metni.

    Returns:
        List[Dict[str, Any]]: Ayrıştırılmış randevu listesi.
    """
    results: List[Dict[str, Any]] = []
    lines: List[str] = content.splitlines()
    i: int = 0
    
    idx: int = 1
    
    while i < len(lines):
        date_m: Optional[re.Match[str]] = re.match(r"\s*(\d{2}\.\d{2}\.\d{4})\s*$", lines[i].strip())
        
        if date_m:
            tarih: str = str(date_m.group(1))
            
            for j in range(i + 1, min(i + 15, len(lines))):
                bina_m: Optional[re.Match[str]] = ARTIBEL_BUILDING_PATTERN.search(lines[j])
                
                if bina_m:
                    raw: str = str(bina_m.group(1)).strip()
                    kid_m: Optional[re.Match[str]] = re.search(r"\(([\d/]+)\)", raw)
                    kid: str = str(kid_m.group(1)).replace("/", "-") if kid_m else "N/A"
                    building: str = str(re.sub(r"\([^)]+\)", "", raw)).strip()
                    
                    safe_b: str = str(re.sub(r'[^A-Za-z0-9]', '', building))[:20]
                    
                    uid: str = f"RANDEVU-ART-{kid}-{safe_b}-{tarih.replace('.', '')}-{idx}"
                    file_name: str = f"RANDEVU_ART_{kid}_{safe_b}_{tarih.replace('.', '')}_{idx}"
                    
                    results.append(_make_randevu(
                        file_name,
                        "Artıbel (Randevu)", building, tarih, uid,
                        elevator_number=f"Asansör #{idx}"
                    ))
                    
                    idx += 1
                    break
        i += 1
        
    return results


def _parse_optimal_denge(content: str, subject: str) -> List[Dict[str, Any]]:
    """Optimal Denge firmasının randevu formatını ayrıştırır.

    Args:
        content (str): E-posta metni.
        subject (str): E-posta konu başlığı.

    Returns:
        List[Dict[str, Any]]: Ayrıştırılmış randevu listesi.
    """
    results: List[Dict[str, Any]] = []

    sub_m: Optional[re.Match[str]] = re.search(r"Randevu\s+(\d{1,2}\.\d{1,2}\.\d{4})\s+(.+)", subject or "", re.IGNORECASE)
    bina_m: Optional[re.Match[str]] = re.search(r"Bina\s*Ad[ıi]\s*:?\s*(.+?)(?:\n|$)", content, re.IGNORECASE)
    tarih_m: Optional[re.Match[str]] = re.search(r"Tarih\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", content, re.IGNORECASE)

    building: Optional[str] = None
    tarih: Optional[str] = None

    if bina_m:
        building = str(bina_m.group(1)).strip().rstrip(".")
    elif sub_m:
        building = str(sub_m.group(2)).strip().rstrip(".")

    if tarih_m:
        raw: str = str(tarih_m.group(1))
        parts: List[str] = raw.split(".")
        if len(parts) == 3:
            tarih = f"{str(parts[0]).zfill(2)}.{str(parts[1]).zfill(2)}.{str(parts[2])}"
    elif sub_m:
        raw = str(sub_m.group(1))
        parts = raw.split(".")
        if len(parts) == 3:
            tarih = f"{str(parts[0]).zfill(2)}.{str(parts[1]).zfill(2)}.{str(parts[2])}"

    if building and tarih:
        safe_b: str = str(re.sub(r'[^A-Za-z0-9]', '', building))[:20]
        
        # Mükerrer (Overwrite) hatasını önlemek için indekse dayalı isimlendirme:
        idx: int = 1
        uid: str = f"RANDEVU-OPT-{safe_b}-{tarih.replace('.', '')}-{idx}"
        file_name: str = f"RANDEVU_OPT_{safe_b}_{tarih.replace('.', '')}_{idx}"
        
        results.append(_make_randevu(
            file_name,
            "Optimal Denge (Randevu)", building, tarih, uid,
            elevator_number=f"Asansör #{idx}"
        ))

    return results


def _make_randevu(
    file_name: str, 
    provider: str, 
    building: str, 
    tarih: str, 
    uuid_str: str, 
    elevator_number: str = "N/A"
) -> Dict[str, Any]:
    """Randevu verilerini içeren standart sonuç sözlüğünü oluşturur.
    
    Bu fonksiyon, gelen yapısal verileri merkezi bir Rapor sözlük modeline uyarlar.

    Args:
        file_name (str): Benzersizleştirilmiş sanal dosya adı.
        provider (str): Raporu sağlayan kuruluş bilgisi.
        building (str): Ayrıştırılan bina adı.
        tarih (str): Muayene / randevu tarihi.
        uuid_str (str): Veritabanı çakışmalarını (primary key collisions) önlemek için eşsiz kimlik.
        elevator_number (str): Engine.py tarafında mükerrer kayıtların ezilmesini önlemek 
            için tahsis edilmiş numaralandırma. Varsayılan "N/A".

    Returns:
        Dict[str, Any]: Ana rapor işleme motoruna gönderilecek veri sözlüğü.
    """
    return {
        "file_name": file_name,
        "provider": provider,
        "building_name": building,
        "label_color": "Randevu",
        "inspection_date": tarih,
        "next_inspection": tarih,
        "elevator_number": elevator_number,
        "uuid": uuid_str,
    }