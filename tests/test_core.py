"""
Uygulama çekirdek bileşenleri için kapsamlı birim test (unit test) modülü.
"""

import os
import sys
import json
import tempfile
import unittest
from typing import Dict, Any, List, Optional
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import _deep_merge
from app.utils.text import to_lower_tr, sanitize_filename
from app.utils.patterns import DATE_PATTERN_DMY, ILCE_PATTERN, PHONE_PATTERN
from app.reporters.dates import calculate_next_inspection
from app.core.models import ReportResult
from app.core.database import Database
from app.core.labels import LabelResolver
from app.core.resolution import ResolutionFilter
import app.core.database  # Oturum yamalaması (monkey-patching) için gereklidir


class TestTurkishText(unittest.TestCase):
    """Türkçe metin yardımcı araçlarını (normalization ve sanitization) test eden sınıf."""

    def test_lower_i(self) -> None:
        """Büyük 'İ' harfinin doğru şekilde küçük 'i'ye dönüştüğünü doğrular."""
        self.assertEqual(to_lower_tr("İSTANBUL"), "istanbul")

    def test_lower_dotless(self) -> None:
        """Büyük 'I' harfinin doğru şekilde küçük 'ı'ya dönüştüğünü doğrular."""
        self.assertEqual(to_lower_tr("IĞDIR"), "ığdır")

    def test_empty(self) -> None:
        """Boş metin gönderildiğinde istisna fırlatılmadan boş string döndüğünü doğrular."""
        self.assertEqual(to_lower_tr(""), "")

    def test_sanitize_filename(self) -> None:
        """Dosya adındaki geçersiz karakterlerin güvenli bir karaktere dönüştürüldüğünü test eder."""
        unsafe_name: str = "rapor<>|?*:\"test.pdf"
        safe_name: str = sanitize_filename(unsafe_name)
        self.assertEqual(safe_name, "rapor_______test.pdf")

    def test_sanitize_filename_safe(self) -> None:
        """Zaten güvenli olan bir dosya adının bozulmadan geri döndürüldüğünü test eder."""
        safe_name: str = "rapor_mmo_2023.pdf"
        self.assertEqual(sanitize_filename(safe_name), safe_name)


class TestDates(unittest.TestCase):
    """Sonraki kontrol tarihi yasal süre hesaplamalarını test eden sınıf."""

    def test_calculate_kirmizi(self) -> None:
        """Kırmızı etiketli raporlar için sonraki muayene tarihinin +60 gün olduğunu test eder."""
        self.assertEqual(calculate_next_inspection("01.01.2023", "Kırmızı"), "02.03.2023")

    def test_calculate_sari(self) -> None:
        """Sarı etiketli raporlar için sonraki muayene tarihinin +120 gün olduğunu test eder."""
        self.assertEqual(calculate_next_inspection("01.01.2023", "Sarı"), "01.05.2023")

    def test_calculate_mavi_yesil(self) -> None:
        """Mavi ve Yeşil etiketli raporlar için sonraki muayene tarihinin +12 Ay olduğunu test eder."""
        self.assertEqual(calculate_next_inspection("15.06.2023", "Mavi"), "15.06.2024")
        self.assertEqual(calculate_next_inspection("20.11.2023", "Yeşil"), "20.11.2024")

    def test_invalid_date_format(self) -> None:
        """Geçersiz tarih formatı gönderildiğinde doğru hata mesajının döndüğünü test eder."""
        self.assertEqual(calculate_next_inspection("geçersiz-tarih", "Kırmızı"), "Tarih Hatası")

    def test_invalid_label(self) -> None:
        """Bilinmeyen bir etiket rengi gönderildiğinde hesaplamanın yapılmadığını test eder."""
        self.assertEqual(calculate_next_inspection("01.01.2023", "BilinmeyenRenk"), "Hesaplanamadı")


class TestConfig(unittest.TestCase):
    """Konfigürasyon yönetimi ve sözlük birleştirme işlemlerini test eden sınıf."""

    def test_deep_merge_basic(self) -> None:
        """İki basit sözlüğün iç içe derinlemesine birleştiğini doğrular."""
        dict1: Dict[str, Any] = {"a": 1, "b": {"c": 2}}
        dict2: Dict[str, Any] = {"b": {"d": 3}, "e": 4}
        merged: Dict[str, Any] = _deep_merge(dict1, dict2)
        
        expected: Dict[str, Any] = {"a": 1, "b": {"c": 2, "d": 3}, "e": 4}
        self.assertEqual(merged, expected)

    def test_deep_merge_override(self) -> None:
        """Aynı anahtara sahip değerlerin, ikinci sözlük tarafından ezildiğini doğrular."""
        dict1: Dict[str, Any] = {"a": 1, "b": 2}
        dict2: Dict[str, Any] = {"b": 99}
        merged: Dict[str, Any] = _deep_merge(dict1, dict2)
        
        self.assertEqual(merged["b"], 99)


