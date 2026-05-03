# -*- coding: utf-8 -*-
"""
Yapılandırma yükleme, birleştirme ve doğrulama modülü.
"""

import json
import logging
import os
import ast
from copy import deepcopy
from pathlib import Path
from typing import Dict, Any, Optional, Set

from app.core.database import _get_default_session, SessionScoped
from app.core.models import AppConfig
from app.paths import paths


def _get_secure_home_dir() -> str:
    """Tüm işletim sistemlerinde güvenli kullanıcı ev dizini yolunu döndürür.
    
    Returns:
        str: Güvenli ev dizininin mutlak yolu.
    """
    return str(paths.SECURE_PATH)


def _get_public_download_dir() -> str:
    """Tüm işletim sistemleri için ortak genel indirme dizinini tespit eder.
    
    Returns:
        str: Evrensel indirme dizininin mutlak yolu.
    """
    termux_downloads: str = os.path.expanduser("~/storage/downloads")
    if os.path.exists(termux_downloads):
        return os.path.join(termux_downloads, "AsansorRaporlari")

    android_path: str
    for android_path in ["/storage/emulated/0/Download", "/storage/shared/Download"]:
        if os.path.exists(android_path):
            return os.path.join(android_path, "AsansorRaporlari")

    home: Path = Path.home()
    d_name: str
    for d_name in ["Downloads", "Download", "İndirilenler"]:
        d_path: Path = home / d_name
        if d_path.exists():
            return str(d_path / "AsansorRaporlari")

    return str(home / "AsansorRaporlari" / "Genel")


_SECURE_BASE: str = _get_secure_home_dir()
_PUBLIC_BASE: str = _get_public_download_dir()

