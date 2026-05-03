"""Uygulama genelinde kullanılan veri modelleri ve SQLAlchemy ORM şemaları.

Bu modül, hem iş mantığında kullanılan Dataclass yapılarını hem de
veritabanı işlemleri için kullanılan SQLAlchemy Declarative Base modellerini içerir.
"""

from dataclasses import dataclass, asdict
from typing import Optional, Any, Dict
from datetime import datetime

from sqlalchemy import Column, Integer, String, LargeBinary, DateTime, JSON
from sqlalchemy.orm import declarative_base

Base: Any = declarative_base()


class ProcessedEmail(Base):
    """İşlenmiş e-postaların durumlarını ve hata sayaçlarını tutan ORM Modeli."""
    __tablename__: str = "processed_emails"

    email_id = Column(String, primary_key=True, index=True)
    processed_at = Column(DateTime, nullable=True)
    fail_count = Column(Integer, default=0, nullable=False)
    last_fail_time = Column(DateTime, nullable=True)
    email_type = Column(String, default="normal")


class ProcessedReport(Base):
    """İşlenmiş PDF raporlarının kimliklerini (Mükerrer kontrolü) tutan ORM Modeli."""
    __tablename__: str = "processed_reports"

    report_id = Column(String, primary_key=True, index=True)
    processed_at = Column(DateTime, default=datetime.now, nullable=False)


class PdfFile(Base):
    """PDF dosyalarının BLOB formatında saklandığı ana tablo ORM Modeli."""
    __tablename__: str = "pdf_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(String, nullable=False, index=True)
    file_name = Column(String, nullable=False)
    file_data = Column(LargeBinary, nullable=False)
    file_size = Column(Integer, nullable=False)
    building = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    label_color = Column(String, nullable=True)
    stored_at = Column(DateTime, default=datetime.now, nullable=False)


class AppConfig(Base):
    """Uygulama yapılandırma (Config) ayarlarının veritabanında tutulduğu ORM Modeli."""
    __tablename__: str = "app_manifest"

    config_key = Column(String, primary_key=True, index=True)
    config_value = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TaskResult(Base):
    """Web arayüzünde gösterilecek sonuçları ve görev çıktılarını tutan ORM Modeli."""
    __tablename__: str = "task_results"

    task_name = Column(String, primary_key=True, index=True)
    result_data = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


@dataclass
class ReportResult:
    """İşlenmiş tek bir asansör muayene raporunu temsil eden veri sınıfı.

    Attributes:
        file_name (str): İşlenen dosyanın adı.
        provider (str): Raporu sağlayan kuruluş/servis.
        building_name (str): Asansörün bulunduğu binanın adı.
        label_color (str): Raporun durumunu belirten etiket rengi.
        inspection_date (str): Muayenenin yapıldığı tarih.
        next_inspection (str): Bir sonraki muayene için planlanan tarih.
        elevator_number (str): İlgili asansörün tanımlayıcı numarası.
        uuid (str): Kayıt için benzersiz kimlik (UUID).
    """
    file_name: str = ""
    provider: str = ""
    building_name: str = "Bilinmiyor"
    label_color: str = "Bulunamadı"
    inspection_date: str = "-"
    next_inspection: str = "N/A"
    elevator_number: str = "N/A"
    uuid: str = "N/A"

    def to_dict(self) -> Dict[str, Any]:
        """Nesne verilerini bir sözlüğe (dictionary) dönüştürür.

        Returns:
            Dict[str, Any]: Nesne özelliklerini içeren anahtar-değer çiftleri.
        """
        return asdict(self)

    @property
    def unique_key(self) -> str:
        """Rapor için benzersiz bir anahtar döndürür.

        UUID varsa UUID'yi, yoksa dosya adını referans alır.

        Returns:
            str: Kayıtların ayırt edilmesi için kullanılan benzersiz değer.
        """
        return self.uuid if self.uuid != "N/A" else self.file_name


@dataclass
class EmailMeta:
    """Çözünürlük filtreleme işlemleri için e-postadan çıkarılan meta veriler.

    Attributes:
        id_key (Optional[str]): E-posta için tanımlayıcı anahtar.
        name_key (Optional[str]): E-posta ile ilişkili isim anahtarı.
    """
    id_key: Optional[str] = None
    name_key: Optional[str] = None


@dataclass
class SourceConfig:
    """Yapılandırma dosyasından alınan bir e-posta kaynağı tanımı.

    Attributes:
        label_name (str): Gmail veya diğer servislerdeki etiket adı.
        query (str): E-postaları bulmak için kullanılan arama sorgusu.
        processor (str): Bu kaynağı işleyecek olan sınıf veya fonksiyonun adı.
    """
    label_name: str = ""
    query: str = ""
    processor: str = ""

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SourceConfig":
        """Verilen bir sözlükten SourceConfig örneği oluşturur.

        Args:
            d (Dict[str, Any]): Yapılandırma verilerini içeren sözlük.

        Returns:
            SourceConfig: Sözlükteki verilerle başlatılmış yeni bir yapılandırma nesnesi.
        """
        return SourceConfig(
            label_name=d.get("label_name", ""),
            query=d.get("query", ""),
            processor=d.get("processor", ""),
        )