"""Web sunucusu modülü: Uygulamanın arayüzünü ve API uç noktalarını yönetir."""

import json
import logging
import os
import threading
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Tuple, Dict, List, Set, Optional

from flask import Flask, render_template, request, jsonify, send_file, Response
from flask_socketio import SocketIO

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
    uid: str = str(r.get("uuid", ""))
    
    if uid and uid != "N/A" and uid != "None":
        return uid
        
    return str(r.get("file_name", ""))


def create_app() -> Tuple[Flask, SocketIO]:
    """Flask web uygulamasını ve SocketIO eklentisini oluşturur ve yapılandırır.
    
    Returns:
        Tuple[Flask, SocketIO]: Başlatılmış Flask uygulaması ve SocketIO sunucusu.
    """
    template_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
    static_dir: str = os.path.abspath(os.path.join(os.path.dirname(__file__), 'static'))
    
    app: Flask = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET", os.urandom(24))
    
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
    def index() -> str:
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
    def status() -> Response:
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
    def start_run() -> Response:
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
                        stored_data: Dict[str, Any] = get_task_result("web_last_results") or {}
                        existing_results: List[Dict[str, Any]] = stored_data.get("data", [])
                        
                        existing_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in existing_results}
                        res: Dict[str, Any]
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
    def watch_start() -> Response:
        """Periyodik kontrol modunu başlatır."""
        global _watch_running
        
        try:
            config: Dict[str, Any] = load_config()
            is_search_by_label: bool = config.get("search_settings", {}).get("search_by_label", False)
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
            global _watch_running
            try:
                from app.core.engine import run, _watch_stop
                _watch_stop.clear()
                
                config: Dict[str, Any] = load_config()
                ws: Dict[str, Any] = config.get("watch_settings", {})
                interval: int = max(1, ws.get("interval_minutes", 30))
                
                log.info("=" * 50)
                log.info(f"👁️  DİNLEME MODU — Her {interval} dakikada bir kontrol yapılacak")
                log.info("=" * 50)
                
                cycle: int = 0
                
                while not _watch_stop.is_set():
                    cycle += 1
                    log.info(f"🔄 Döngü #{cycle} başlıyor...")
                    try:
                        results: List[Dict[str, Any]] = run()
                        
                        if results:
                            with _lock:
                                stored_data: Dict[str, Any] = get_task_result("web_last_results") or {}
                                existing_results: List[Dict[str, Any]] = stored_data.get("data", [])
                                
                                existing_map: Dict[str, Dict[str, Any]] = {_get_unique_key(r): r for r in existing_results}
                                r: Dict[str, Any]
                                for r in results:
                                    existing_map[_get_unique_key(r)] = r
                                
                                updated_list: List[Dict[str, Any]] = list(existing_map.values())
                                set_task_result("web_last_results", {"data": updated_list})
                            
                            socketio.emit("results_updated", namespace="/logs")
                            log.info(f"🔄 Döngü #{cycle} tamamlandı: {len(results)} yeni rapor eklendi.")
                        else:
                            log.info(f"🔄 Döngü #{cycle} tamamlandı: Yeni rapor bulunamadı.")
                            
                    except Exception as e:
                        log.error(f"🔄 Döngü #{cycle} hatası: {e}", exc_info=True)

                    log.info(f"⏳ {interval} dakika bekleniyor...")
                    if _watch_stop.wait(timeout=interval * 60):
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
    def watch_stop() -> Response:
        """Periyodik kontrol modunu durdurur."""
        global _watch_running
        from app.core.engine import stop_watch
        
        with _lock:
            stop_watch()
            _watch_running = False
            
        return jsonify({"status": "stopped"})

    @app.route("/api/results", methods=["GET"])
    def get_results() -> Response:
        """İşlenmiş rapor sonuçlarını döndürür."""
        try:
            stored_data: Dict[str, Any] = get_task_result("web_last_results") or {}
            all_results: List[Dict[str, Any]] = stored_data.get("data", [])
            return jsonify(all_results)
        except Exception as error:
            log.error("Sonuçlar getirilirken hata: %s", str(error))
            return jsonify({"error": "Veritabanı hatası"}), 500

    @app.route("/api/report/delete/<item_id>", methods=["DELETE"])
    def delete_report_single(item_id: str) -> Response:
        """Tekli bir raporu ID'sine göre veritabanından tamamen siler."""
        try:
            stored_data: Dict[str, Any] = get_task_result("web_last_results") or {}
            all_results: List[Dict[str, Any]] = stored_data.get("data", [])
            
            if all_results:
                valid_results: List[Dict[str, Any]] = [r for r in all_results if _get_unique_key(r) != item_id]
                set_task_result("web_last_results", {"data": valid_results})
                
            session: Any = db.Session()
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
                # Güvenli havuz boşaltımı (session.close yerine db.Session.remove kullanıldı)
                db.Session.remove()
                
            return jsonify({"status": "deleted", "id": item_id})
        except Exception as error:
            log.error("Tekli rapor silinirken hata oluştu: %s", str(error))
            return jsonify({"error": "Silme başarısız"}), 500

    @app.route("/api/results/clear-all", methods=["POST", "DELETE"])
    def clear_all_results() -> Response:
        """Ekranda listelenen tüm sonuçları veritabanından tamamen siler."""
        try:
            stored_data: Dict[str, Any] = get_task_result("web_last_results") or {}
            all_results: List[Dict[str, Any]] = stored_data.get("data", [])
            
            session: Any = db.Session()
            try:
                from app.core.models import PdfFile, ProcessedReport
                r: Dict[str, Any]
                for r in all_results:
                    item_id: str = _get_unique_key(r)
                    if item_id:
                        session.query(PdfFile).filter_by(report_id=item_id).delete()
                        session.query(ProcessedReport).filter_by(report_id=item_id).delete()
                        
                session.commit()
                log.info("🗑️ Tüm sonuçlar sistemden tamamen silindi.")
            except Exception as inner_error:
                session.rollback()
                log.error(f"Toplu veritabanı silme hatası: {inner_error}")
            finally:
                db.Session.remove()
                
            set_task_result("web_last_results", {"data": []})
            
            return jsonify({"status": "cleared"})
        except Exception as error:
            log.error("Tüm sonuçlar temizlenirken hata: %s", str(error))
            return jsonify({"error": "Temizleme başarısız"}), 500

    @app.route("/api/config", methods=["GET"])
    def get_api_config() -> Response:
        """Sistem yapılandırmasını döndürür."""
        return jsonify(load_config())

    @app.route("/api/config", methods=["POST"])
    def update_config() -> Response:
        """Sistem yapılandırmasını günceller."""
        try:
            new_config: Dict[str, Any] = request.get_json()
            save_config(new_config)
            return jsonify({"status": "saved"})
        except Exception as e:
            log.error(f"Ayarlar kaydedilirken sunucu hatası oluştu: {e}")
            return jsonify({"error": str(e)}), 500

    @app.route("/api/scraping-profiles", methods=["GET"])
    def get_profiles() -> Response:
        """Kazıma profillerini okur ve döndürür."""
        profile_path: str = os.path.join("app", "downloaders", "scraping_profiles.json")
        try:
            with open(profile_path, "r", encoding="utf-8") as f:
                return jsonify(json.load(f))
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/scraping-profiles", methods=["POST"])
    def save_profiles() -> Response:
        """Kazıma profillerini günceller."""
        profile_path: str = os.path.join("app", "downloaders", "scraping_profiles.json")
        try:
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(request.get_json(), f, ensure_ascii=False, indent=2)
            
            reload_profiles()
            return jsonify({"status": "saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pdfs", methods=["GET"])
    def get_pdfs_list() -> Response:
        """Kayıtlı PDF'lerin meta veri listesini döndürür."""
        try:
            return jsonify(db.list_pdfs())
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.route("/api/pdfs/<int:pdf_id>/download", methods=["GET"])
    def download_pdf(pdf_id: int) -> Response:
        """Belirtilen PDF dosyasını veritabanından çekerek indirir."""
        try:
            pdf_data: Optional[Dict[str, Any]] = db.get_pdf(pdf_id)
            if not pdf_data:
                return jsonify({"error": "PDF veritabanında bulunamadı"}), 404
            
            file_name: str = pdf_data.get("file_name", f"rapor_{pdf_id}.pdf")
            file_bytes: bytes = pdf_data.get("file_data", b"")
            
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
    def download_pdf_by_report(report_id: str) -> Response:
        """Spesifik rapora ait PDF dosyasını döndürür."""
        try:
            pdf_data: Optional[Dict[str, Any]] = db.get_pdf_by_report(report_id)
            if not pdf_data:
                return jsonify({"error": "PDF veritabanında bulunamadı"}), 404
            
            file_name: str = pdf_data.get("file_name", f"rapor_{report_id}.pdf")
            file_bytes: bytes = pdf_data.get("file_data", b"")
            
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
    def run_cleanup() -> Response:
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
    def run_trash() -> Response:
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
    def run_delete_labels() -> Response:
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
    def logs() -> Response:
        """Son log kayıtlarını döndürür."""
        return jsonify(get_recent_logs(500))

    @app.route("/api/auth/status")
    def auth_status() -> Response:
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
    def upload_auth_file(filetype: str) -> Response:
        """Kullanıcının yüklediği yapılandırma dosyalarını şifreleyip veritabanına kaydeder."""
        if filetype not in ("credentials", "token"):
            return jsonify({"error": "Geçersiz dosya tipi"}), 400
            
        auth_file: Any = request.files.get("file")
        if not auth_file:
            return jsonify({"error": "Dosya bulunamadı"}), 400
            
        try:
            file_content: str = auth_file.read().decode('utf-8')
            json_data: Dict[str, Any] = json.loads(file_content)
            
            set_secure_config(f"auth_{filetype}", json_data)
                
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
    def download_auth_file(filetype: str) -> Response:
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
    def delete_auth_file(filetype: str) -> Response:
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
    def on_connect() -> None:
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
    
    setup_logging(level=os.environ.get("LOG_LEVEL", "INFO"), log_file=paths.DEFAULT_LOG_PATH)
    log.info("🌐 Web arayüzü başlatılıyor: http://%s:%s", host, port)

    wz_logger: logging.Logger = logging.getLogger('werkzeug')
    wz_logger.setLevel(logging.ERROR)

    socketio.run(app, host=host, port=port, allow_unsafe_werkzeug=True)