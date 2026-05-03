"""
Sonraki kontrol tarihi hesaplama modülü.
Rapor etiket rengine göre bir sonraki muayene tarihini yasal süreler dahilinde hesaplar.
"""

from datetime import datetime, timedelta
from typing import Dict, Callable, Optional
from dateutil.relativedelta import relativedelta

_INTERVALS: Dict[str, Callable[[datetime], datetime]] = {
    "Mavi": lambda d: d + relativedelta(months=12),
    "Yeşil": lambda d: d + relativedelta(months=12),
    "Sarı": lambda d: d + timedelta(days=120),
    "Kırmızı": lambda d: d + timedelta(days=60),
}


def calculate_next_inspection(date_str: str, label: str) -> str:
    """Verilen muayene tarihi ve etiket rengine göre bir sonraki kontrol tarihini hesaplar.

    Args:
        date_str (str): Muayenenin yapıldığı tarih.
        label (str): Raporun etiket rengi.

    Returns:
        str: Bir sonraki muayene tarihi veya hata durumlarında ilgili hata mesajı.
    """
    if not isinstance(date_str, str):
        return "Geçersiz Tarih"

    try:
        start: datetime = datetime.strptime(date_str.replace(".", "/"), "%d/%m/%Y")
    except ValueError:
        return "Tarih Hatası"

    calc: Optional[Callable[[datetime], datetime]] = _INTERVALS.get(label)
    
    if not calc:
        return "Hesaplanamadı"

    try:
        return calc(start).strftime("%d.%m.%Y")
    except Exception:
        return "Hesaplama Hatası"