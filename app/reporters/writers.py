"""Rapor çıktı yazıcıları: Metin, tablo, mesajlaşma ve komut satırı formatlarında sonuç üretir."""

import csv
import os
import re
import shutil
from datetime import datetime
from typing import List, Dict, Any

from app.utils.logging import get_logger

log: Any = get_logger(__name__)

_ICONS: Dict[str, str] = {
    "Mavi": "🔵", 
    "Yeşil": "🟢", 
    "Sarı": "🟡", 
    "Kırmızı": "🔴", 
    "Randevu": "📆"
}

_ANSI: Dict[str, str] = {
    "Kırmızı": "\033[91m", 
    "Sarı": "\033[93m", 
    "Mavi": "\033[94m",
    "Yeşil": "\033[92m", 
    "Randevu": "\033[96m",
}


def _sort_by_next(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sonuçları bir sonraki muayene tarihine göre kronolojik olarak sıralar.

    Args:
        results (List[Dict[str, Any]]): Sıralanacak rapor sonuçları listesi.

    Returns:
        List[Dict[str, Any]]: Tarihe göre sıralanmış yeni liste.
    """
    def key_func(item: Dict[str, Any]) -> datetime:
        d: Any = item.get("next_inspection", "")
        
        if d and isinstance(d, str) and re.match(r"\d{2}\.\d{2}\.\d{4}", d):
            try:
                return datetime.strptime(d, "%d.%m.%Y")
            except ValueError:
                pass
                
        return datetime.max
        
    return sorted(results, key=key_func)


def write_txt(results: List[Dict[str, Any]], path: str = "rapor_ozeti.txt") -> None:
    """Rapor sonuçlarını görsel bir tablo yapısında metin dosyasına yazar.

    Args:
        results (List[Dict[str, Any]]): Rapor verileri.
        path (str): Çıktı dosyasının yolu.
    """
    results = _sort_by_next(results)
    
    cols: int
    try:
        cols = shutil.get_terminal_size((80, 20)).columns
    except Exception:
        cols = 80
        
    w: int = min(78, max(40, cols - 2))
    
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"╔{'═'*w}╗\n")
            f.write(f"║ {'RAPOR ÖZETİ':^{w}} ║\n")
            f.write(f"║ {datetime.now().strftime('%d.%m.%Y %H:%M'):^{w}} ║\n")
            f.write(f"╚{'═'*w}╝\n\n")
            
            i: int
            r: Dict[str, Any]
            for i, r in enumerate(results, 1):
                icon: str = _ICONS.get(r.get("label_color", ""), "⚪")
                f.write(f"┌── {i:03d} {'─'*(w-7)}┐\n")
                f.write(f"│ 🏢 BİNA ADI:     {r.get('building_name','N/A'):<{w-20}}│\n")
                f.write(f"│ 🆔 ASANSÖR NO:   {r.get('elevator_number','N/A'):<{w-20}}│\n")
                f.write(f"│ 🏷  ETİKET:       {icon} {r.get('label_color','N/A'):<{w-23}}│\n")
                
                dl: str = f"{r.get('inspection_date','-')} → {r.get('next_inspection','-')}"
                f.write(f"│ 📅 TARİH:        {dl:<{w-20}}│\n")
                
                f.write(f"│ 🔧 FİRMA:        {r.get('provider','N/A'):<{w-20}}│\n")
                f.write(f"│ 📄 DOSYA:        {r.get('file_name','N/A'):<{w-20}}│\n")
                f.write(f"└{'─'*w}┘\n")
            
            f.write(f"\nToplam {len(results)} kayıt raporlandı.\n")
            
        log.info(f"📄 Özet rapor oluşturuldu: {path}")
    except Exception as e:
        log.error(f"Metin raporu yazılırken hata oluştu: {e}")


def write_csv(results: List[Dict[str, Any]], path: str = "rapor_ozeti.csv") -> None:
    """Rapor sonuçlarını tablo uyumlu bir dosyaya aktarır.

    Args:
        results (List[Dict[str, Any]]): Rapor verileri.
        path (str): Dosyanın yolu.
    """
    headers: List[str] = [
        "file_name", "provider", "building_name", "elevator_number",
        "inspection_date", "label_color", "uuid", "next_inspection"
    ]
    
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer: csv.DictWriter[str] = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
            writer.writeheader()
            
            r: Dict[str, Any]
            for r in results:
                writer.writerow(r)
                
        log.info(f"📊 Tablo raporu oluşturuldu: {path}")
    except Exception as e:
        log.error(f"Tablo yazma hatası: {e}")


def write_whatsapp(results: List[Dict[str, Any]], path: str = "rapor_whatsapp.txt") -> None:
    """Paylaşmaya uygun formatlı metin dosyası üretir.

    Args:
        results (List[Dict[str, Any]]): Rapor verileri.
        path (str): Metin dosyasının yolu.
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"*🚀 GÜNLÜK ASANSÖR RAPORU* 📅 _{datetime.now().strftime('%d.%m.%Y')}_\n")
            f.write(f"_Toplam {len(results)} rapor işlendi._\n\n")
            
            r: Dict[str, Any]
            for r in results:
                icon: str = _ICONS.get(r.get("label_color", ""), "⚪")
                f.write(f"🏢 *{r.get('building_name','N/A')}*\n")
                f.write(f"{icon} *Etiket:* {r.get('label_color','N/A')}\n")
                f.write(f"📅 *Tarih:* {r.get('inspection_date','-')} ➡ {r.get('next_inspection','-')}\n")
                f.write(f"🆔 *Asansör No:* {r.get('elevator_number','N/A')}\n")
                f.write(f"🔧 *Firma:* {r.get('provider','N/A')}\n")
                f.write("──────────────────\n")
                
        log.info(f"📱 Paylaşım raporu oluşturuldu: {path}")
    except Exception as e:
        log.error(f"Paylaşım raporu yazma hatası: {e}")


