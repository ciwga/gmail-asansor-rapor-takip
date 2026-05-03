"""
Ana işlem motoru: yetkilendirme → arama → indirme → ayrıştırma → raporlama süreçlerini yönetir.
Hem Komut Satırı Arayüzü (CLI) hem de web arayüzü üzerinden tetiklenebilir.
"""

import os
import shutil
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Set, Tuple, Optional, Callable

from app.config import load_config
from app.utils.logging import get_logger, setup_logging
from app.core.database import Database
from app.core.resolution import ResolutionFilter
from app.core.labels import LabelResolver
from app.core.worker import process_messages
from app.parsers.registry import detect_and_parse
from app.reporters.writers import generate_reports
from app.gmail.auth import authenticate
from app.gmail.client import ensure_labels, get_all_messages, batch_fetch_messages
from app.gmail.maintenance import (
    run_rules_engine, create_cleanup_request, create_trash_request, delete_label
)
from app.paths import paths

log: Any = get_logger(__name__)

_watch_stop: threading.Event = threading.Event()


def stop_watch() -> None:
    """Dinleme (Watch) modunu dışarıdan güvenli bir şekilde durdurur."""
    _watch_stop.set()


def run_watch(config_path: str = "app_manifest") -> None:
    """Dinleme modu: Belirli aralıklarla yeni e-posta kontrolü yapar.

    Web API'den gelen bir sinyal veya CLI üzerinde Ctrl+C ile durdurulana kadar çalışır.
    
    Args:
        config_path (str): Yapılandırma dosyasının referans anahtarı.
    """
    config: Dict[str, Any] = load_config(config_path)
    ws: Dict[str, Any] = config.get("watch_settings", {})
    interval: int = max(1, ws.get("interval_minutes", 30))
    paths_dict: Dict[str, Any] = config.get("paths", {})
    
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"), log_file=paths_dict.get("log_file"))

    log.info("=" * 50)
    log.info(f"👁️  DİNLEME MODU — Her {interval} dakikada bir kontrol yapılacak")
    log.info("Durdurmak için Ctrl+C tuşlarına basın (veya Web Arayüzünü kullanın)")
    log.info("=" * 50)

    _watch_stop.clear()
    cycle: int = 0

    while not _watch_stop.is_set():
        cycle += 1
        log.info(f"🔄 Döngü #{cycle} başlıyor...")
        try:
            results: List[Dict[str, Any]] = run(config_path)
        except Exception as e:
            log.error(f"🔄 Döngü #{cycle} sırasında hata oluştu: {e}", exc_info=True)

        log.info(f"⏳ {interval} dakika bekleniyor...")
        if _watch_stop.wait(timeout=interval * 60):
            break

    log.info("👁️  Dinleme modu başarıyla durduruldu.")


