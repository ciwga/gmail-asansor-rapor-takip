"""
Gmail bakım modülü: Etiket temizliği, e-posta çöpe atma ve etiket silme işlemlerini yönetir.

Bu modül, Gmail kutusunu düzenli tutmak için tanımlanan kuralları işletir. 
Web arayüzü etkileşimlerinde oluşabilecek mükerrer işlemleri önlemek için kilit mekanizması 
ve API hatalarına karşı dayanıklılık katmanları içerir.
"""

import time
import threading
from typing import Dict, Callable, Any, List, Optional

from googleapiclient.errors import HttpError

from app.gmail.client import get_all_messages, BATCH_SIZE_MODIFY
from app.utils.logging import get_logger
from app.gmail.auth import authenticate

log: Any = get_logger(__name__)

_maintenance_lock: threading.Lock = threading.Lock()


def _batch_callback(request_id: str, response: Any, exception: Optional[Exception]) -> None:
    """Google API toplu işlemleri için geri çağırma fonksiyonu.

    Args:
        request_id (str): İsteğin benzersiz kimliği.
        response (Any): API'den dönen yanıt nesnesi.
        exception (Optional[Exception]): Eğer bir hata oluştuysa ilgili istisna nesnesi.
    """
    if exception:
        if isinstance(exception, HttpError) and exception.resp.status == 429:
            log.warning(f"Hız limitine takıldı - İstek kimliği: {request_id}")
        else:
            log.error(f"Toplu işlem hatası - İstek kimliği {request_id}: {exception}")


def run_rules_engine(
    service: Any,
    settings: Dict[str, Any],
    labels_map: Dict[str, str],
    is_test: bool,
    action_fn: Callable,
) -> int:
    """Temizlik veya çöpe atma kurallarını yapılandırmaya göre işletir.

    Args:
        service (Any): Gmail API servis nesnesi.
        settings (Dict[str, Any]): İlgili modun ayarları.
        labels_map (Dict[str, str]): Etiket haritası.
        is_test (bool): True ise gerçek işlem yapmaz, sadece log üretir.
        action_fn (Callable): Her mesaj için oluşturulacak API isteğini belirleyen fonksiyon.

    Returns:
        int: İşlemden etkilenen toplam mesaj sayısı.
    """
    rules: List[Dict[str, Any]] = settings.get("cleanup_rules", settings.get("trash_rules", []))
    
    if not rules:
        log.warning("Bu mod için tanımlanmış herhangi bir kural bulunamadı.")
        return 0

    total: int = 0
    
    i: int
    rule: Dict[str, Any]
    for i, rule in enumerate(rules, 1):
        comment: str = rule.get("comment", f"Kural #{i}")
        log.info(f"--- KURAL #{i}: {comment} ---")

        filters: Dict[str, Any] = rule.get("filters", {})
        query_parts: List[str] = []

        label_names: List[str] = rule.get("labels_to_remove", filters.get("required_labels", []))
        if label_names:
            valid: List[str] = [f'"{n}"' for n in label_names if n in labels_map]
            if valid:
                query_parts.append(f'({" OR ".join(f"label:{n}" for n in valid)})')
            else:
                log.warning("Kural atlandı: Belirtilen etiketler Gmail üzerinde bulunamadı.")
                continue

        senders: Optional[List[str]] = filters.get("from_senders")
        if senders:
            query_parts.append(f'({" OR ".join(f"from:{s}" for s in senders)})')
            
        keywords: Optional[List[str]] = filters.get("subject_keywords")
        if keywords:
            joined: str = " OR ".join(f'"{kw}"' for kw in keywords)
            query_parts.append(f"(subject:({joined}))")
            
        days: Any = filters.get("days_older_than")
        if days and isinstance(days, int) and days > 0:
            query_parts.append(f"older_than:{days}d")

        query: str = " ".join(query_parts) if query_parts else "label:all"
        log.info(f"Sorgu: {query}")

        messages: List[Dict[str, Any]] = get_all_messages(service, query)
        if not messages:
            log.info("Eşleşen herhangi bir e-posta bulunamadı.")
            continue

        log.info(f"{len(messages)} adet e-posta bulundu.")
        total += len(messages)

        if is_test:
            log.warning(f"TEST MODU: {len(messages)} e-posta bu kuraldan etkilenecekti.")
            msg: Dict[str, Any]
            for msg in messages[:20]:
                log.info(f"  - Örnek kimlik: {msg['id']}")
            if len(messages) > 20:
                log.info(f"  ... ve {len(messages) - 20} adet daha.")
        else:
            log.warning(f"CANLI MOD: {len(messages)} e-posta işleniyor...")
            batch: Any = service.new_batch_http_request(callback=_batch_callback)
            count: int = 0
            
            for msg in messages:
                try:
                    api_call: Any = action_fn(service, msg["id"], rule, labels_map)
                    if api_call:
                        batch.add(api_call)
                        count += 1
                    
                    if count >= BATCH_SIZE_MODIFY:
                        batch.execute()
                        time.sleep(1)
                        batch = service.new_batch_http_request(callback=_batch_callback)
                        count = 0
                except Exception as e:
                    log.error(f"Toplu işleme ekleme hatası (Kimlik: {msg['id']}): {e}")

            if count > 0:
                batch.execute()
            log.info(f"Kural tamamlandı: {len(messages)} e-posta işlendi.")

    return total


