"""
Asansör Denetçisi - Periyodik asansör muayene raporu otomasyonu.

Ana giriş noktası: Uygulamayı komut satırı, web arayüzü veya izleme modunda başlatır.
Terminal üzerinden yürütülen işlemlerin sonuçlarını web arayüzü ile senkronize eder.
"""

import logging
import argparse
import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

from app.core.engine import run, run_watch
from app.web.server import start_server
from app.utils.logging import get_logger
from app.config import load_config, save_config
from app.core.database import Database, get_task_result, set_task_result

from colorama import Fore, Style, init

init(autoreset=True)

log: logging.Logger = get_logger("run")


def _update_web_results(new_results: Optional[List[Dict[str, Any]]]) -> None:
    """Terminal üzerinden tamamlanan işlem sonuçlarını veritabanına senkronize eder.
    
    Veri kaybını önlemek ve eşzamanlı çalışma uyumluluğunu sağlamak için 
    TaskResult tablosu kullanılarak atomik okuma ve yazma işlemi gerçekleştirilir.
    
    Args:
        new_results (Optional[List[Dict[str, Any]]]): İşlenen yeni rapor veya randevuların listesi.
    """
    if not new_results:
        return

    try:
        task_name: str = "web_last_results"
        
        existing_task: Optional[Dict[str, Any]] = get_task_result(task_name)
        existing_results: List[Dict[str, Any]] = []
        
        if existing_task and "data" in existing_task:
            existing_results = existing_task["data"]
            if not isinstance(existing_results, list):
                existing_results = []

        existing_map: Dict[str, Dict[str, Any]] = {
            str(r.get("uuid", r.get("file_name", ""))): r for r in existing_results
        }
        
        r: Dict[str, Any]
        for r in new_results:
            key: str = str(r.get("uuid", r.get("file_name", "")))
            if not key:
                continue
            existing_map[key] = r

        updated_list: List[Dict[str, Any]] = list(existing_map.values())
        
        set_task_result(task_name, {"data": updated_list})
        
        log.info(f"🔄 Web arayüzü verileri veritabanında başarıyla güncellendi ({len(new_results)} yeni kayıt).")
    except Exception as e:
        log.error(f"Web sonuçları veritabanı senkronizasyon hatası: {e}")