def run(config_path: str = "app_manifest") -> List[Dict[str, Any]]:
    """Tüm tarama, indirme ve işleme döngüsünü başlatan ana koordinasyon fonksiyonu.
    
    Args:
        config_path (str): Yapılandırma verisinin referans yolu.
        
    Returns:
        List[Dict[str, Any]]: İşlenen ve yeni eklenen rapor veya randevu sonuçlarının listesi.
    """
    start: float = time.time()
    config: Dict[str, Any] = load_config(config_path)
    mode: str = config.get("mode", "local").lower()
    paths_dict: Dict[str, Any] = config.get("paths", {})
    
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"), log_file=paths_dict.get("log_file", paths.DEFAULT_LOG_PATH))

    log.info("=" * 50)
    log.info(f"Asansör Rapor Otomasyonu — Çalışma Modu: {mode}")
    log.info("=" * 50)

    db_path: str = paths_dict.get("database", "")
    if not db_path or db_path.strip() == "":
        db_path = paths.DEFAULT_DB_PATH

    db: Database = Database(db_path)
    all_results: List[Dict[str, Any]] = []
    mmo_ids: Set[Tuple[str, str]] = set()

    try:
        if mode == "gmail":
            all_results = _run_gmail(config, db, mmo_ids)
        elif mode == "local":
            all_results = _run_local(config, db)
        elif mode == "cleanup":
            _run_cleanup(config)
        elif mode == "delete_label":
            _run_delete_label(config)
        elif mode == "trash_emails":
            _run_trash(config)
    except Exception as e:
        log.critical(f"Kritik işlem hatası: {e}", exc_info=True)
    finally:
        db.close()

    if all_results:
        final: List[Dict[str, Any]]
        skipped_items: List[Dict[str, Any]]
        final, skipped_items = _deduplicate(all_results)
        
        out_folder: str = paths_dict.get("output_folder", "")
        if not out_folder or out_folder.strip() == "":
            out_folder = os.path.join(str(Path.home()), "AsansorRaporlari", "ciktilar")
            
        generate_reports(final, config.get("output_formats", ["txt"]), out_folder)
        
        log.info("\n" + "=" * 65)
        log.info(f"📊 İŞLEM ÖZETİ (Toplam Süre: {time.time()-start:.1f} sn)")
        log.info("=" * 65)
        log.info(f"📥 Yeni E-postalardan Çıkarılan Toplam Rapor : {len(all_results)}")
        
        if skipped_items:
            log.info(f"✂️ Aynı Bina İçin Eski/Mükerrer Olarak Elenen: {len(skipped_items)}")
            for sk in skipped_items:
                b_name: str = sk.get('building_name', 'Bilinmiyor')
                i_date: str = sk.get('inspection_date', '-')
                log.info(f"   - 🗑️ Elendi: {b_name} | Tarih: {i_date} (Daha günceli tutuldu)")
                
        log.info(f"✅ Sisteme Eklenen Benzersiz Yeni Kayıt     : {len(final)}")
        log.info("=" * 65 + "\n")
        
        return final
    else:
        log.info(f"📭 Herhangi bir yeni sonuç bulunamadı. (Süre: {time.time()-start:.1f}sn)")
        return []


def _auth_gmail(config: Dict[str, Any]) -> Tuple[Any, Dict[str, str]]:
    """Gmail servisine bağlanır ve gerekli etiketleri senkronize eder.
    
    Args:
        config (Dict[str, Any]): Uygulama yapılandırma sözlüğü.
        
    Returns:
        Tuple[Any, Dict[str, str]]: Gmail servis nesnesi ve etiket adı-ID eşleşme haritası.
        
    Raises:
        RuntimeError: Gmail API yetkilendirmesi başarısız olduğunda fırlatılır.
    """
    service: Any = authenticate()
    if not service:
        raise RuntimeError("Gmail API yetkilendirmesi başarısız oldu.")

    resolver: LabelResolver = LabelResolver(config)
    config["_label_resolver"] = resolver

    active_labels: Set[str] = set()
    active_labels.update(resolver.all_color_labels())
    
    for s in config.get("sources", []):
        lbl: str = resolver.source_label(s.get("label_name", ""))
        if lbl:
            active_labels.add(lbl)
            
    q_label: Optional[str] = config.get("quarantine_settings", {}).get("quarantine_label_name")
    if q_label:
        active_labels.add(q_label)

    if getattr(resolver, '_use_tree', False) and getattr(resolver, '_parent', ''):
        active_labels.add(resolver._parent)
        
    active_labels.discard("")

    label_map: Dict[str, str] = ensure_labels(service, active_labels)
    
    try:
        results: Dict[str, Any] = service.users().labels().list(userId='me').execute()
        for l in results.get('labels', []):
            if l['name'] not in label_map:
                label_map[l['name']] = l['id']
    except Exception as e:
        log.error(f"Gmail üzerindeki tüm etiket listesi alınırken hata: {e}")

    config["_internal_labels_map"] = label_map
    return service, label_map


