"""
SQLAlchemy ORM: Uygulamanın veritabanı işlemlerinin yürütüldüğü merkezi yapı.
ACID uyumlu, Thread-Safe oturum yönetimleri sunar.
"""

import os
import logging
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Set, Any, Optional, List

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.orm.attributes import flag_modified

from cryptography.fernet import Fernet

from app.paths import paths
from app.utils.logging import get_logger
from app.core.models import (
    Base, ProcessedEmail, ProcessedReport, PdfFile, TaskResult, AppConfig
)

log: logging.Logger = get_logger(__name__)


def _get_encryption_key() -> bytes:
    """Sistem için benzersiz ve güvenli bir AES-256 şifreleme anahtarı üretir veya okur.

    Returns:
        bytes: Üretilen veya diskten okunan AES-256 uyumlu şifreleme anahtarı.
    """
    key_path: str = paths.MASTER_KEY_FILE
    
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            return f.read().strip()
    else:
        key: bytes = Fernet.generate_key()
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        
        with open(key_path, "wb") as f:
            f.write(key)
            
        try:
            os.chmod(key_path, 0o600)
        except Exception:
            pass
            
        return key

_cipher: Fernet = Fernet(_get_encryption_key())

_engine: Any = None
_session_factory: sessionmaker = sessionmaker()
SessionScoped: scoped_session = scoped_session(_session_factory)


def _get_db_path() -> str:
    """Bu fonksiyon CLI ve Web Sunucusu arasındaki veritabanı yolu
    uyumsuzluğunu (çift veritabanı oluşması) çözer.
    Veritabanını her koşulda projenin kök dizinine sabitler.
    
    Returns:
        str: Veritabanının mutlak dosya yolu.
    """
    path_str: str = str(paths.DEFAULT_DB_PATH)
    
    if os.path.isabs(path_str):
        return path_str
        
    current_dir: str = os.path.dirname(os.path.abspath(__file__))
    project_root: str = os.path.dirname(os.path.dirname(current_dir))
    
    return os.path.join(project_root, path_str)


def _init_db(path: Optional[str] = None) -> Any:
    """Veritabanı motorunu başlatır ve tabloları güvenceye alır.
    
    Geçersiz veya boş veritabanı yollarının in-memory
    veritabanlarına yol açmasını engeller.
    
    Args:
        path (Optional[str]): Veritabanı dosya yolu. Belirtilmezse otomatik tespit eder.
        
    Returns:
        Any: Başlatılmış ve yapılandırılmış SQLAlchemy Engine nesnesi.
    """
    global _engine
    
    if not path or str(path).strip() == "" or path == paths.LEGACY_DB_PATH:
        path = _get_db_path()
        
    db_uri: str = f"sqlite:///{path}"
    
    if _engine is not None and str(_engine.url) == db_uri:
        return _engine
        
    directory: str = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
        
    _engine = create_engine(db_uri, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=_engine)
    
    _session_factory.configure(bind=_engine)
    
    log.info(f"💾 ORM Veritabanı bağlandı: {path}")
        
    return _engine


def _get_default_session() -> Any:
    """Modül seviyesindeki fonksiyonlar için varsayılan Thread-Safe oturumu döndürür.
    
    Returns:
        Any: Başlatılmış SQLAlchemy oturum (Session) nesnesi.
    """
    global _engine
    
    if _engine is None:
        _init_db()
        
    return SessionScoped()


def get_task_result(task_name: str) -> Optional[Dict[str, Any]]:
    """Belirtilen bir görev (task) için kayıtlı sonucu getirir.

    Args:
        task_name (str): Görevin veritabanındaki benzersiz adı.

    Returns:
        Optional[Dict[str, Any]]: Görev sonucunu barındıran veri kümesi veya bulunamazsa None.
    """
    session: Any = _get_default_session()
    try:
        task = session.query(TaskResult).filter_by(task_name=task_name).first()
        return {"data": task.result_data} if task and task.result_data else None
    finally:
        SessionScoped.remove()


def set_task_result(task_name: str, data: Dict[str, Any]) -> None:
    """Belirtilen bir görevin sonucunu ORM üzerine yazar.

    Args:
        task_name (str): Görevin adı.
        data (Dict[str, Any]): Kaydedilecek JSON uyumlu sözlük (data key'i içermelidir).
        
    Raises:
        Exception: Veritabanı commit veya kayıt işlemi sırasında oluşan hataları fırlatır.
    """
    session: Any = _get_default_session()
    try:
        task = session.query(TaskResult).filter_by(task_name=task_name).first()
        result_data: Any = data.get("data", [])
        
        if not task:
            task = TaskResult(task_name=task_name, result_data=result_data)
            session.add(task)
        else:
            task.result_data = result_data
            flag_modified(task, "result_data")
            
        session.commit()
    except Exception as e:
        session.rollback()
        log.error(f"Görev sonucu kaydedilemedi ({task_name}): {e}")
        raise
    finally:
        SessionScoped.remove()