def main() -> None:
    """Uygulama başlatıcı ve komut satırı parametre yönlendiricisi.
    
    Argparse aracılığıyla gelen parametreleri analiz eder, yapılandırmayı yükler
    ve uygulamayı istenen modda çalıştırır.
    """
    parser: argparse.ArgumentParser = argparse.ArgumentParser(description="Asansör Rapor Otomasyonu - Ana Giriş")
    
    parser.add_argument("--web", action="store_true", help="Web arayüzünü başlatır")
    parser.add_argument("--watch", action="store_true", help="İzleme modu: Belirli aralıklarla otomatik tarama yapar")
    parser.add_argument("-i", "--interval", dest="interval", type=int, default=None, help="İzleme aralığı (Dakika)")
    parser.add_argument("-H", "--host", dest="host", default=None, help="Web sunucu adresi")
    parser.add_argument("-p", "--port", dest="port", type=int, default=None, help="Web sunucu portu")
    parser.add_argument("-m", "--mode", dest="mode", choices=["gmail", "local", "cleanup", "delete_label", "trash_emails"],
                        help="Çalışma modunu geçici olarak değiştirir")
    parser.add_argument("-c", "--config", dest="config", default=None, help="Kullanılacak yapılandırma dosyası yolu")
    
    parser.add_argument("-L", "--list-pdfs", dest="list_pdfs", action="store_true", help="Veritabanında kayıtlı tüm PDF raporlarını listeler")
    parser.add_argument("-E", "--export", dest="export", type=int, metavar="PDF_ID", help="Belirtilen ID'ye sahip PDF raporunu diske çıkarır")
    parser.add_argument("-O", "--export-dir", dest="export_dir", default=".", help="Dışa aktarılan PDF'in kaydedileceği klasör")

    search_group: Any = parser.add_argument_group("Arama ve E-posta İşleme Ayarları")
    search_group.add_argument("--archive", dest="archive_emails", action="store_true", help="İşlem sonrası e-postaları arşivler")
    search_group.add_argument("--read", dest="mark_as_read", action="store_true", help="İşlem sonrası e-postaları okundu işaretler")
    search_group.add_argument("--by-label", dest="search_by_label", action="store_true", help="Aramayı yalnızca hedef etiketlere göre yapar")
    search_group.add_argument("-w", "--workers", dest="num_workers", type=int, help="Eşzamanlı çalışacak işçi sayısı")
    search_group.add_argument("-d", "--days", dest="search_days", type=int, help="Bugünden geriye dönük aranacak gün sayısı")
    search_group.add_argument("-l", "--labels", dest="target_labels", nargs="+", type=str, help="Arama yapılacak hedef etiketler (boşlukla ayırarak)")
    search_group.add_argument("--skip-words", dest="exceptional_keywords", nargs="+", type=str, help="Hariç tutulacak kelimeler")
    search_group.add_argument("--skip-mails", dest="exceptional_senders", nargs="+", type=str, help="Hariç tutulacak gönderen adresleri")

    appointment_group: Any = parser.add_argument_group("Randevu E-Posta Ayarları")
    appointment_group.add_argument("--appt", dest="enable_appointments", action="store_true", help="Randevu e-postası işlemeyi aktif eder")
    appointment_group.add_argument("--hide-done", dest="filter_resolved", action="store_true", help="Çözülmüş randevuları gizler")
    appointment_group.add_argument("--hide-past", dest="filter_past_dates", action="store_true", help="Geçmiş tarihli randevuları gizler")
    appointment_group.add_argument("--appt-days", dest="randevu_search_days", type=int, help="Randevu araması için geriye dönük gün sayısı")
    appointment_group.add_argument("--appt-label", dest="randevu_label", type=str, help="Randevular için kullanılacak etiket adı")

    db_group: Any = parser.add_argument_group("Veritabanı Ayarları")
    db_group.add_argument("-f", "--force", dest="force_reprocess", action="store_true", help="Tüm PDF'leri zorla yeniden işler")
    db_group.add_argument("--dups", dest="allow_duplicates", action="store_true", help="Mükerrer indirmelere izin verir")

    misc_group: Any = parser.add_argument_group("Manuel Kaynak ve Karantina Ayarları")
    misc_group.add_argument("--manual", dest="enable_manual_source", action="store_true", help="Manuel klasör üzerinden okumayı aktif eder")
    misc_group.add_argument("-F", "--folder", dest="manual_folder", type=str, help="Manuel işlenecek dosyaların bulunduğu klasör yolu")
    misc_group.add_argument("-q", "--quarantine", dest="enable_quarantine", action="store_true", help="Hatalı işlemlerde karantina modunu aktif eder")
    misc_group.add_argument("--max-fail", dest="quarantine_max_fail", type=int, help="Karantinaya girmeden önceki maksimum hata sayısı")

    cleanup_group: Any = parser.add_argument_group("Temizlik, Etiket ve Çöp Modu Ayarları")
    cleanup_group.add_argument("--clean", dest="enable_cleanup", action="store_true", help="Temizlik modunu aktif eder")
    cleanup_group.add_argument("--del-labels", dest="enable_label_delete", action="store_true", help="Etiket silme modunu aktif eder")
    cleanup_group.add_argument("--trash", dest="enable_trash_mode", action="store_true", help="Çöp kutusu işleme modunu aktif eder")
    cleanup_group.add_argument("--real", dest="real_run", action="store_true", help="Test modunu kapatır")
    cleanup_group.add_argument("--rm-labels", dest="labels_to_delete", nargs="+", type=str, help="Kalıcı olarak silinecek etiketler")
    cleanup_group.add_argument("--clean-rules", dest="cleanup_rules", nargs="+", type=str, help="Temizlik modunda uygulanacak kurallar")
    cleanup_group.add_argument("--trash-rules", dest="trash_rules", nargs="+", type=str, help="Çöp kutusu modunda uygulanacak kurallar")

    args: argparse.Namespace = parser.parse_args()

    try:
        config: Dict[str, Any] = load_config(args.config)
    except FileNotFoundError as e:
        log.error(str(e))
        sys.exit(1)
    except Exception as e:
        log.error(f"Yapılandırma yüklenirken beklenmeyen hata: {e}")
        sys.exit(1)

    config_changed: bool = False
    
    if args.mode:
        config["mode"] = args.mode
        config_changed = True
        log.info(f"⚙️ Çalışma modu değiştirildi: {args.mode}")

    if args.interval is not None:
        config.setdefault("watch_settings", {})["interval_minutes"] = args.interval
        config_changed = True
        log.info(f"⚙️ İzleme aralığı değiştirildi: {args.interval} dakika")

    if args.archive_emails:
        config.setdefault("search_settings", {})["archive_after_processing"] = True
        config_changed = True
        log.info("⚙️ Ayar: E-postalar işlem sonrası arşivlenecek")
        
    if args.mark_as_read:
        config.setdefault("search_settings", {})["mark_as_read_after_processing"] = True
        config_changed = True
        log.info("⚙️ Ayar: E-postalar işlem sonrası okundu işaretlenecek")
        
    if args.search_by_label:
        config.setdefault("search_settings", {})["search_by_label"] = True
        config_changed = True
        log.info("⚙️ Ayar: Arama etiketlere göre yapılacak")
        
    if args.num_workers is not None:
        config.setdefault("search_settings", {})["num_workers"] = args.num_workers
        config_changed = True
        log.info(f"⚙️ Ayar: İş parçacığı sayısı {args.num_workers} olarak ayarlandı")
        
    if args.search_days is not None:
        config.setdefault("search_settings", {})["search_days_before_today"] = args.search_days
        config_changed = True
        log.info(f"⚙️ Ayar: Arama {args.search_days} gün geriye dönük yapılacak")

    if args.target_labels is not None:
        config.setdefault("search_settings", {})["target_labels"] = args.target_labels
        config_changed = True
        log.info(f"⚙️ Ayar: Hedef etiketler güncellendi: {args.target_labels}")

    if args.exceptional_keywords is not None:
        config.setdefault("search_settings", {})["exceptional_keywords"] = args.exceptional_keywords
        config_changed = True
        log.info(f"⚙️ Ayar: İstisna kelimeler güncellendi: {args.exceptional_keywords}")

    if args.exceptional_senders is not None:
        config.setdefault("search_settings", {})["exceptional_senders"] = args.exceptional_senders
        config_changed = True
        log.info(f"⚙️ Ayar: İstisna gönderenler güncellendi: {args.exceptional_senders}")

    if args.enable_appointments:
        config.setdefault("appointment_email_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Randevu modülü aktif edildi")
        
    if args.filter_resolved:
        config.setdefault("appointment_email_settings", {})["filter_if_resolved"] = True
        config_changed = True
        log.info("⚙️ Ayar: Çözülmüş randevular filtrelenecek")
        
    if args.filter_past_dates:
        config.setdefault("appointment_email_settings", {})["filter_past_dates"] = True
        config_changed = True
        log.info("⚙️ Ayar: Geçmiş tarihli randevular filtrelenecek")
        
    if args.randevu_search_days is not None:
        config.setdefault("appointment_email_settings", {})["randevu_search_days"] = args.randevu_search_days
        config_changed = True
        log.info(f"⚙️ Ayar: Randevu araması {args.randevu_search_days} gün yapılacak")

    if args.randevu_label is not None:
        config.setdefault("appointment_email_settings", {})["randevu_label_name"] = args.randevu_label
        config_changed = True
        log.info(f"⚙️ Ayar: Randevu etiket adı güncellendi: {args.randevu_label}")

    if args.force_reprocess:
        config.setdefault("database_settings", {})["force_reprocess_all"] = True
        config_changed = True
        log.info("⚙️ Ayar: Tüm veritabanı kayıtları zorla yeniden işlenecek")
        
    if args.allow_duplicates:
        config.setdefault("database_settings", {})["skip_duplicate_downloads"] = False
        config_changed = True
        log.info("⚙️ Ayar: Mükerrer indirmelere izin verildi")

    if args.enable_manual_source:
        config.setdefault("manual_source_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Manuel klasörden dosya okuma aktif edildi")
        
    if args.manual_folder:
        config.setdefault("manual_source_settings", {})["folder_path"] = args.manual_folder
        config_changed = True
        log.info(f"⚙️ Ayar: Manuel işleme klasörü {args.manual_folder} olarak atandı")
        
    if args.enable_quarantine:
        config.setdefault("quarantine_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Karantina modu aktif edildi")
        
    if args.quarantine_max_fail is not None:
        config.setdefault("quarantine_settings", {})["max_fail_count"] = args.quarantine_max_fail
        config_changed = True
        log.info(f"⚙️ Ayar: Karantina maksimum hata sayısı {args.quarantine_max_fail} yapıldı")

    if args.enable_cleanup:
        config.setdefault("cleanup_mode_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Temizlik modu aktif edildi")
        
    if args.enable_label_delete:
        config.setdefault("label_delete_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Etiket silme modu aktif edildi")
        
    if args.enable_trash_mode:
        config.setdefault("trash_mode_settings", {})["enabled"] = True
        config_changed = True
        log.info("⚙️ Ayar: Çöp modu aktif edildi")

    if args.real_run:
        config.setdefault("cleanup_mode_settings", {})["run_in_test_mode"] = False
        config.setdefault("label_delete_settings", {})["run_in_test_mode"] = False
        config.setdefault("trash_mode_settings", {})["run_in_test_mode"] = False
        config_changed = True
        log.warning("⚠️ DİKKAT: Test modu devre dışı bırakıldı! Gerçek işlemler yapılacak.")

    if args.labels_to_delete is not None:
        config.setdefault("label_delete_settings", {})["labels_to_delete_permanently"] = args.labels_to_delete
        config_changed = True
        log.info(f"⚙️ Ayar: Silinecek etiketler listesi güncellendi: {args.labels_to_delete}")

    if args.cleanup_rules is not None:
        config.setdefault("cleanup_mode_settings", {})["cleanup_rules"] = args.cleanup_rules
        config_changed = True
        log.info(f"⚙️ Ayar: Temizlik kuralları güncellendi: {args.cleanup_rules}")

    if args.trash_rules is not None:
        config.setdefault("trash_mode_settings", {})["trash_rules"] = args.trash_rules
        config_changed = True
        log.info(f"⚙️ Ayar: Çöp kutusu kuralları güncellendi: {args.trash_rules}")

    if config_changed:
        try:
            save_config(config, args.config)
        except Exception as e:
            log.error(f"Yapılandırma dosyasına yazılırken hata oluştu: {e}")

    if args.list_pdfs or args.export:
        db_path: str = config.get("paths", {}).get("database", "")
        if not db_path:
            log.error("Veritabanı yolu yapılandırma dosyasında bulunamadı.")
            sys.exit(1)
            
        try:
            db: Database = Database(db_path)
            
            if args.list_pdfs:
                pdfs: List[Dict[str, Any]] = db.list_pdfs()
                
                header: str = f"{Fore.CYAN}{'ID':<6} | {'BİNA ADI':<25} | {'KAYIT TARİHİ':<20} | {'DURUM'}"
                separator: str = f"{Fore.WHITE}{'=' * 6}+{'' + '-' * 27}+{'' + '-' * 22}+{'' + '-' * 15}"

                print(f"\n{Fore.YELLOW}{Style.BRIGHT}   MEVCUT BİNA RAPORLARI LİSTESİ")
                print(separator)
                print(header)
                print(separator)

                if not pdfs:
                    print(f"{Fore.RED} Veritabanında henüz bir rapor kaydı bulunmuyor.")
                else:
                    p: Dict[str, Any]
                    for p in pdfs:
                        p_id: str = str(p.get('id', '-'))
                        building: str = (p.get('building') or 'Belirtilmemiş')[:25]
                        date: str = (p.get('stored_at') or 'Bilinmiyor')[:19]
                        label: str = (p.get('label_color') or 'Standart').upper()
                        
                        label_style: str = Fore.WHITE
                        if 'KIRMIZI' in label or 'RED' in label:
                            label_style = Fore.RED
                        elif 'YEŞİL' in label or 'GREEN' in label:
                            label_style = Fore.GREEN
                        elif 'SARI' in label or 'YELLOW' in label:
                            label_style = Fore.YELLOW
                        elif 'MAVİ' in label or 'BLUE' in label:
                            label_style = Fore.BLUE

                        print(
                            f"{Fore.GREEN}{p_id:<6}{Fore.WHITE} | "
                            f"{Style.BRIGHT}{building:<25}{Style.RESET_ALL}{Fore.WHITE} | "
                            f"{date:<20} | "
                            f"{label_style}{label:<15}"
                        )

                print(separator + "\n")
                return

            if args.export:
                pdf_record: Optional[Dict[str, Any]] = db.get_pdf(args.export)
                if not pdf_record:
                    log.error(f"Hata: {args.export} ID'li PDF veritabanında bulunamadı.")
                    sys.exit(1)
                    
                output_file_path: str = os.path.join(args.export_dir, pdf_record["file_name"])
                os.makedirs(args.export_dir, exist_ok=True)
                
                with open(output_file_path, "wb") as f:
                    f.write(pdf_record["file_data"])
                log.info(f"✅ PDF başarıyla dışa aktarıldı: {output_file_path}")
                return

        except Exception as e:
            log.error(f"Veritabanı işlemi sırasında hata: {e}")
            sys.exit(1)

    if args.web:
        server_host: str = args.host if args.host else config.get("web_settings", {}).get("host", "127.0.0.1")
        try:
            server_port: int = int(args.port) if args.port else int(config.get("web_settings", {}).get("port", 5001))
        except ValueError:
            log.error("Geçersiz port değeri tespit edildi, varsayılan port 5001 kullanılıyor.")
            server_port = 5001
            
        log.info("🌐 Web sunucusu modunda başlatılıyor...")
        start_server(host=server_host, port=server_port)
        
    elif args.watch:
        is_search_by_label: bool = config.get("search_settings", {}).get("search_by_label", False)
        if is_search_by_label:
            log.error("⛔ HATA: Etikete göre arama aktifken izleme modu kullanılamaz!")
            sys.exit(1)
            
        log.info("👀 İzleme modunda başlatılıyor...")
        run_watch()
        
    else:
        log.info("💻 Komut satırı modunda başlatılıyor...")
        results: Optional[List[Dict[str, Any]]] = run()
        
        if results:
            _update_web_results(results)
            log.info(f"✅ İşlem tamamlandı. Toplam {len(results)} kayıt işlendi ve veritabanına aktarıldı.")
        else:
            log.info("📭 İşlenecek yeni kayıt bulunamadı.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("🛑 İşlem kullanıcı tarafından durduruldu.")
        sys.exit(0)
    except Exception as unexpected_error:
        log.critical(f"Sistemde kritik bir hata oluştu: {unexpected_error}")
        sys.exit(1)