def _run_gmail(config: Dict[str, Any], db: Database, mmo_ids: Set[Tuple[str, str]]) -> List[Dict[str, Any]]:
    """Gmail üzerindeki e-postaları tarar, uygun olanları indirir ve ayrıştırır.

    Args:
        config (Dict[str, Any]): Yapılandırma verileri.
        db (Database): Veritabanı yönetim nesnesi.
        mmo_ids (Set[Tuple[str, str]]): MMO mükerrer kontrol kümesi.

    Returns:
        List[Dict[str, Any]]: Başarıyla işlenen raporların verileri.
    """
    service: Any
    label_map: Dict[str, str]
    service, label_map = _auth_gmail(config)
    
    search_cfg: Dict[str, Any] = config.get("search_settings", {})
    search_by_label: bool = search_cfg.get("search_by_label", False)
    num_workers: int = search_cfg.get("num_workers", 10)
    force: bool = config.get("database_settings", {}).get("force_reprocess_all", False)
    only_unread: bool = search_cfg.get("search_only_unread", False)
    
    if force:
        log.info("⚠️ DİKKAT: 'Zaten işlenmiş e-postaları tekrar işle' seçeneği aktif.")

    res_filter: Optional[ResolutionFilter] = None
    if search_by_label:
        resolver: LabelResolver = config.get("_label_resolver", LabelResolver(config))
        res_labels: List[str] = [resolver.color_label("Mavi"), resolver.color_label("Yeşil")]
        res_filter = _build_res_filter(service, res_labels)

    proc_map: Dict[str, Dict[str, Any]] = db.load_email_map()
    proc_ids: Set[str] = db.load_report_ids()
    all_ids: Set[str] = set()
    appointment_ids: Set[str] = set()

    appt_cfg: Dict[str, Any] = config.get("appointment_email_settings", {})
    appt_only_unread: bool = appt_cfg.get("search_only_unread", only_unread)

    if search_by_label:
        resolver_inst: Optional[LabelResolver] = config.get("_label_resolver")
        
        for label in search_cfg.get("target_labels", []):
            search_label: str = label
            if resolver_inst and getattr(resolver_inst, '_use_tree', False) and getattr(resolver_inst, '_parent', ''):
                if not search_label.startswith(resolver_inst._parent):
                    search_label = f"{resolver_inst._parent}/{search_label}"

            q: str = f'label:"{search_label}"'
            if only_unread:
                q += " is:unread"
            
            days_map: Dict[str, Any] = search_cfg.get("label_specific_days_before", {})
            days: Any = days_map.get(label)
            if not days and ("Randevu" in label or "Appointment" in label):
                days = appt_cfg.get("randevu_search_days", 60)
                
            if days and isinstance(days, int):
                cutoff: datetime = datetime.now() - timedelta(days=days)
                q += f' after:{cutoff.strftime("%Y/%m/%d")}'
                
            log.info(f"🔎 Etiket taranıyor: {q}")
            for msg in get_all_messages(service, q):
                all_ids.add(msg["id"])

        appt_sources: List[Dict[str, str]] = [s for s in config.get("sources", []) if s.get("processor") == "appointment"]
        if appt_sources:
            appt_days: int = appt_cfg.get("randevu_search_days", 60)
            appt_senders_q: str = " OR ".join(f'from:{s["query"]}' for s in appt_sources)
            aq: str = f"({appt_senders_q})"
            
            if appt_only_unread:
                aq += " is:unread"
                
            if appt_days:
                cutoff_appt: datetime = datetime.now() - timedelta(days=appt_days)
                aq += f' after:{cutoff_appt.strftime("%Y/%m/%d")}'
                
            log.info(f"🔎 Randevu kaynakları taranıyor: {aq}")
            for msg in get_all_messages(service, aq):
                all_ids.add(msg["id"])
                appointment_ids.add(msg["id"])
    else:
        sources: List[Dict[str, str]] = config.get("sources", [])
        if sources:
            report_sources: List[Dict[str, str]] = [s for s in sources if s.get("processor") != "appointment"]
            appt_sources_list: List[Dict[str, str]] = [s for s in sources if s.get("processor") == "appointment"]

            if report_sources:
                sender_q: str = " OR ".join(f'from:{s["query"]}' for s in report_sources)
                q_sender: str = f"({sender_q})"
                
                if only_unread:
                    q_sender += " is:unread"
                    
                days_sender: int = search_cfg.get("search_days_before_today", 0)
                if days_sender > 0:
                    cutoff_sender: datetime = datetime.now() - timedelta(days=days_sender)
                    q_sender += f' after:{cutoff_sender.strftime("%Y/%m/%d")}'
                    
                log.info(f"🔎 Gönderen bazlı genel arama: {q_sender}")
                for msg in get_all_messages(service, q_sender):
                    all_ids.add(msg["id"])

            if appt_sources_list:
                appt_q_parts: str = " OR ".join(f'from:{s["query"]}' for s in appt_sources_list)
                aq_list: str = f"({appt_q_parts})"
                
                if appt_only_unread:
                    aq_list += " is:unread"
                    
                appt_days_list: int = appt_cfg.get("randevu_search_days", 60)
                if appt_days_list:
                    cutoff_appt_list: datetime = datetime.now() - timedelta(days=appt_days_list)
                    aq_list += f' after:{cutoff_appt_list.strftime("%Y/%m/%d")}'
                    
                log.info(f"🔎 Randevu gönderenleri taranıyor: {aq_list}")
                for msg in get_all_messages(service, aq_list):
                    all_ids.add(msg["id"])
                    appointment_ids.add(msg["id"])

    if not all_ids:
        log.info("📭 Aranan kriterlere uygun yeni e-posta bulunamadı.")
        results: List[Dict[str, Any]] = []
    else:
        messages: List[Dict[str, Any]] = [{"id": mid} for mid in all_ids]
        log.info(f"📬 Toplamda {len(messages)} benzersiz e-posta işleme kuyruğuna alındı.")
        results = process_messages(messages, service, config, db, proc_map, proc_ids, mmo_ids,
                                   resolution_filter=res_filter, num_workers=num_workers,
                                   force_ids=appointment_ids)

        if search_by_label and results:
            target_set: Set[str] = set(search_cfg.get("target_labels", []))
            if target_set:
                before: int = len(results)
                allowed_colors: Set[str] = set()
                
                for t in target_set:
                    t_lower: str = t.lower()
                    if "kırmızı" in t_lower:
                        allowed_colors.add("Kırmızı")
                    elif "sarı" in t_lower:
                        allowed_colors.add("Sarı")
                    elif "mavi" in t_lower:
                        allowed_colors.add("Mavi")
                    elif "yeşil" in t_lower:
                        allowed_colors.add("Yeşil")
                    elif "randevu" in t_lower:
                        allowed_colors.add("Randevu")
                
                filtered_results: List[Dict[str, Any]] = []
                for r in results:
                    lbl_color: str = str(r.get("label_color", ""))
                    if lbl_color in allowed_colors or lbl_color == "":
                        filtered_results.append(r)
                    else:
                        bina_adi: str = str(r.get("building_name", "Bilinmeyen Bina"))
                        asansor_no: str = str(r.get("elevator_number", "Bilinmeyen No"))
                        
                        log.info(
                            f"🎯 [RENK FİLTRESİ] Rapor hedeflenmediği için çıkarıldı "
                            f"| Bina: '{bina_adi}' | Asansör No: '{asansor_no}' | Renk: '{lbl_color}'"
                        )
                
                results = filtered_results
                
                diff: int = before - len(results)
                if diff > 0:
                    log.info(f"🎯 [RENK FİLTRESİ] İstenmeyen renge sahip toplam {diff} rapor hedeflenmediği için listeden çıkarıldı.")

    man_cfg: Dict[str, Any] = config.get("manual_source_settings", {})
    if man_cfg.get("enabled"):
        results.extend(_process_manual(man_cfg, db))
        
    return results