def get_secure_config(key: str) -> Optional[Dict[str, Any]]:
    """Veritabanından yapılandırmayı okur, eğer şifreliyse AES-256 ile çözer.
    
    Args:
        key (str): Okunacak yapılandırmanın anahtar değeri.
        
    Returns:
        Optional[Dict[str, Any]]: Çözülmüş yapılandırma sözlüğü veya bulunamazsa None.
    """
    session: Any = _get_default_session()
    try:
        record = session.query(AppConfig).filter_by(config_key=key).first()
        
        if record and record.config_value:
            enc_data: Optional[str] = record.config_value.get("encrypted_data")
            
            if enc_data:
                decrypted_bytes: bytes = _cipher.decrypt(enc_data.encode('utf-8'))
                return json.loads(decrypted_bytes.decode('utf-8'))
                
            return record.config_value
            
        return None
    finally:
        SessionScoped.remove()


def set_secure_config(key: str, value: Dict[str, Any]) -> None:
    """Veriyi AES-256 ile şifreleyerek veritabanına kaydeder.
    
    Args:
        key (str): Kaydedilecek yapılandırmanın anahtar değeri.
        value (Dict[str, Any]): Şifrelenerek kaydedilecek sözlük verisi.
        
    Raises:
        Exception: Şifreleme veya veritabanına yazma sırasında oluşabilecek hataları fırlatır.
    """
    session: Any = _get_default_session()
    try:
        json_str: str = json.dumps(value)
        encrypted_bytes: bytes = _cipher.encrypt(json_str.encode('utf-8'))
        
        secure_payload: Dict[str, str] = {"encrypted_data": encrypted_bytes.decode('utf-8')}

        record = session.query(AppConfig).filter_by(config_key=key).first()
        
        if not record:
            record = AppConfig(config_key=key, config_value=secure_payload)
            session.add(record)
        else:
            record.config_value = secure_payload
            flag_modified(record, "config_value")
            
        session.commit()
    except Exception as e:
        session.rollback()
        log.error(f"Güvenli kayıt hatası ({key}): {e}")
        raise
    finally:
        SessionScoped.remove()
        

def delete_secure_config(key: str) -> bool:
    """Belirtilen güvenli yapılandırmayı veritabanından siler.
    
    Args:
        key (str): Silinecek yapılandırmanın anahtar değeri.
        
    Returns:
        bool: İşlem başarılı ise True, kayıt bulunamadıysa veya hata varsa False.
    """
    session: Any = _get_default_session()
    try:
        deleted: int = session.query(AppConfig).filter_by(config_key=key).delete()
        session.commit()
        return deleted > 0
    except Exception as e:
        session.rollback()
        log.error(f"Güvenli silme hatası ({key}): {e}")
        return False
    finally:
        SessionScoped.remove()


