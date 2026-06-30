"""Web sunucusu modülü: Uygulamanın arayüzünü ve API uç noktalarını yönetir."""

import json
import logging
import os
import threading
from io import BytesIO
from pathlib import Path
from typing import Any, Tuple, Dict, List, Optional, Union, cast

from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_socketio import SocketIO
from werkzeug.datastructures import FileStorage
from sqlalchemy.orm import Session

from app.config import load_config, save_config
from app.utils.logging import setup_logging, set_socketio, get_recent_logs, get_logger
from app.core.engine import run
from app.core.database import Database, get_task_result, set_task_result, get_secure_config, set_secure_config, delete_secure_config
from app.downloaders.engine import reload_profiles
from app.paths import paths

log: logging.Logger = get_logger(__name__)

_running: bool = False
_watch_running: bool = False
_run_start_time: Optional[float] = None
_run_id: int = 0
_progress: Dict[str, Any] = {"total": 0, "done": 0, "phase": ""}
_last_error: str = ""
_lock: threading.Lock = threading.Lock()

db: Database = Database()


def _get_unique_key(r: Dict[str, Any]) -> str:
    """Rapor sözlüğünden benzersiz kimliği güvenli şekilde çıkarır.

    Args:
        r (Dict[str, Any]): İşlenmiş rapor verilerini içeren sözlük.
        
    Returns:
        str: Rapor için güvenli ve benzersiz kimlik dizgesi.
    """
    uid_raw: Any = r.get("uuid", "")
    uid: str = str(uid_raw)
    
    if uid and uid != "N/A" and uid != "None":
        return uid
        
    file_name_raw: Any = r.get("file_name", "")
    return str(file_name_raw)


def _backup_to_archive(results_to_archive: List[Dict[str, Any]]) -> None:
    """Belirtilen sonuç listesini veritabanı silinmeden önce arşive alır.
    
    Args:
        results_to_archive (List[Dict[str, Any]]): Arşivlenecek rapor/randevu öğeleri.
    """
    if not results_to_archive:
        return
        
    arch_data: Optional[Dict[str, Any]] = get_task_result("web_archived_results")
    arch_safe: Dict[str, Any] = arch_data if arch_data else {}
    arch_raw: Any = arch_safe.get("data", [])
    arch_list: List[Dict[str, Any]] = []
    
    if isinstance(arch_raw, list):
        raw_list: List[Any] = cast(List[Any], arch_raw)
        for item in raw_list:
            if isinstance(item, dict):
                arch_list.append(cast(Dict[str, Any], item))
                
    arch_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in arch_list}
    for r in results_to_archive:
        arch_map[_get_unique_key(r)] = r
        
    set_task_result("web_archived_results", {"data": list(arch_map.values())})


def _remove_from_archive(ids_to_remove: List[str]) -> None:
    """Belirtilen kimliklere sahip sonuçları arşivden kalıcı olarak temizler.
    
    Args:
        ids_to_remove (List[str]): Arşivden çıkarılacak eşsiz kimlikler.
    """
    if not ids_to_remove:
        return
        
    arch_data: Optional[Dict[str, Any]] = get_task_result("web_archived_results")
    arch_safe: Dict[str, Any] = arch_data if arch_data else {}
    arch_raw: Any = arch_safe.get("data", [])
    arch_list: List[Dict[str, Any]] = []
    
    if isinstance(arch_raw, list):
        raw_list: List[Any] = cast(List[Any], arch_raw)
        for item in raw_list:
            if isinstance(item, dict):
                arch_list.append(cast(Dict[str, Any], item))
                
    valid_arch: List[Dict[str, Any]] = [r for r in arch_list if _get_unique_key(r) not in ids_to_remove]
    set_task_result("web_archived_results", {"data": valid_arch})