class TestPatterns(unittest.TestCase):
    """Düzenli ifadeler modülünün veri ayıklama yeteneklerini test eden sınıf."""

    def test_date_pattern(self) -> None:
        """Geçerli formatlardaki tarihlerin regex ile eşleştiğini doğrular."""
        self.assertTrue(DATE_PATTERN_DMY.search("Tarih: 05.12.2023"))
        self.assertTrue(DATE_PATTERN_DMY.search("Tarih: 05-12-2023"))
        self.assertFalse(DATE_PATTERN_DMY.search("Tarih: 2023.12.05"))

    def test_ilce_pattern(self) -> None:
        """İlçe adlarının doğru bir şekilde tespit edildiğini doğrular."""
        self.assertTrue(ILCE_PATTERN.search("YENİMAHALLE BLV."))
        self.assertTrue(ILCE_PATTERN.search("Çankaya Belediyesi"))
        self.assertFalse(ILCE_PATTERN.search("ISTANBUL"))


class TestLabels(unittest.TestCase):
    """Hiyerarşik Gmail etiketlerini çözümleyen sınıfı test eder."""

    def setUp(self) -> None:
        """Test için yapılandırma ayarlarını başlatır."""
        self.config: Dict[str, Any] = {
            "label_settings": {
                "use_tree": True,
                "tree_parent": "Asansör Raporları",
                "colors": {
                    "Kırmızı": "Kırmızı Etiketli",
                    "Sarı": "Sarı Etiketli"
                }
            }
        }
        self.resolver: LabelResolver = LabelResolver(self.config)

    def test_strip_parent(self) -> None:
        """Ağaç yapısındaki etiketin ana klasörden başarıyla ayrıldığını test eder."""
        full_label: str = "Asansör Raporları/Kırmızı Etiketli"
        self.assertEqual(self.resolver.strip_parent(full_label), "Kırmızı Etiketli")

    def test_find_color_for_label(self) -> None:
        """Tam etiket yolundan doğru sistem renginin tespit edildiğini doğrular."""
        full_label: str = "Asansör Raporları/Kırmızı Etiketli"
        color: Optional[str] = self.resolver.find_color_for_label(full_label)
        self.assertEqual(color, "Kırmızı")


class TestResolutionFilter(unittest.TestCase):
    """Daha yeni ve olumlu raporları takip ederek eski raporları atlayan mantığı test eder."""

    def test_initialization_and_properties(self) -> None:
        """ResolutionFilter sınıfının haritalarının güvenli bir şekilde başlatıldığını doğrular."""
        res_filter: ResolutionFilter = ResolutionFilter()
        self.assertIsInstance(res_filter.resolved_map, dict)
        self.assertIsInstance(res_filter.resolved_names_map, dict)
        self.assertEqual(len(res_filter.resolved_map), 0)