class Database:
    """Thread-safe SQLAlchemy ORM yönetim sınıfı.
    
    Tüm veritabanı etkileşimleri bu sınıf üzerinden izole oturumlarla yürütülür.
    
    Attributes:
        _path (str): SQLite veritabanı dosyasının yolu.
        engine (Any): SQLAlchemy engine nesnesi.
        Session (scoped_session): Güvenli işlemler için thread-local oturum nesnesi.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        """Veritabanı bağlantısını başlatır ve eksik tabloları oluşturur.

        Args:
            path (Optional[str]): Veritabanı dosyasının disk üzerindeki yolu.
        """
        if not path or path.strip() == "" or path == paths.LEGACY_DB_PATH:
            path = _get_db_path()
            
        self._path: str = path
        self.engine: Any = _init_db(path)
        self.Session: scoped_session = SessionScoped

    def close(self) -> None:
        """Mevcut iş parçacığındaki veritabanı oturumunu güvenli bir şekilde kapatır."""
        self.Session.remove()

    def load_email_map(self) -> Dict[str, Dict[str, Any]]:
        """İşlenmiş e-postaların durumlarını ve hata sayılarını yükler.

        Returns:
            Dict[str, Dict[str, Any]]: email_id anahtarlı durum haritası.
        """
        session: Any = self.Session()
        try:
            records: List[ProcessedEmail] = session.query(ProcessedEmail).all()
            return {
                r.email_id: {
                    "fail_count": r.fail_count, 
                    "last_fail_time": r.last_fail_time.isoformat() if r.last_fail_time else None
                } for r in records
            }
        finally:
            self.Session.remove()

    def load_report_ids(self) -> Set[str]:
        """Daha önce başarıyla işlenmiş rapor kimliklerini yükler.

        Returns:
            Set[str]: Benzersiz rapor kimliklerini içeren küme.
        """
        session: Any = self.Session()
        try:
            records = session.query(ProcessedReport.report_id).all()
            return {r[0] for r in records}
        finally:
            self.Session.remove()

    def mark_email_success(self, email_id: str, email_type: str = "normal") -> None:
        """E-postayı başarıyla işlendi olarak işaretler ve hata sayısını sıfırlar.

        Args:
            email_id (str): İşlenen e-postanın benzersiz kimliği.
            email_type (str): E-posta türü (örn: 'normal', 'randevu'). Varsayılan "normal".
        """
        session: Any = self.Session()
        try:
            email = session.query(ProcessedEmail).filter_by(email_id=email_id).first()
            
            if not email:
                email = ProcessedEmail(
                    email_id=email_id, 
                    processed_at=datetime.now(),
                    fail_count=0,
                    email_type=email_type
                )
                session.add(email)
            else:
                email.processed_at = datetime.now()
                email.fail_count = 0
                email.last_fail_time = None
                email.email_type = email_type
                
            session.commit()
        except Exception as e:
            session.rollback()
            log.error(f"E-posta başarı durumu işaretlenemedi ({email_id}): {e}")
        finally:
            self.Session.remove()

    def add_report(self, report_id: str) -> None:
        """Rapor kimliğini işlendi olarak kaydederek mükerrer işlemleri önler.

        Args:
            report_id (str): İşlenen raporun benzersiz kimliği.
        """
        session: Any = self.Session()
        try:
            report = session.query(ProcessedReport).filter_by(report_id=report_id).first()
            
            if not report:
                report = ProcessedReport(report_id=report_id, processed_at=datetime.now())
                session.add(report)
                session.commit()
        except Exception as e:
            session.rollback()
            log.error(f"Rapor ID kaydedilemedi ({report_id}): {e}")
        finally:
            self.Session.remove()

    def increment_fail(self, email_id: str) -> None:
        """E-posta işleme hatası oluştuğunda hata sayacını artırır.

        Args:
            email_id (str): Hataya neden olan e-postanın kimliği.
        """
        session: Any = self.Session()
        try:
            email = session.query(ProcessedEmail).filter_by(email_id=email_id).first()
            
            if not email:
                email = ProcessedEmail(
                    email_id=email_id,
                    fail_count=1,
                    last_fail_time=datetime.now()
                )
                session.add(email)
            else:
                email.fail_count += 1
                email.last_fail_time = datetime.now()
                email.processed_at = None
                
            session.commit()
        except Exception as e:
            session.rollback()
            log.error(f"Hata sayacı artırılamadı ({email_id}): {e}")
        finally:
            self.Session.remove()

    def cleanup_old(self, days: int = 180) -> int:
        """Belirtilen günden daha eski başarılı kayıtları veritabanından temizler.

        Args:
            days (int): Kaç günden eski kayıtların silineceği (Varsayılan: 180).

        Returns:
            int: Silinen toplam kayıt sayısı.
        """
        session: Any = self.Session()
        try:
            threshold_date: datetime = datetime.now() - timedelta(days=days)
            
            deleted_emails: int = session.query(ProcessedEmail).filter(
                ProcessedEmail.fail_count == 0,
                ProcessedEmail.processed_at < threshold_date
            ).delete()
            
            deleted_reports: int = session.query(ProcessedReport).filter(
                ProcessedReport.processed_at < threshold_date
            ).delete()
            
            session.commit()
            total_deleted: int = deleted_emails + deleted_reports
            
            if total_deleted > 0:
                log.info(f"🧹 ORM temizlendi: {total_deleted} eski kayıt silindi ({days} günden eski)")
                
            return total_deleted
        except Exception as e:
            session.rollback()
            log.error(f"Veritabanı temizlik işlemi sırasında hata: {e}")
            return 0
        finally:
            self.Session.remove()

    def store_pdf(self, report_id: str, file_name: str, file_path: str,
                  building: str = "", provider: str = "", label_color: str = "") -> bool:
        """Bir PDF dosyasını okur ve içeriğini BLOB olarak veritabanına kaydeder.

        Args:
            report_id (str): İlgili raporun kimliği.
            file_name (str): Dosyanın orijinal adı.
            file_path (str): Dosyanın disk üzerindeki yolu.
            building (str): Bina adı (isteğe bağlı).
            provider (str): Raporu sağlayan kuruluş (isteğe bağlı).
            label_color (str): Etiket rengi (isteğe bağlı).

        Returns:
            bool: İşlem başarılıysa True, dosya okunamazsa veya kayıt hatası oluşursa False.
        """
        try:
            if not os.path.exists(file_path):
                log.warning(f"⚠️ Dosya bulunamadı: {file_path}")
                return False
                
            with open(file_path, "rb") as f:
                data: bytes = f.read()
                
            session: Any = self.Session()
            try:
                existing = session.query(PdfFile).filter_by(
                    report_id=report_id, file_name=file_name
                ).first()
                
                if existing:
                    existing.file_data = data
                    existing.file_size = len(data)
                    existing.building = building
                    existing.provider = provider
                    existing.label_color = label_color
                    existing.stored_at = datetime.now()
                else:
                    new_pdf = PdfFile(
                        report_id=report_id,
                        file_name=file_name,
                        file_data=data,
                        file_size=len(data),
                        building=building,
                        provider=provider,
                        label_color=label_color,
                        stored_at=datetime.now()
                    )
                    session.add(new_pdf)
                    
                session.commit()
                return True
            except Exception as e:
                session.rollback()
                log.error(f"PDF kaydetme (ORM) hatası: {e}")
                return False
            finally:
                self.Session.remove()
        except Exception as io_err:
            log.error(f"PDF dosya okuma hatası: {io_err}")
            return False

    def get_pdf(self, pdf_id: int) -> Optional[Dict[str, Any]]:
        """Veritabanından ID'si belirtilen PDF dosyasını içeriğiyle birlikte getirir.

        Args:
            pdf_id (int): Veritabanındaki benzersiz PDF kaydı ID'si.

        Returns:
            Optional[Dict[str, Any]]: PDF verilerini içeren sözlük veya bulunamazsa None.
        """
        session: Any = self.Session()
        try:
            record = session.query(PdfFile).filter_by(id=pdf_id).first()
            
            if not record:
                return None
                
            return {
                "id": record.id, 
                "report_id": record.report_id, 
                "file_name": record.file_name, 
                "file_data": record.file_data,
                "file_size": record.file_size, 
                "building": record.building, 
                "provider": record.provider, 
                "label_color": record.label_color, 
                "stored_at": record.stored_at.isoformat() if record.stored_at else None
            }
        finally:
            self.Session.remove()

    def get_pdf_by_report(self, report_id: str) -> Optional[Dict[str, Any]]:
        """Bir rapor kimliğine ait ilk PDF dosyasını getirir.

        Args:
            report_id (str): Aranacak raporun kimliği.

        Returns:
            Optional[Dict[str, Any]]: PDF verilerini içeren sözlük veya bulunamazsa None.
        """
        session: Any = self.Session()
        try:
            record = session.query(PdfFile).filter_by(report_id=report_id).first()
            
            if not record:
                return None
                
            return {
                "id": record.id, 
                "report_id": record.report_id, 
                "file_name": record.file_name, 
                "file_data": record.file_data,
                "file_size": record.file_size, 
                "building": record.building, 
                "provider": record.provider, 
                "label_color": record.label_color, 
                "stored_at": record.stored_at.isoformat() if record.stored_at else None
            }
        finally:
            self.Session.remove()

    def list_pdfs(self, limit: int = 500) -> List[Dict[str, Any]]:
        """Sistemde kayıtlı PDF'lerin listesini içerik verisi olmadan döndürür.

        Args:
            limit (int): Döndürülecek maksimum kayıt sayısı (Varsayılan: 500).

        Returns:
            List[Dict[str, Any]]: PDF meta verilerini içeren sözlük listesi.
        """
        session: Any = self.Session()
        try:
            records = session.query(
                PdfFile.id, PdfFile.report_id, PdfFile.file_name, 
                PdfFile.file_size, PdfFile.building, PdfFile.provider, 
                PdfFile.label_color, PdfFile.stored_at
            ).order_by(PdfFile.stored_at.desc()).limit(limit).all()
            
            return [
                {
                    "id": r.id, "report_id": r.report_id, "file_name": r.file_name, 
                    "file_size": r.file_size, "building": r.building, 
                    "provider": r.provider, "label_color": r.label_color, 
                    "stored_at": r.stored_at.isoformat() if r.stored_at else None
                }
                for r in records
            ]
        finally:
            self.Session.remove()

    def export_pdf(self, pdf_id: int, dest_folder: str) -> Optional[str]:
        """Veritabanındaki bir PDF dosyasını disk üzerine dışa aktarır.

        Args:
            pdf_id (int): Dışa aktarılacak PDF'in ID'si.
            dest_folder (str): Dosyanın kaydedileceği klasör yolu.

        Returns:
            Optional[str]: Kaydedilen dosyanın tam yolu veya hata durumunda None.
        """
        pdf: Optional[Dict[str, Any]] = self.get_pdf(pdf_id)
        
        if not pdf:
            return None
            
        os.makedirs(dest_folder, exist_ok=True)
        path: str = os.path.join(dest_folder, pdf["file_name"])
        
        try:
            with open(path, "wb") as f:
                f.write(pdf["file_data"])
            return path
        except Exception as e:
            log.error(f"PDF dışa aktarma hatası: {e}")
            return None