def create_cleanup_request(service: Any, msg_id: str, rule: Dict[str, Any], labels_map: Dict[str, str]) -> Any:
    """Bir mesajdan belirli etiketleri kaldırmak için API isteği oluşturur.

    Args:
        service (Any): Gmail API servisi.
        msg_id (str): Mesaj kimliği.
        rule (Dict[str, Any]): İşletilen kural verisi.
        labels_map (Dict[str, str]): Etiket haritası.

    Returns:
        Any: Hazırlanmış API değiştirme isteği.
    """
    ids: List[str] = [labels_map[n] for n in rule.get("labels_to_remove", []) if n in labels_map]
    
    if not ids:
        return None
        
    return service.users().messages().modify(
        userId="me", id=msg_id, body={"removeLabelIds": ids}
    )


def create_trash_request(service: Any, msg_id: str, rule: Dict[str, Any], labels_map: Dict[str, str]) -> Any:
    """Bir mesajı çöp kutusuna taşımak için API isteği oluşturur.

    Args:
        service (Any): Gmail API servisi.
        msg_id (str): Mesaj kimliği.
        rule (Dict[str, Any]): Kullanılmayan ancak imza uyumu için tutulan kural parametresi.
        labels_map (Dict[str, str]): Kullanılmayan ancak imza uyumu için tutulan harita.

    Returns:
        Any: Hazırlanmış API çöp kutusu isteği.
    """
    return service.users().messages().trash(userId="me", id=msg_id)


def delete_label(service: Any, label_name: str, labels_map: Dict[str, str], is_test: bool = True) -> bool:
    """Belirtilen bir Gmail etiketini kalıcı olarak siler.

    Args:
        service (Any): Gmail API servisi.
        label_name (str): Silinecek etiketin adı.
        labels_map (Dict[str, str]): Etiket haritası.
        is_test (bool): True ise sadece simülasyon yapar.

    Returns:
        bool: İşlem başarılıysa veya etiket zaten yoksa True.
    """
    label_id: Optional[str] = labels_map.get(label_name)
    
    if not label_id:
        log.info(f"✨ Etiket '{label_name}' sistemde bulunamadı.")
        return True

    if is_test:
        log.warning(f"[TEST] Etiket silinecekti: '{label_name}' (Kimlik: {label_id})")
        return True

    try:
        log.warning(f"[CANLI] Etiket siliniyor: '{label_name}'...")
        service.users().labels().delete(userId="me", id=label_id).execute()
        log.info(f"Etiket '{label_name}' başarıyla silindi.")
        return True
    except HttpError as e:
        if e.resp.status == 404:
            log.info(f"✨ Etiket '{label_name}' zaten silinmiş.")
            return True
        log.error(f"Etiket silme hatası '{label_name}': {e}")
        return False