def create_app() -> Tuple[Flask, SocketIO]:
    """Flask web uygulamasını ve SocketIO eklentisini oluşturur ve yapılandırır.
    
    Returns:
        Tuple[Flask, SocketIO]: Başlatılmış Flask uygulaması ve SocketIO sunucusu.
    """
    template_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
    static_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
    
    app: Flask = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    
    secret_env: Optional[str] = os.environ.get("FLASK_SECRET")
    app.config["SECRET_KEY"] = secret_env if secret_env is not None else os.urandom(24)
    
    socketio: SocketIO = SocketIO(
        app, 
        cors_allowed_origins="*", 
        async_mode="threading",
        logger=False, 
        engineio_logger=False,
        ping_timeout=120, 
        ping_interval=25,
    )
    
    set_socketio(socketio)

    @app.route("/")
    def index() -> str:  # pyright: ignore[reportUnusedFunction]
        """Ana web arayüzünü sunar."""
        with _lock:
            return render_template(
                "index.html",
                running=_running,
                watch_running=_watch_running,
                run_id=_run_id,
                progress=_progress,
                error=_last_error
            )

    @app.route("/api/status", methods=["GET"])
    def status() -> Response:  # pyright: ignore[reportUnusedFunction]
        """İşlem motorunun mevcut durumunu döndürür."""
        with _lock:
            return jsonify({
                "running": _running,
                "is_running": _running,
                "watching": _watch_running,
                "watch_running": _watch_running,
                "is_watching": _watch_running,
                "is_watch_running": _watch_running,
                "run_id": _run_id,
                "progress": _progress,
                "error": _last_error
            })

    @app.route("/api/run", methods=["POST"])
    def start_run() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """İşlem motorunu asenkron olarak tetikler."""
        global _running, _run_id, _progress, _last_error, _run_start_time
        
        with _lock:
            if _running:
                return jsonify({"status": "already_running"}), 409
                
            _running = True
            _run_id += 1
            _progress = {"total": 0, "done": 0, "phase": "Başlatılıyor..."}
            _last_error = ""
            
        def _run_thread() -> None:
            """Arka planda çalışan tetikleme iş parçacığı."""
            global _running, _progress, _last_error
            try:
                results: List[Dict[str, Any]] = run()
                
                if results:
                    with _lock:
                        stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
                        stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
                        
                        existing_results_raw: Any = stored_data_safe.get("data", [])
                        existing_results: List[Dict[str, Any]] = []
                        
                        if isinstance(existing_results_raw, list):
                            raw_list: List[Any] = cast(List[Any], existing_results_raw)
                            for item in raw_list:
                                if isinstance(item, dict):
                                    item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                                    existing_results.append(item_map)
                        
                        existing_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in existing_results}
                        for res in results:
                            existing_map[_get_unique_key(res)] = res
                            
                        merged_results: List[Dict[str, Any]] = list(existing_map.values())
                        set_task_result("web_last_results", {"data": merged_results})
                    
                with _lock:
                    _progress["phase"] = "Tamamlandı"
            except Exception as e:
                with _lock:
                    _last_error = str(e)
                    _progress["phase"] = "Hata oluştu"
            finally:
                with _lock:
                    _running = False
                    
        threading.Thread(target=_run_thread, daemon=True).start()
        
        return jsonify({"status": "started", "run_id": _run_id})

    @app.route("/api/watch/start", methods=["POST"])
    def watch_start() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Periyodik kontrol modunu başlatır."""
        global _watch_running
        
        try:
            config: Dict[str, Any] = load_config()
            search_settings_raw: Any = config.get("search_settings", {})
            is_search_by_label: bool = False
            
            if isinstance(search_settings_raw, dict):
                s_map: Dict[str, Any] = cast(Dict[str, Any], search_settings_raw)
                is_search_by_label = bool(s_map.get("search_by_label", False))
                
            if is_search_by_label:
                return jsonify({
                    "status": "error", 
                    "error": "Etikete göre arama aktifken İzleme modu kullanılamaz. Lütfen ayarlardan bu seçeneği kapatın."
                }), 400
        except Exception as e:
            log.error(f"Konfigürasyon okuma hatası: {e}")
        
        with _lock:
            if _watch_running:
                return jsonify({"status": "already_watching"}), 409
                
            _watch_running = True

        def _bg_watch() -> None:
            """Dinleme modunun kendi iş parçacığında çalışan ana döngüsü."""
            global _watch_running, _running, _run_id, _progress, _last_error
            try:
                from app.core.engine import run, _watch_stop  # pyright: ignore[reportPrivateUsage]
                _watch_stop.clear()  # pyright: ignore[reportPrivateUsage]
                
                cycle: int = 0
                
                while not _watch_stop.is_set():  # pyright: ignore[reportPrivateUsage]
                    cycle += 1
                    
                    bg_config: Dict[str, Any] = load_config()
                    ws_raw: Any = bg_config.get("watch_settings", {})
                    interval: int = 30
                    
                    if isinstance(ws_raw, dict):
                        ws_map: Dict[str, Any] = cast(Dict[str, Any], ws_raw)
                        interval_raw: Any = ws_map.get("interval_minutes", 30)
                        try:
                            interval = int(interval_raw)
                        except (ValueError, TypeError):
                            pass
                            
                    interval = max(1, interval)
                    
                    if cycle == 1:
                        log.info("=" * 50)
                        log.info(f"👁️  DİNLEME MODU — Her {interval} dakikada bir kontrol yapılacak")
                        log.info("=" * 50)
                    
                    log.info(f"🔄 Döngü #{cycle} başlıyor...")
                    
                    # Eşzamanlı başlatmaları engellemek için kontrol
                    can_run = False
                    with _lock:
                        if not _running:
                            _running = True
                            _run_id += 1
                            _progress = {"total": 0, "done": 0, "phase": f"İzleme (Döngü {cycle}) başlatılıyor..."}
                            _last_error = ""
                            can_run = True
                    
                    if not can_run:
                        log.info(f"🔄 Döngü #{cycle} atlandı: Halihazırda manuel bir tarama işlemi devam ediyor.")
                    else:
                        try:
                            socketio.emit("watch_cycle_started", {"cycle": cycle}, namespace="/logs")  # pyright: ignore[reportUnknownMemberType]
                            
                            results: List[Dict[str, Any]] = run()
                            
                            if results:
                                with _lock:
                                    stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
                                    stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
                                    
                                    existing_results_raw: Any = stored_data_safe.get("data", [])
                                    existing_results: List[Dict[str, Any]] = []
                                    
                                    if isinstance(existing_results_raw, list):
                                        raw_list: List[Any] = cast(List[Any], existing_results_raw)
                                        for item in raw_list:
                                            if isinstance(item, dict):
                                                item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                                                existing_results.append(item_map)
                                    
                                    existing_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in existing_results}
                                    for r in results:
                                        existing_map[_get_unique_key(r)] = r
                                    
                                    updated_list: List[Dict[str, Any]] = list(existing_map.values())
                                    set_task_result("web_last_results", {"data": updated_list})
                                
                                socketio.emit("results_updated", namespace="/logs")  # pyright: ignore[reportUnknownMemberType]
                                log.info(f"🔄 Döngü #{cycle} tamamlandı: {len(results)} yeni rapor eklendi.")
                            else:
                                log.info(f"🔄 Döngü #{cycle} tamamlandı: Yeni rapor bulunamadı.")
                                
                            with _lock:
                                _progress["phase"] = "İzleme tamamlandı"
                                
                        except Exception as e:
                            log.error(f"🔄 Döngü #{cycle} hatası: {e}", exc_info=True)
                            with _lock:
                                _last_error = str(e)
                                _progress["phase"] = "Hata oluştu"
                        finally:
                            with _lock:
                                _running = False

                    log.info(f"⏳ {interval} dakika bekleniyor...")
                    if _watch_stop.wait(timeout=interval * 60):  # pyright: ignore[reportPrivateUsage]
                        break

            except Exception as e:
                log.error(f"Dinleme modu genel hatası: {e}")
            finally:
                with _lock:
                    _watch_running = False
                log.info("👁️  Dinleme modu durduruldu.")

        threading.Thread(target=_bg_watch, daemon=True).start()
        
        return jsonify({"status": "started"})

    @app.route("/api/watch/stop", methods=["POST"])
    def watch_stop() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Periyodik kontrol modunu durdurur."""
        global _watch_running
        from app.core.engine import stop_watch
        
        with _lock:
            stop_watch()
            _watch_running = False
            
        return jsonify({"status": "stopped"})

    @app.route("/api/results", methods=["GET"])
    def get_results() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """İşlenmiş rapor sonuçlarını döndürür."""
        try:
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            all_results_raw: Any = stored_data_safe.get("data", [])
            all_results: List[Dict[str, Any]] = []
            
            if isinstance(all_results_raw, list):
                raw_list: List[Any] = cast(List[Any], all_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        all_results.append(item_map)
                        
            return jsonify(all_results)
        except Exception as error:
            log.error("Sonuçlar getirilirken hata: %s", str(error))
            return jsonify({"error": "Veritabanı hatası"}), 500

    @app.route("/api/report/delete/<item_id>", methods=["DELETE"])
    def delete_report_single(item_id: str) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Tekli bir raporu ID'sine göre hem listeden hem de veritabanından tamamen siler."""
        try:
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            all_results_raw: Any = stored_data_safe.get("data", [])
            all_results: List[Dict[str, Any]] = []
            
            if isinstance(all_results_raw, list):
                raw_list: List[Any] = cast(List[Any], all_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        all_results.append(item_map)
            
            if all_results:
                valid_results: List[Dict[str, Any]] = [r for r in all_results if _get_unique_key(r) != item_id]
                set_task_result("web_last_results", {"data": valid_results})
            
            _remove_from_archive([item_id])
                
            session: Session = db.Session()
            try:
                from app.core.models import PdfFile, ProcessedReport
                session.query(PdfFile).filter_by(report_id=item_id).delete()
                session.query(ProcessedReport).filter_by(report_id=item_id).delete()
                session.commit()
                log.info(f"🗑️ Rapor sistemden tamamen silindi: {item_id}")
            except Exception as inner_error:
                session.rollback()
                log.error(f"Veritabanı silme hatası: {inner_error}")
            finally:
                db.Session.remove()
                
            return jsonify({"status": "deleted", "id": item_id})
        except Exception as error:
            log.error("Tekli rapor silinirken hata oluştu: %s", str(error))
            return jsonify({"error": "Silme başarısız"}), 500

    @app.route("/api/results/delete-selected", methods=["POST"])
    def delete_selected_results() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kullanıcının işaretlediği kayıtları sadece arayüz listesinden kaldırır (Veritabanında korur, arşive atar)."""
        try:
            req_data: Any = request.get_json()
            if not isinstance(req_data, dict):
                return jsonify({"error": "Geçersiz istek formatı"}), 400
            
            req_map: Dict[str, Any] = cast(Dict[str, Any], req_data)
            ids_raw: Any = req_map.get("ids", [])
            
            if not isinstance(ids_raw, list):
                return jsonify({"error": "ID listesi bulunamadı"}), 400
                
            raw_ids_list: List[Any] = cast(List[Any], ids_raw)
            ids_to_delete: List[str] = [str(i) for i in raw_ids_list]
            
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            all_results_raw: Any = stored_data_safe.get("data", [])
            all_results: List[Dict[str, Any]] = []
            
            if isinstance(all_results_raw, list):
                raw_list: List[Any] = cast(List[Any], all_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        all_results.append(item_map)
            
            if all_results:
                valid_results: List[Dict[str, Any]] = []
                archived_results: List[Dict[str, Any]] = []
                
                for r in all_results:
                    if _get_unique_key(r) not in ids_to_delete:
                        valid_results.append(r)
                    else:
                        archived_results.append(r)
                        
                _backup_to_archive(archived_results)
                set_task_result("web_last_results", {"data": valid_results})
                
            log.info(f"➖ {len(ids_to_delete)} adet sonuç sadece ekran listesinden kaldırıldı ve arşive taşındı.")
            return jsonify({"status": "deleted"})
        except Exception as error:
            log.error("Seçili sonuçlar temizlenirken hata: %s", str(error))
            return jsonify({"error": "Temizleme başarısız"}), 500

    @app.route("/api/database/delete-selected", methods=["POST"])
    def delete_selected_database() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kullanıcının işaretlediği kayıtları arayüzden, arşivden ve VERİTABANINDAN KALICI olarak siler."""
        try:
            req_data: Any = request.get_json()
            if not isinstance(req_data, dict):
                return jsonify({"error": "Geçersiz istek formatı"}), 400
                
            req_map: Dict[str, Any] = cast(Dict[str, Any], req_data)
            ids_raw: Any = req_map.get("ids", [])
            
            if not isinstance(ids_raw, list):
                return jsonify({"error": "ID listesi bulunamadı"}), 400
                
            raw_ids_list: List[Any] = cast(List[Any], ids_raw)
            ids_to_delete: List[str] = [str(i) for i in raw_ids_list]
            
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            all_results_raw: Any = stored_data_safe.get("data", [])
            all_results: List[Dict[str, Any]] = []
            
            if isinstance(all_results_raw, list):
                raw_list: List[Any] = cast(List[Any], all_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        all_results.append(item_map)
                        
            if all_results:
                valid_results: List[Dict[str, Any]] = [r for r in all_results if _get_unique_key(r) not in ids_to_delete]
                set_task_result("web_last_results", {"data": valid_results})
            
            _remove_from_archive(ids_to_delete)
                
            session: Session = db.Session()
            deleted_count: int = 0
            try:
                from app.core.models import PdfFile, ProcessedReport
                for item_id in ids_to_delete:
                    if item_id:
                        session.query(PdfFile).filter_by(report_id=item_id).delete()
                        session.query(ProcessedReport).filter_by(report_id=item_id).delete()
                        deleted_count += 1
                        
                session.commit()
                log.info(f"🗑️ {deleted_count} adet rapor sistemden tamamen silindi.")
            except Exception as inner_error:
                session.rollback()
                log.error(f"Toplu veritabanı silme hatası: {inner_error}")
            finally:
                db.Session.remove()
                
            return jsonify({"status": "deleted", "deleted_count": deleted_count})
        except Exception as error:
            log.error("Seçili sonuçlar DB'den silinirken hata: %s", str(error))
            return jsonify({"error": "DB Silme başarısız"}), 500

    @app.route("/api/results/fetch-db", methods=["POST"])
    def fetch_results_from_db() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Veritabanında saklanan ancak listeden silinmiş olan PDF'leri ve arşivdeki Randevuları geri getirir."""
        try:
            pdfs: List[Dict[str, Any]] = db.list_pdfs(limit=2500)
            
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            existing_results_raw: Any = stored_data_safe.get("data", [])
            existing_results: List[Dict[str, Any]] = []
            
            if isinstance(existing_results_raw, list):
                raw_list: List[Any] = cast(List[Any], existing_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        existing_results.append(item_map)
                        
            existing_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in existing_results}
            
            added_count: int = 0
            
            arch_data: Optional[Dict[str, Any]] = get_task_result("web_archived_results")
            arch_safe: Dict[str, Any] = arch_data if arch_data else {}
            arch_raw: Any = arch_safe.get("data", [])
            
            if isinstance(arch_raw, list):
                raw_arch: List[Any] = cast(List[Any], arch_raw)
                for item in raw_arch:
                    if isinstance(item, dict):
                        arch_item: Dict[str, Any] = cast(Dict[str, Any], item)
                        uid: str = _get_unique_key(arch_item)
                        if uid and uid not in existing_map:
                            existing_map[uid] = arch_item
                            added_count += 1
            
            for p in pdfs:
                rid_raw: Any = p.get("report_id")
                rid: str = str(rid_raw) if rid_raw else ""
                if not rid:
                    continue
                    
                if rid not in existing_map:
                    new_rep: Dict[str, Any] = {
                        "uuid": rid,
                        "file_name": str(p.get("file_name", "")),
                        "building_name": str(p.get("building", "")),
                        "provider": str(p.get("provider", "")),
                        "label_color": str(p.get("label_color", "")),
                        "inspection_date": "Arşivden Yüklendi",
                        "next_inspection": "-",
                        "elevator_number": "-",
                    }
                    existing_map[rid] = new_rep
                    added_count += 1
                    
            merged_results: List[Dict[str, Any]] = list(existing_map.values())
            set_task_result("web_last_results", {"data": merged_results})
            
            log.info(f"📥 Veritabanından ve arşivden {added_count} adet kayıt başarıyla listeye okundu.")
            return jsonify({"status": "fetched", "count": added_count})
        except Exception as error:
            log.error("DB verileri listeye aktarılırken hata: %s", str(error))
            return jsonify({"error": "Aktarım başarısız"}), 500

    @app.route("/api/results/clear-all", methods=["POST", "DELETE"])
    def clear_all_results() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Ekranda listelenen tüm sonuçları sadece arayüzden (bellekten) siler ve arşive taşır, veritabanına dokunmaz."""
        try:
            stored_data: Optional[Dict[str, Any]] = get_task_result("web_last_results")
            stored_data_safe: Dict[str, Any] = stored_data if stored_data else {}
            
            all_results_raw: Any = stored_data_safe.get("data", [])
            all_results: List[Dict[str, Any]] = []
            
            if isinstance(all_results_raw, list):
                raw_list: List[Any] = cast(List[Any], all_results_raw)
                for item in raw_list:
                    if isinstance(item, dict):
                        item_map: Dict[str, Any] = cast(Dict[str, Any], item)
                        all_results.append(item_map)
                        
            _backup_to_archive(all_results)
            set_task_result("web_last_results", {"data": []})
            
            log.info("🗑️ Tüm sonuçlar ekran listesinden temizlendi (Veritabanı korundu).")
            return jsonify({"status": "cleared"})
        except Exception as error:
            log.error("Tüm sonuçlar temizlenirken hata: %s", str(error))
            return jsonify({"error": "Temizleme başarısız"}), 500

    @app.route("/api/database/clear", methods=["POST", "DELETE"])
    def clear_database() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Veritabanındaki tüm işlenmiş verileri (E-posta, Rapor, PDF) tamamen siler ve arayüzü sıfırlar."""
        try:
            deleted_count: int = db.clear_all_data()
            set_task_result("web_last_results", {"data": []})
            set_task_result("web_archived_results", {"data": []})
            return jsonify({"status": "cleared", "deleted_count": deleted_count})
        except Exception as error:
            log.error("Veritabanı sıfırlanırken hata: %s", str(error))
            return jsonify({"error": "Sıfırlama başarısız"}), 500

    @app.route("/api/config", methods=["GET"])
    def get_api_config() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Sistem yapılandırmasını döndürür."""
        return jsonify(load_config())

    @app.route("/api/config", methods=["POST"])
    def update_config() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Sistem yapılandırmasını günceller."""
        try:
            new_config_raw: Any = request.get_json()
            new_config: Dict[str, Any] = {}
            
            if isinstance(new_config_raw, dict):
                new_config = cast(Dict[str, Any], new_config_raw)
                
            save_config(new_config)
            return jsonify({"status": "saved"})
        except Exception as e:
            log.error(f"Ayarlar kaydedilirken sunucu hatası oluştu: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/scraping-profiles", methods=["GET"])
    def get_profiles() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kazıma profillerini okur ve döndürür."""
        profile_path: Path = paths.SCRAPING_PROFILES
        try:
            if not profile_path.exists():
                log.warning(f"Profil dosyası mevcut dizinde bulunamadı: {profile_path}")
                return jsonify({"error": "Scraping profili bulunamadı."}), 404

            with open(profile_path, "r", encoding="utf-8") as f:
                json_data: Any = json.load(f)
                return jsonify(json_data)
        except Exception as e:
            log.error(f"Profil okuma hatası: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/scraping-profiles", methods=["POST"])
    def save_profiles() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kazıma profillerini günceller."""
        profile_path: Path = paths.SCRAPING_PROFILES
        try:
            profile_path.parent.mkdir(parents=True, exist_ok=True)
            new_profiles_raw: Any = request.get_json()
            
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(new_profiles_raw, f, ensure_ascii=False, indent=2)
            
            reload_profiles()
            return jsonify({"status": "saved"})
        except Exception as e:
            log.error(f"Profil kaydetme hatası: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pdfs", methods=["GET"])
    def get_pdfs_list() -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kayıtlı PDF'lerin meta veri listesini döndürür."""
        try:
            pdfs: List[Dict[str, Any]] = db.list_pdfs()
            return jsonify(pdfs)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pdfs/<int:pdf_id>/download", methods=["GET"])
    def download_pdf(pdf_id: int) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Belirtilen PDF dosyasını veritabanından çekerek indirir."""
        try:
            pdf_data: Optional[Dict[str, Any]] = db.get_pdf(pdf_id)
            if not pdf_data:
                return jsonify({"error": "PDF veritabanında bulunamadı"}), 404
            
            file_name_raw: Any = pdf_data.get("file_name", f"rapor_{pdf_id}.pdf")
            file_name: str = str(file_name_raw)
            file_bytes_raw: Any = pdf_data.get("file_data", b"")
            file_bytes: bytes = file_bytes_raw if isinstance(file_bytes_raw, bytes) else b""
            
            return send_file(
                BytesIO(file_bytes), 
                download_name=file_name, 
                as_attachment=True,
                mimetype="application/pdf"
            )
        except Exception as e:
            log.error("PDF indirme hatası: %s", str(e))
            return jsonify({"error": "İndirme başarısız"}), 500

    @app.route("/api/pdf/by-report/<report_id>", methods=["GET"])
    def download_pdf_by_report(report_id: str) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Spesifik rapora ait PDF dosyasını döndürür."""
        try:
            pdf_data: Optional[Dict[str, Any]] = db.get_pdf_by_report(report_id)
            if not pdf_data:
                return jsonify({"error": "PDF veritabanında bulunamadı"}), 404
            
            file_name_raw: Any = pdf_data.get("file_name", f"rapor_{report_id}.pdf")
            file_name: str = str(file_name_raw)
            file_bytes_raw: Any = pdf_data.get("file_data", b"")
            file_bytes: bytes = file_bytes_raw if isinstance(file_bytes_raw, bytes) else b""
            
            return send_file(
                BytesIO(file_bytes), 
                download_name=file_name, 
                as_attachment=False,
                mimetype="application/pdf"
            )
        except Exception as e:
            log.error("PDF rapor ID ile indirme hatası: %s", str(e))
            return jsonify({"error": "İndirme başarısız"}), 500

    @app.route("/api/maintenance/cleanup", methods=["POST"])
    def run_cleanup() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Gelen kutusundaki işlenmiş e-postaların etiketlerini temizler."""
        def _bg_cleanup() -> None:
            try:
                from app.gmail.maintenance import run_cleanup_task
                run_cleanup_task(load_config())
            except Exception as e:
                log.error(f"Temizlik hatası: {e}")
                
        threading.Thread(target=_bg_cleanup, daemon=True).start()
        
        return jsonify({"status": "started", "action": "cleanup"})

    @app.route("/api/maintenance/trash", methods=["POST"])
    def run_trash() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Yapılandırılmış kurallara uyan e-postaları çöpe atar."""
        def _bg_trash() -> None:
            try:
                from app.gmail.maintenance import run_trash_task
                run_trash_task(load_config())
            except Exception as e:
                log.error(f"Çöp kutusuna taşıma hatası: {e}")
                
        threading.Thread(target=_bg_trash, daemon=True).start()
        
        return jsonify({"status": "started", "action": "trash"})

    @app.route("/api/maintenance/delete-labels", methods=["POST"])
    def run_delete_labels() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Kullanılmayan veya silinmesi gereken Gmail etiketlerini kalıcı olarak siler."""
        def _bg_label_del() -> None:
            try:
                from app.gmail.maintenance import run_delete_label_task
                run_delete_label_task(load_config())
            except Exception as e:
                log.error(f"Etiket silme hatası: {e}")
                
        threading.Thread(target=_bg_label_del, daemon=True).start()
        
        return jsonify({"status": "started", "action": "delete_labels"})

    @app.route("/api/logs", methods=["GET"])
    def logs() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Son log kayıtlarını döndürür."""
        return jsonify(get_recent_logs(500))

    @app.route("/api/auth/status")
    def auth_status() -> Response:  # pyright: ignore[reportUnusedFunction]
        """Gmail yetkilendirme durumunu döndürür."""
        from app.gmail.auth import get_pending_auth_url, needs_auth
        
        is_auth_needed: bool = needs_auth()
        url: Optional[str] = get_pending_auth_url()
        
        cred_exists: bool = get_secure_config("auth_credentials") is not None
        token_exists: bool = get_secure_config("auth_token") is not None

        return jsonify({
            "needs_auth": is_auth_needed if not url else True,
            "auth_url": url,
            "credentials_exists": cred_exists,
            "token_exists": token_exists,
        })

    @app.route("/api/auth/upload/<filetype>", methods=["POST"])
    def upload_auth_file(filetype: str) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Kullanıcının yüklediği yapılandırma dosyalarını şifreleyip veritabanına kaydeder."""
        if filetype not in ("credentials", "token"):
            return jsonify({"error": "Geçersiz dosya tipi"}), 400
            
        auth_file: Optional[FileStorage] = request.files.get("file")
        if not auth_file:
            return jsonify({"error": "Dosya bulunamadı"}), 400
            
        try:
            file_content_raw: bytes = auth_file.read()
            file_content: str = file_content_raw.decode('utf-8')
            json_data_raw: Any = json.loads(file_content)
            
            if isinstance(json_data_raw, dict):
                json_data: Dict[str, Any] = cast(Dict[str, Any], json_data_raw)
                set_secure_config(f"auth_{filetype}", json_data)
            else:
                return jsonify({"error": "JSON içeriği geçerli bir sözlük değil"}), 400
                
            fname: str = f"{filetype}.json"
            if os.path.exists(fname):
                try:
                    os.remove(fname)
                    log.info(f"🧹 Güvenlik: Diskte bulunan eski {fname} dosyası silindi.")
                except Exception:
                    pass
                
            log.info(f"🔑 Kimlik verisi başarıyla veritabanına eklendi.")
            
            return jsonify({"status": "uploaded", "file": f"auth_{filetype}"})
            
        except json.JSONDecodeError:
            return jsonify({"error": "Geçersiz JSON formatı"}), 400
        except Exception as e:
            log.error(f"Kayıt hatası: {e}")
            return jsonify({"error": "Yükleme başarısız"}), 500

    @app.route("/api/auth/download/<filetype>")
    def download_auth_file(filetype: str) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Yetkilendirme dosyalarını veritabanından çözüp JSON olarak indirir."""
        if filetype not in ("credentials", "token"):
            return jsonify({"error": "Geçersiz dosya tipi"}), 400
        
        try:
            db_data: Optional[Dict[str, Any]] = get_secure_config(f"auth_{filetype}")
            if not db_data:
                return jsonify({"error": f"{filetype} veritabanında bulunamadı"}), 404
                
            json_bytes: bytes = json.dumps(db_data, ensure_ascii=False, indent=2).encode('utf-8')
            
            return send_file(
                BytesIO(json_bytes), 
                as_attachment=True, 
                download_name=f"{filetype}.json",
                mimetype="application/json"
            )
        except Exception as e:
            log.error(f"İndirme hatası: {e}")
            return jsonify({"error": "İndirme başarısız"}), 500

    @app.route("/api/auth/delete/<filetype>", methods=["DELETE"])
    def delete_auth_file(filetype: str) -> Union[Response, Tuple[Response, int]]:  # pyright: ignore[reportUnusedFunction]
        """Belirtilen yetkilendirme dosyasını veritabanından tamamen siler."""
        if filetype not in ("credentials", "token"):
            return jsonify({"error": "Geçersiz dosya tipi"}), 400
            
        try:
            deleted: bool = delete_secure_config(f"auth_{filetype}")
            
            fname: str = f"{filetype}.json"
            if os.path.exists(fname):
                try:
                    os.remove(fname)
                except Exception:
                    pass
            
            if deleted:
                log.info(f"🗑️ Kimlik verisi veritabanından kalıcı olarak silindi: auth_{filetype}")
                return jsonify({"status": "deleted", "file": f"auth_{filetype}"})
            else:
                return jsonify({"error": "Kayıt veritabanında bulunamadı"}), 404
                
        except Exception as e:
            log.error(f"Veritabanı silme hatası ({filetype}): {e}")
            return jsonify({"error": "Silme başarısız"}), 500

    @socketio.on("connect", namespace="/logs")
    def on_connect() -> None:  # pyright: ignore[reportUnusedFunction]
        """Yeni bir istemci bağlantısı sağlandığında çalışır."""
        pass

    return app, socketio


def start_server(host: str = "127.0.0.1", port: int = 5001) -> None:
    """Flask web sunucusunu belirlenen adres ve port üzerinden başlatır.

    Args:
        host (str): Dinlenecek IP adresi.
        port (int): Dinlenecek TCP portu.
    """
    app: Flask
    socketio: SocketIO
    app, socketio = create_app()
    
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"), log_file=str(paths.DEFAULT_LOG_PATH))
    log.info("🌐 Web arayüzü başlatılıyor: http://%s:%s", host, port)

    wz_logger: logging.Logger = logging.getLogger('werkzeug')
    wz_logger.setLevel(logging.ERROR)

    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)  # pyright: ignore[reportUnknownMemberType]