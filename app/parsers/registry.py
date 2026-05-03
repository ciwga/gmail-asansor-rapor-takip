"""
Ayrıştırıcı kaydı: PDF içerisindeki firmayı tespit edip ilgili sınıfa yönlendirir.

Yeni bir firma desteği eklemek için: 'parsers/' altında yeni sınıfı tanımlayın 
ve 'DETECTORS' listesine ilgili desenle birlikte ekleyin.
"""

import os
import re
from typing import Optional, List, Tuple, Any, Type

from app.parsers.base import BaseParser
from app.parsers.artibel import ArtibelParser
from app.parsers.adetsis import AdetsisParser
from app.parsers.mmo import MmoParser
from app.parsers.optimaldenge import OptimalDengeParser
from app.parsers.pdf_reader import extract_text
from app.core.models import ReportResult
from app.utils.logging import get_logger

log: Any = get_logger(__name__)

DETECTORS: List[Tuple[str, str, Type[BaseParser]]] = [
    ("Artıbel",              r"Art[ıi]bel\s*(?:Belgelendirme|Sertifikasyon)", ArtibelParser),
    ("MMO",                  r"TMMOB\s*Makina\s*Mühendisleri\s*Odas[ıi]",    MmoParser),
    ("Optimal Denge",        r"OPT[İI]MAL\s*DENGE",                           OptimalDengeParser),
    ("Kent Grup Belgelendirme", r"KENT\s*(?:BELGELENDİRME|GRUP)",           AdetsisParser),
    ("Asansör Kontrol",      r"ASANSÖR\s*KONTROL",                           AdetsisParser),
]


def detect_and_parse(file_path: str, db: Optional[Any] = None) -> Optional[ReportResult]:
    """PDF dosyasını okur, firmayı tespit eder ve ilgili ayrıştırıcıyı kullanarak verileri çeker.

    Args:
        file_path (str): İşlenecek PDF dosyasının tam yolu.
        db (Optional[Any]): Veritabanı bağlantı nesnesi. Verilirse PDF içeriği veritabanına kaydedilir.

    Returns:
        Optional[ReportResult]: Ayrıştırılan rapor sonuçlarını içeren nesne veya hata durumunda None.
    """
    text: Optional[str] = extract_text(file_path)
    
    if not text:
        log.warning(f"Metin ayıklanamadı: {file_path}")
        return None

    parser_class: Type[BaseParser] = AdetsisParser
    display_name: str = "Bilinmeyen Firma"

    name: str
    pattern: str
    cls: Type[BaseParser]
    for name, pattern, cls in DETECTORS:
        if re.search(pattern, text, re.IGNORECASE):
            parser_class = cls
            display_name = name
            break

    parser: BaseParser
    try:
        parser = parser_class(text)
    except Exception as e:
        log.error(f"Ayrıştırıcı başlatma hatası ({file_path}): {e}")
        return None

    from app.reporters.dates import calculate_next_inspection

    building: str = parser.extract_building_name() or "BİLİNMEYEN"
    label: str = parser.label_color
    date: Optional[str] = parser.extract_inspection_date()

    result: ReportResult = ReportResult(
        file_name=os.path.basename(file_path),
        provider=display_name,
        building_name=building,
        label_color=label,
        inspection_date=date or "-",
        elevator_number=parser.extract_elevator_number() or "N/A",
        uuid=parser.extract_uuid() or "N/A",
    )

    if date and label not in ("Etiket Bulunamadı",):
        result.next_inspection = calculate_next_inspection(date, label)

    if db is not None:
        try:
            db.store_pdf(
                report_id=result.unique_key,
                file_name=result.file_name,
                file_path=file_path,
                building=building,
                provider=display_name,
                label_color=label,
            )
        except Exception as e:
            log.warning(f"PDF veritabanına kaydedilemedi ({result.file_name}): {e}")

    return result