def run_delete_label_task(config: Dict[str, Any]) -> None:
    """Yapılandırmada belirlenen etiketleri kilitli mekanizma ile kalıcı olarak siler.

    Args:
        config (Dict[str, Any]): Uygulama yapılandırma nesnesi.
    """
    if not _maintenance_lock.acquire(blocking=False):
        log.warning("⏳ Etiket silme işlemi şu an başka bir iş parçacığında devam ediyor.")
        return

    try:
        service: Optional[Any] = authenticate()
        if not service:
            log.error("Gmail servisi başlatılamadığı için işlem iptal edildi.")
            return

        settings: Dict[str, Any] = config.get("label_delete_settings", {})
        is_test: bool = settings.get("run_in_test_mode", True)
        labels_to_delete: List[str] = settings.get("labels_to_delete_permanently", [])

        if not labels_to_delete:
            log.info("Silinecek herhangi bir etiket tanımlanmamış.")
            return

        try:
            results: Dict[str, Any] = service.users().labels().list(userId='me').execute()
            existing_map: Dict[str, str] = {l['name']: l['id'] for l in results.get('labels', [])}
        except Exception as e:
            log.error(f"Güncel etiket listesi çekilemedi: {e}")
            return

        if not is_test:
            log.critical("!!! KRİTİK: CANLI ETİKET SİLME MODU AKTİF. 2 saniye içinde başlıyor...")
            time.sleep(2)

        name: str
        for name in labels_to_delete:
            delete_label(service, name, existing_map, is_test)
            
    finally:
        _maintenance_lock.release()


def run_cleanup_task(config: Dict[str, Any]) -> None:
    """Gelen kutusu etiket temizlik kurallarını güvenli şekilde çalıştırır.

    Args:
        config (Dict[str, Any]): Uygulama yapılandırma nesnesi.
    """
    if not _maintenance_lock.acquire(blocking=False):
        log.warning("⏳ Temizlik işlemi zaten devam ediyor, mükerrer işlem engellendi.")
        return
        
    try:
        service: Optional[Any] = authenticate()
        if not service:
            log.error("Gmail servisi başlatılamadı.")
            return
            
        settings: Dict[str, Any] = config.get("cleanup_mode_settings", {})
        is_test: bool = settings.get("run_in_test_mode", True)
        
        try:
            results: Dict[str, Any] = service.users().labels().list(userId='me').execute()
            existing_map: Dict[str, str] = {l['name']: l['id'] for l in results.get('labels', [])}
        except Exception as e:
            log.error(f"Etiket listesi alınamadı: {e}")
            return

        log.info("🧹 Temizlik işlemi başlatıldı...")
        run_rules_engine(service, settings, existing_map, is_test, create_cleanup_request)
        log.info("✅ Temizlik işlemi başarıyla tamamlandı.")
        
    finally:
        _maintenance_lock.release()


def run_trash_task(config: Dict[str, Any]) -> None:
    """Yapılandırmadaki kurallara göre e-postaları güvenli şekilde çöpe atar.

    Args:
        config (Dict[str, Any]): Uygulama yapılandırma nesnesi.
    """
    if not _maintenance_lock.acquire(blocking=False):
        log.warning("⏳ Çöpe atma işlemi zaten devam ediyor.")
        return
        
    try:
        service: Optional[Any] = authenticate()
        if not service:
            log.error("Gmail servisi başlatılamadı.")
            return
            
        settings: Dict[str, Any] = config.get("trash_mode_settings", {})
        is_test: bool = settings.get("run_in_test_mode", True)
        
        try:
            results: Dict[str, Any] = service.users().labels().list(userId='me').execute()
            existing_map: Dict[str, str] = {l['name']: l['id'] for l in results.get('labels', [])}
        except Exception as e:
            log.error(f"Etiket haritası yüklenemedi: {e}")
            return

        log.info("🗑️ Çöpe atma işlemi başlatıldı...")
        run_rules_engine(service, settings, existing_map, is_test, create_trash_request)
        log.info("✅ Çöpe atma işlemi tamamlandı.")
        
    finally:
        _maintenance_lock.release()