def _run_local(config: Dict[str, Any], db: Database) -> List[Dict[str, Any]]:
    """Yerel diskteki 'indirilenler' klasöründeki PDF dosyalarını tarar ve işler.

    Args:
        config (Dict[str, Any]): Yapılandırma verileri.
        db (Database): Veritabanı nesnesi.

    Returns:
        List[Dict[str, Any]]: İşlenen yerel PDF'lerden elde edilen veriler.
    """
    folder: str = config.get("paths", {}).get("download_folder", "")
    if not folder or folder.strip() == "":
        folder = os.path.join(str(Path.home()), "AsansorRaporlari", "raporlar")
        
    if not os.path.exists(folder):
        log.warning(f"Yerel klasör bulunamadı: {folder}")
        return []
        
    files: List[str] = [os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    proc_ids: Set[str] = db.load_report_ids()
    log.info(f"📂 Yerel klasörde {len(files)} adet PDF dosyası tespit edildi.")
    
    results: List[Dict[str, Any]] = []
    for fpath in files:
        result: Any = detect_and_parse(fpath, db=db)
        if result:
            rdict: Dict[str, Any] = result.to_dict()
            uid: str = result.unique_key
            if uid not in proc_ids:
                results.append(rdict)
                proc_ids.add(uid)
                db.add_report(uid)
                
    return results


def _run_cleanup(config: Dict[str, Any]) -> None:
    """Gmail Gelen Kutusu (Inbox) için yapılandırılmış temizlik kurallarını çalıştırır.
    
    Args:
        config (Dict[str, Any]): Yapılandırma verileri.
    """
    service: Any
    lm: Dict[str, str]
    service, lm = _auth_gmail(config)
    s: Dict[str, Any] = config.get("cleanup_mode_settings", {})
    
    if not s.get("enabled"):
        log.error("Temizlik modu aktif değil.")
        return
        
    is_test: bool = s.get("run_in_test_mode", True)
    if not is_test:
        log.critical("!!! CANLI TEMİZLİK MODU BAŞLATILIYOR. 2 saniye bekleniyor...")
        time.sleep(2)
        
    t: int = run_rules_engine(service, s, lm, is_test, create_cleanup_request)
    log.info(f"TEMİZLİK İŞLEMİ TAMAMLANDI: Toplam {t} e-posta işlendi.")


def _run_delete_label(config: Dict[str, Any]) -> None:
    """Yapılandırmada belirtilen etiketleri Gmail üzerinden kalıcı olarak siler.
    
    Args:
        config (Dict[str, Any]): Yapılandırma verileri.
    """
    service: Any
    lm: Dict[str, str]
    service, lm = _auth_gmail(config)
    s: Dict[str, Any] = config.get("label_delete_settings", {})
    
    if not s.get("enabled"):
        log.error("Etiket silme modu aktif değil.")
        return
        
    is_test: bool = s.get("run_in_test_mode", True)
    if not is_test:
        log.critical("!!! CANLI ETİKET SİLME MODU. 2 saniye bekleniyor...")
        time.sleep(2)
        
    for name in s.get("labels_to_delete_permanently", []):
        delete_label(service, name, lm, is_test)


def _run_trash(config: Dict[str, Any]) -> None:
    """Belirli kurallara uyan e-postaları Çöp Kutusu'na (Trash) taşır.
    
    Args:
        config (Dict[str, Any]): Yapılandırma verileri.
    """
    service: Any
    lm: Dict[str, str]
    service, lm = _auth_gmail(config)
    s: Dict[str, Any] = config.get("trash_mode_settings", {})
    
    if not s.get("enabled"):
        log.error("Çöp modu aktif değil.")
        return
        
    is_test: bool = s.get("run_in_test_mode", True)
    if not is_test:
        log.critical("!!! CANLI ÇÖP MODU BAŞLATILIYOR. 2 saniye bekleniyor...")
        time.sleep(2)
        
    t: int = run_rules_engine(service, s, lm, is_test, create_trash_request)
    log.info(f"ÇÖP İŞLEMİ TAMAMLANDI: Toplam {t} e-posta işlendi.")


def _build_res_filter(service: Any, label_names: List[str]) -> ResolutionFilter:
    """Mavi veya Yeşil etiketli raporlar üzerinden akıllı bir çözümleme dizini oluşturur.

    Args:
        service (Any): Gmail API servisi.
        label_names (List[str]): Taranacak etiket isimleri.

    Returns:
        ResolutionFilter: Çözümlenmiş raporları içeren filtre nesnesi.
    """
    rf: ResolutionFilter = ResolutionFilter()
    log.info("🔎 Çözülmüş rapor indeksi oluşturuluyor (Mavi/Yeşil)...")
    msgs: List[Dict[str, Any]] = []
    
    for label in label_names:
        msgs.extend(get_all_messages(service, f'label:"{label}"'))
        
    if not msgs:
        return rf

    def _cb(rid: str, res: Any, exc: Any) -> None:
        if not exc and res:
            h: List[Dict[str, str]] = res.get("payload", {}).get("headers", [])
            s: str = next((x["value"] for x in h if x["name"].lower() == "subject"), "")
            f: str = next((x["value"] for x in h if x["name"].lower() == "from"), "")
            sn: str = res.get("snippet", "")
            d: int = int(res.get("internalDate", 0))
            rf.add_resolved(s, sn, f, d)

    batch_fetch_messages(service, [m["id"] for m in msgs], _cb)
    log.info(f"✅ Çözüm indeksi tamamlandı: {len(msgs)} rapor analiz edildi.")
    return rf


def _process_manual(man_cfg: Dict[str, Any], db: Database) -> List[Dict[str, Any]]:
    """'Manuel' klasörüne elle atılan PDF dosyalarını tarar, ayrıştırır ve taşır.

    Args:
        man_cfg (Dict[str, Any]): Manuel işlem yapılandırması.
        db (Database): Veritabanı nesnesi.

    Returns:
        List[Dict[str, Any]]: Manuel işlenen dosyalardan çıkan sonuçlar.
    """
    folder: str = man_cfg.get("folder_path", "data/manuel")
    proc_folder: str = man_cfg.get("processed_folder_path", "data/manuel/islenenler")
    
    if not os.path.exists(folder):
        return []
        
    log.info(f"📂 Manuel klasör taranıyor: {folder}")
    files: List[str] = [f for f in os.listdir(folder) if f.lower().endswith(".pdf")]
    
    if not files:
        log.info("Manuel klasörde işlenecek PDF bulunamadı.")
        return []
        
    os.makedirs(proc_folder, exist_ok=True)
    results: List[Dict[str, Any]] = []
    
    for fname in files:
        fpath: str = os.path.join(folder, fname)
        result: Any = detect_and_parse(fpath, db=db)
        if result:
            results.append(result.to_dict())
            if man_cfg.get("move_processed_files", True):
                try:
                    shutil.move(fpath, os.path.join(proc_folder, fname))
                except Exception as e:
                    log.error(f"Dosya taşıma hatası: {e}")
        else:
            log.warning(f"Dosya işlenemedi (Desteklenmiyor veya Hatalı): {fname}")
            
    return results


def _deduplicate(results: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Aynı bina ve asansör için gelen mükerrer veya eski tarihli raporları eler.

    Args:
        results (List[Dict[str, Any]]): Tüm işlenen rapor listesi.

    Returns:
        Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]: 
            1. Sadece en güncel raporları içeren benzersiz liste (Final).
            2. Elenen (daha eski veya mükerrer) raporların listesi (Skipped).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    
    for r in results:
        key: str = f"{r.get('building_name','')}" + " - " + f"{r.get('elevator_number','')}"
        groups.setdefault(key, []).append(r)
        
    final: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    
    for items in groups.values():
        def pd(d: str) -> datetime:
            """Güvenli tarih çevirici (Safe Date Parser)."""
            try:
                return datetime.strptime(d, "%d.%m.%Y")
            except Exception:
                try:
                    return datetime.strptime(d.replace("/", "."), "%d.%m.%Y")
                except Exception:
                    return datetime.min
        
        items.sort(key=lambda x: pd(x.get("inspection_date", "")), reverse=True)
        final.append(items[0])
        skipped.extend(items[1:])

    def sort_key(r: Dict[str, Any]) -> datetime:
        """Çıktı sıralaması için bir sonraki muayene tarihini temel alır."""
        d: str = r.get("next_inspection", "")
        try:
            return datetime.strptime(d, "%d.%m.%Y")
        except Exception:
            try:
                return datetime.strptime(d.replace("/", "."), "%d.%m.%Y")
            except Exception:
                return datetime.max
            
    final.sort(key=sort_key)
    
    return final, skipped