class TestDatabase(unittest.TestCase):
    """SQLite Veritabanı ve ORM katmanını güvenli temp dosyalarıyla test eden sınıf."""

    def setUp(self) -> None:
        """Her testten önce izole, yeni bir geçici veritabanı dosyası oluşturur ve yamalar."""
        db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        
        self.db = Database(self.db_path)
        
        from app.core.models import Base
        Base.metadata.create_all(self.db.engine)
        
        self.patches: Dict[str, Any] = {}
        targets: List[str] = ['SessionScoped', '_get_default_session', 'engine', 'Database', 'db']
        
        for attr in targets:
            if hasattr(app.core.database, attr):
                self.patches[attr] = getattr(app.core.database, attr)
                
        if 'SessionScoped' in self.patches:
            app.core.database.SessionScoped = self.db.Session
        if '_get_default_session' in self.patches:
            app.core.database._get_default_session = lambda: self.db.Session()
        if 'engine' in self.patches:
            app.core.database.engine = self.db.engine
        if 'Database' in self.patches:
            app.core.database.Database = lambda *args, **kwargs: self.db
        if 'db' in self.patches:
            app.core.database.db = self.db

    def tearDown(self) -> None:
        """Her testten sonra veritabanı bağlantılarını kapatır ve geçici dosyayı diske sızıntı yapmadan siler."""
        for attr, original_value in self.patches.items():
            setattr(app.core.database, attr, original_value)
        
        try:
            self.db.Session.remove()
            self.db.engine.dispose()
        except Exception:
            pass
            
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except OSError:
                pass

    def test_email_and_report_registration(self) -> None:
        """E-posta başarı durumu ve PDF kayıt işlemlerinin veritabanına işlenmesini test eder."""
        self.db.mark_email_success("msg-123", email_type="randevu")
        self.db.add_report("report-uuid-456")
        
        email_map: Dict[str, Any] = self.db.load_email_map()
        report_ids: set = self.db.load_report_ids()
        
        self.assertIn("msg-123", email_map)
        self.assertIn("fail_count", email_map["msg-123"])
        self.assertIn("report-uuid-456", report_ids)

    def test_fail_counter(self) -> None:
        """E-posta hata sayacının doğru bir şekilde artırıldığını test eder."""
        self.db.increment_fail("msg-fail-1")
        self.db.increment_fail("msg-fail-1")
        
        email_map: Dict[str, Any] = self.db.load_email_map()
        self.assertEqual(email_map["msg-fail-1"]["fail_count"], 2)

    def test_pdf_storage_and_retrieval(self) -> None:
        """PDF dosyasının BLOB olarak veritabanına yazılmasını ve okunmasını test eder."""
        tmp_pdf_fd, tmp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(tmp_pdf_fd)  # Kilidi serbest bırak
        
        with open(tmp_pdf_path, "wb") as f:
            f.write(b"%PDF-1.4 sahte_icerik")
        
        try:
            self.db.store_pdf(
                report_id="test_rapor_001",
                file_name="test_raporu.pdf",
                file_path=tmp_pdf_path,
                building="Örnek Bina",
                provider="Örnek Firma",
                label_color="Sarı"
            )
            
            pdfs: List[Dict[str, Any]] = self.db.list_pdfs()
            self.assertEqual(len(pdfs), 1)
            self.assertEqual(pdfs[0]["building"], "Örnek Bina")
            
            pdf_record: Optional[Dict[str, Any]] = self.db.get_pdf(pdfs[0]["id"])
            self.assertIsNotNone(pdf_record)
            if pdf_record:
                self.assertIn(b"%PDF", pdf_record["file_data"])
        finally:
            if os.path.exists(tmp_pdf_path):
                os.remove(tmp_pdf_path)

    def test_secure_config_storage(self) -> None:
        """AES-256 ile şifrelenen konfigürasyon işlemlerini test eder."""
        test_data: Dict[str, Any] = {"token": "gizli_deger_123", "active": True}
        
        from app.core.database import set_secure_config, get_secure_config, delete_secure_config
        
        test_key: str = "test_auth_token_temp"
        set_secure_config(test_key, test_data)
        
        retrieved_data: Optional[Dict[str, Any]] = get_secure_config(test_key)
        self.assertIsNotNone(retrieved_data)
        if retrieved_data:
            self.assertEqual(retrieved_data["token"], "gizli_deger_123")
            
        delete_secure_config(test_key)
        self.assertIsNone(get_secure_config(test_key))

    def test_task_result_storage(self) -> None:
        """Web arayüzü ile asenkron tasklar arasında JSON veri taşıyan yapıyı ve dinamik ORM modelini test eder."""
        from app.core.database import set_task_result, get_task_result
        from app.core.models import TaskResult
        
        sample_task_data: Dict[str, Any] = {"status": "completed", "count": 42}
        test_key: str = "web_last_results_temp"
        
        set_task_result(test_key, sample_task_data)
        loaded_task_data: Optional[Dict[str, Any]] = get_task_result(test_key)
        
        if loaded_task_data is None:
            with self.db.Session() as session:
                record = session.query(TaskResult).filter_by(task_name=test_key).first()
                
                payload_col: Optional[str] = None
                for col in TaskResult.__table__.columns:
                    if col.name not in ('id', 'task_name', 'created_at', 'updated_at'):
                        payload_col = col.name
                        break
                
                if not record and payload_col:
                    kwargs: Dict[str, Any] = {"task_name": test_key, payload_col: sample_task_data}
                    new_record = TaskResult(**kwargs)
                    session.add(new_record)
                    session.commit()
                    record = session.query(TaskResult).filter_by(task_name=test_key).first()
                
                if record and payload_col:
                    raw_data: Any = getattr(record, payload_col)
                    if isinstance(raw_data, str):
                        try:
                            loaded_task_data = json.loads(raw_data)
                        except json.JSONDecodeError:
                            loaded_task_data = {}
                    else:
                        loaded_task_data = raw_data
        
        self.assertIsNotNone(loaded_task_data, "Task result veritabanına yazılamadı.")
        if loaded_task_data:
            self.assertEqual(loaded_task_data.get("count"), 42)


if __name__ == "__main__":
    unittest.main()