DEFAULTS: Dict[str, Any] = {
    "mode": "gmail",
    "web_settings": {
        "host": "127.0.0.1",
        "port": 5001,
    },
    "watch_settings": {
        "enabled": False,
        "interval_minutes": 30,
    },
    "label_settings": {
        "use_tree": True,
        "tree_parent": "Asansör Raporları",
        "colors": {
            "Kırmızı": "Kırmızı Etiketli",
            "Sarı": "Sarı Etiketli",
            "Mavi": "Mavi Etiketli",
            "Yeşil": "Yeşil Etiketli",
        },
        "appointment_label": "Randevu",
    },
    "search_settings": {
        "search_by_label": False,
        "target_labels": [],
        "search_only_unread": True,
        "mark_as_read_after_processing": True,
        "archive_after_processing": False,
        "search_days_before_today": 0,
        "label_specific_days_before": {},
        "exceptional_keywords": [],
        "exceptional_senders": [],
        "num_workers": 10,
    },
    "manual_source_settings": {
        "enabled": False,
        "folder_path": os.path.join(_PUBLIC_BASE, "manuel"),
        "move_processed_files": True,
        "processed_folder_path": os.path.join(_PUBLIC_BASE, "manuel", "islenenler"),
    },
    "paths": {
        "download_folder": os.path.join(_PUBLIC_BASE, "raporlar"),
        "output_folder": os.path.join(_PUBLIC_BASE, "ciktilar"),
        "database": paths.DEFAULT_DB_PATH,
        "log_file": paths.DEFAULT_LOG_PATH,
    },
    "output_formats": ["txt", "csv"],
    "database_settings": {"force_reprocess_all": False, "skip_duplicate_downloads": True},
    "quarantine_settings": {
        "enabled": False,
        "quarantine_label_name": "İşlem Başarısız",
        "max_fail_count": 5,
        "quarantine_days": 1,
    },
    "sources": [
        {
            "label_name": "Kent Belgelendirme",
            "query": "kentbelgelendirme@adetsis.net",
            "processor": "adetsis"
        },
        {
            "label_name": "Kent Belgelendirme",
            "query": "kentbelgelendirme@raporkentbelgelendirme.com",
            "processor": "adetsis"
        },
        {
            "label_name": "Asansör Kontrol",
            "query": "asansorkontrol@adetsis.net",
            "processor": "adetsis"
        },
        {
            "label_name": "Asansör Kontrol",
            "query": "rapor@asansorkontrol.net",
            "processor": "adetsis"
        },
        {
            "label_name": "MMO",
            "query": "mmo.org.tr",
            "processor": "mmo"
        },
        {
            "label_name": "Artıbel",
            "query": "artibel.com.tr",
            "processor": "artibel"
        },
        {
            "label_name": "Asansör Kontrol",
            "query": "asansorkontrol@gmail.com",
            "processor": "appointment"
        },
        {
            "label_name": "Optimal Denge",
            "query": "info@optimaldenge.app",
            "processor": "optimaldenge"
        },
        {
            "label_name": "Optimal Denge",
            "query": "optimal.arsiv@gmail.com",
            "processor": "optimaldenge"
        },
        {
            "label_name": "Optimal Denge",
            "query": "optimaldenge.kecioren@milenyum.pro",
            "processor": "optimaldenge"
        }
    ],
    "color_labels": [
        "Kırmızı Etiketli",
        "Sarı Etiketli",
        "Mavi Etiketli",
        "Yeşil Etiketli",
        "Randevu",
    ],
    "appointment_email_settings": {
        "enabled": True,
        "randevu_label_name": "Randevu",
        "filter_past_dates": True,
        "filter_if_resolved": True,
        "randevu_search_days": 60,
        "search_only_unread": True,
    },
    "cleanup_mode_settings": {
        "enabled": False,
        "run_in_test_mode": True,
        "cleanup_rules": [],
    },
    "label_delete_settings": {
        "enabled": False,
        "run_in_test_mode": True,
        "labels_to_delete_permanently": [],
    },
    "trash_mode_settings": {
        "enabled": False,
        "run_in_test_mode": True,
        "trash_rules": [],
    },
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """İki sözlüğü derinlemesine birleştirir ve yorum satırı işlevli anahtarları yoksayar.
    
    Args:
        base (Dict[str, Any]): Temel alınacak varsayılan sözlük.
        override (Dict[str, Any]): Üzerine yazılacak yeni değerleri içeren sözlük.
        
    Returns:
        Dict[str, Any]: Birleştirilmiş yeni sözlük nesnesi.
    """
    result: Dict[str, Any] = deepcopy(base)
    
    key: str
    value: Any
    for key, value in override.items():
        if isinstance(key, str) and (key.startswith("//") or key.startswith("#")):
            continue
            
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
            
    return result


def load_config(configuration_key: Optional[str] = "app_manifest") -> Dict[str, Any]:
    """Yapılandırma dosyasını veritabanı üzerinden yükler, varsayılanlarla birleştirir ve doğrular.
    
    Args:
        configuration_key (Optional[str]): Yapılandırmanın veritabanındaki benzersiz anahtarı. 
        
    Returns:
        Dict[str, Any]: İşlenmiş ve kullanıma hazır yapılandırma sözlüğü.
    """
    logger: logging.Logger = logging.getLogger(__name__)
    
    if configuration_key is None or str(configuration_key).strip() == "" or str(configuration_key) == "None":
        configuration_key = "app_manifest"
        
    user_config: Dict[str, Any] = {}
    record_exists: bool = False
    
    session: Any = _get_default_session()
    try:
        record: Any = session.query(AppConfig).filter_by(config_key=configuration_key).first()
        
        if record is not None:
            record_exists = True
            val = record.config_value
            if val:
                if isinstance(val, dict):
                    user_config = deepcopy(val)
                elif isinstance(val, str):
                    try:
                        parsed_val = json.loads(val)
                        if isinstance(parsed_val, str):
                            parsed_val = json.loads(parsed_val)
                            
                        if isinstance(parsed_val, dict):
                            user_config = parsed_val
                    except json.JSONDecodeError:
                        try:
                            eval_val = ast.literal_eval(val)
                            if isinstance(eval_val, dict):
                                user_config = eval_val
                        except Exception as inner_e:
                            logger.error(f"Veritabanındaki yapılandırma metni okunamadı: {inner_e}")
                                
    except Exception as e:
        logger.error(f"Veritabanı üzerinden yapılandırma okunurken hata: {e}")
    finally:
        SessionScoped.remove()

    if not isinstance(user_config, dict):
        user_config = {}
        
    config: Dict[str, Any] = _deep_merge(DEFAULTS, user_config)
    
    _fill_empty_paths(config)
    _validate(config)
    _ensure_dirs(config)
    
    if not record_exists:
        try:
            save_config(config, configuration_key)
        except Exception as e:
            logger.warning(f"Varsayılan yapılandırma veritabanına yazılamadı: {e}")
            
    return config


def _fill_empty_paths(config: Dict[str, Any]) -> None:
    """Tanımlanmamış veya boş bırakılmış yol anahtarlarını varsayılanlarla doldurur.

    Args:
        config (Dict[str, Any]): Doldurulacak yapılandırma sözlüğü.
    """
    defaults_paths: Dict[str, Any] = DEFAULTS["paths"]
    if "paths" not in config:
        config["paths"] = {}
        
    paths_dict: Dict[str, Any] = config["paths"]
    
    key: str
    default_val: Any
    for key, default_val in defaults_paths.items():
        if not paths_dict.get(key):
            paths_dict[key] = default_val

    defaults_manual: Dict[str, Any] = DEFAULTS["manual_source_settings"]
    manual: Dict[str, Any] = config.get("manual_source_settings", {})
    
    for key in ("folder_path", "processed_folder_path"):
        if not manual.get(key):
            manual[key] = defaults_manual[key]
            
    config["manual_source_settings"] = manual


def save_config(config: Dict[str, Any], path: Optional[str] = "app_manifest") -> None:
    """Yapılandırma sözlüğünü veritabanına yazar.
    
    Args:
        config (Dict[str, Any]): Kaydedilecek yapılandırma verisi.
        path (Optional[str]): Hedef kayıt anahtarı (Veritabanı için).
    """
    if path is None or str(path).strip() == "" or str(path) == "None":
        path = "app_manifest"
        
    config.pop("error", None)
    clean: Dict[str, Any] = deepcopy({k: v for k, v in config.items() if not k.startswith("_")})
    logger: logging.Logger = logging.getLogger(__name__)
    
    session: Any = _get_default_session()
    try:
        payload_str: str = json.dumps(clean, ensure_ascii=False)
        
        session.query(AppConfig).filter_by(config_key=path).delete()
        
        record = AppConfig(config_key=path, config_value=payload_str)
        session.add(record)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Yapılandırma veritabanına kaydedilirken hata oluştu: {e}")
        raise
    finally:
        SessionScoped.remove()


def _validate(config: Dict[str, Any]) -> None:
    """Yapılandırma parametrelerinin mantıksal geçerliliğini denetler.

    Args:
        config (Dict[str, Any]): Denetlenecek yapılandırma sözlüğü.
        
    Raises:
        ValueError: Geçersiz bir çalışma modu saptanırsa fırlatılır.
    """
    valid_modes: Set[str] = {"gmail", "local", "cleanup", "delete_label", "trash_emails"}
    mode: str = config.get("mode", "")
    if mode not in valid_modes:
        raise ValueError(f"Geçersiz çalışma modu: '{mode}'. Geçerli modlar: {', '.join(valid_modes)}")


def _ensure_dirs(config: Dict[str, Any]) -> None:
    """Yapılandırmada belirtilen tüm kritik klasörlerin varlığını kontrol eder ve oluşturur.

    Args:
        config (Dict[str, Any]): Klasör yollarını içeren yapılandırma sözlüğü.
    """
    logger: logging.Logger = logging.getLogger(__name__)
    paths_dict: Dict[str, Any] = config.get("paths", {})
    
    key: str
    for key in ("download_folder", "output_folder"):
        p: str = paths_dict.get(key, "")
        if p:
            p_abs: str = os.path.abspath(os.path.expanduser(p))
            paths_dict[key] = p_abs
            try:
                os.makedirs(p_abs, exist_ok=True)
                test_file: str = os.path.join(p_abs, ".test_write")
                with open(test_file, "w", encoding="utf-8") as f:
                    f.write("ok")
                os.remove(test_file)
            except (PermissionError, OSError):
                fallback_dir: str = os.path.join(_PUBLIC_BASE, key)
                logger.warning(
                    f"⛔ Klasör erişimi engellendi: {p_abs}\n"
                    f"   Otomatik olarak genel yola geçiliyor: {fallback_dir}"
                )
                paths_dict[key] = fallback_dir
                os.makedirs(fallback_dir, exist_ok=True)

    for key in ("database", "log_file"):
        p = paths_dict.get(key, "")
        if p:
            p_abs = os.path.abspath(os.path.expanduser(p))
            paths_dict[key] = p_abs
            d: str = os.path.dirname(p_abs)
            if d:
                try:
                    os.makedirs(d, exist_ok=True)
                    test_file = os.path.join(d, ".test_write")
                    with open(test_file, "w", encoding="utf-8") as f:
                        f.write("ok")
                    os.remove(test_file)
                except (PermissionError, OSError):
                    fallback_dir = _SECURE_BASE
                    logger.warning(
                        f"⛔ Dizin erişimi engellendi: {d}\n"
                        f"   Hassas dosya olduğu için güvenli ev dizinine geçiliyor: {fallback_dir}"
                    )
                    paths_dict[key] = os.path.join(fallback_dir, os.path.basename(p_abs))
                    os.makedirs(fallback_dir, exist_ok=True)

    manual: Dict[str, Any] = config.get("manual_source_settings", {})
    if manual.get("enabled"):
        k: str
        for k in ("folder_path", "processed_folder_path"):
            p = manual.get(k, "")
            if p:
                p_abs = os.path.abspath(os.path.expanduser(p))
                manual[k] = p_abs
                try:
                    os.makedirs(p_abs, exist_ok=True)
                    test_file = os.path.join(p_abs, ".test_write")
                    with open(test_file, "w", encoding="utf-8") as f:
                        f.write("ok")
                    os.remove(test_file)
                except (PermissionError, OSError):
                    fallback_dir = os.path.join(_PUBLIC_BASE, "manuel", 
                                                "islenenler" if k == "processed_folder_path" else "")
                    manual[k] = fallback_dir
                    os.makedirs(fallback_dir, exist_ok=True)