def generate_reports(results: List[Dict[str, Any]], formats: List[str], output_dir: str = ".") -> None:
    """Belirlenen formatlarda tüm rapor çıktılarını eşzamanlı olarak üretir.

    Args:
        results (List[Dict[str, Any]]): İşleme sonuçları (Boş liste durumunda dosyalar sıfırlanır).
        formats (List[str]): İstenen formatlar.
        output_dir (str): Dosyaların kaydedileceği klasör.
    """
    if not results:
        log.info("Raporlanacak veri kalmadı, mevcut çıktı dosyaları sıfırlanıyor.")
        
    fmt: str
    for fmt in formats:
        p: str = os.path.join(output_dir, f"rapor_ozeti.{fmt}" if fmt != "whatsapp" else "rapor_whatsapp.txt")
        
        if fmt == "txt":
            write_txt(results, p)
        elif fmt == "csv":
            write_csv(results, p)
        elif fmt == "whatsapp":
            write_whatsapp(results, p)
            
    print_cli_summary(results)


def print_cli_summary(results: List[Dict[str, Any]]) -> None:
    """Terminal ekranına okunaklı bir rapor özeti basar.

    Args:
        results (List[Dict[str, Any]]): Rapor verileri.
    """
    R: str = "\033[0m"
    B: str = "\033[1m"
    DIM: str = "\033[2m"
    
    sorted_r: List[Dict[str, Any]] = _sort_by_next(results)
    
    print(f"\n{B}{'═'*60}")
    print(f"  📋 KONTROL SONUÇLARI — {len(results)} rapor")
    print(f"{'═'*60}{R}\n")
    
    i: int
    r: Dict[str, Any]
    for i, r in enumerate(sorted_r, 1):
        lbl: str = r.get("label_color", "")
        c: str = _ANSI.get(lbl, "")
        icon: str = _ICONS.get(lbl, "⚪")
        
        bld: str = r.get("building_name", "?")
        dt: str = r.get("inspection_date", "-")
        nx: str = r.get("next_inspection", "-")
        prv: str = r.get("provider", "?")
        asn: str = r.get("elevator_number", "N/A")
        
        print(f"  {c}{icon} {B}{bld}{R}")
        print(f"     {c}Etiket:{R} {lbl}  {DIM}|{R}  {c}Tarih:{R} {dt} → {nx}")
        print(f"     {DIM}Firma: {prv}  |  Asansör: {asn}{R}")
        
        if i < len(sorted_r):
            print(f"  {DIM}{'─'*56}{R}")
            
    print(f"\n{B}{'═'*60}{R}\n")