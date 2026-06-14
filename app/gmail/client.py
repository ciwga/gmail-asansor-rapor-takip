"""
Gmail API İstemcisi - Yaygın işlemleri hata yönetimi ile birlikte sarmalar.
"""

import time
import logging
from typing import List, Dict, Set, Any, Optional, Callable, cast

from googleapiclient.errors import HttpError  # type: ignore

from app.utils.logging import get_logger

log: logging.Logger = get_logger(__name__)

BATCH_SIZE_GET: int = 20
BATCH_SIZE_MODIFY: int = 40


def get_all_messages(service: Any, query: str) -> List[Dict[str, Any]]:
    """Belirtilen Gmail arama sorgusuna uyan tüm mesaj kimliklerini çeker.
    
    Sayfalama desteği ile tüm sonuçlar bitene kadar API'yi sorgular.

    Args:
        service (Any): Yetkilendirilmiş Gmail API servis nesnesi.
        query (str): Gmail arama sorgusu (örn: 'label:unread').

    Returns:
        List[Dict[str, Any]]: Mesaj kimliklerini ve thread kimliklerini içeren liste.
    """
    messages: List[Dict[str, Any]] = []
    page_token: Optional[str] = None

    while True:
        try:
            resp: Dict[str, Any] = service.users().messages().list(
                userId="me", q=query, maxResults=500, pageToken=page_token
            ).execute()
            
            messages.extend(resp.get("messages", []))
            
            next_token_raw: Any = resp.get("nextPageToken")
            page_token = str(next_token_raw) if next_token_raw else None
            
            if not page_token:
                break
        except Exception as e:
            log.error(f"Mesajlar listelenirken hata oluştu: {e}")
            break

    return messages


def ensure_labels(service: Any, label_names: Set[str]) -> Dict[str, str]:
    """Verilen isimlere sahip etiketlerin kimliklerini döndürür, yoksa oluşturur.

    Args:
        service (Any): Gmail API servis nesnesi.
        label_names (Set[str]): Kontrol edilecek veya oluşturulacak etiket isimleri.

    Returns:
        Dict[str, str]: Etiket adı ve etiket kimliği eşleşme haritası.
    """
    try:
        results: Dict[str, Any] = service.users().labels().list(userId="me").execute()
        existing_list: List[Dict[str, Any]] = results.get("labels", [])
        existing: Dict[str, str] = {str(l["name"]): str(l["id"]) for l in existing_list}
    except Exception as e:
        log.error(f"Etiket listesi alınamadı: {e}")
        return {}

    label_map: Dict[str, str] = {}
    created: int = 0
    
    for name in label_names:
        safe_name: str = str(name)
        if not safe_name:
            continue
            
        if safe_name in existing:
            label_map[safe_name] = existing[safe_name]
        else:
            try:
                result: Dict[str, str] = service.users().labels().create(
                    userId="me",
                    body={
                        "name": safe_name,
                        "labelListVisibility": "labelShow",
                        "messageListVisibility": "show",
                    },
                ).execute()
                label_map[safe_name] = result["id"]
                created += 1
            except Exception as e:
                if "already exists" in str(e).lower():
                    try:
                        results2: Dict[str, Any] = service.users().labels().list(userId="me").execute()
                        fallback_list: List[Dict[str, Any]] = results2.get("labels", [])
                        for l in fallback_list:
                            if str(l.get("name", "")) == safe_name:
                                label_map[safe_name] = str(l["id"])
                                break
                    except Exception:
                        pass
                else:
                    log.error(f"Etiket oluşturulamadı '{safe_name}': {e}")

    if created:
        log.info(f"🏷️ {created} yeni etiket oluşturuldu")

    return label_map


def batch_fetch_messages(
    service: Any, message_ids: List[str], callback: Callable[[str, Any, Any], None]
) -> None:
    """Mesaj içeriklerini toplu paketler halinde çeker.

    Args:
        service (Any): Gmail API servis nesnesi.
        message_ids (List[str]): Çekilecek mesajların kimlik listesi.
        callback (Callable[[str, Any, Any], None]): 
            Her mesaj çekildiğinde çalıştırılacak katı tanımlı (strict-typed) fonksiyon.
    """
    i: int
    for i in range(0, len(message_ids), BATCH_SIZE_GET):
        batch: Any = service.new_batch_http_request()
        
        mid: str
        for mid in message_ids[i : i + BATCH_SIZE_GET]:
            batch.add(
                service.users().messages().get(userId="me", id=mid, format="full"),
                callback=callback,
            )
            
        try:
            batch.execute()
            time.sleep(1)
        except Exception as e:
            log.error(f"Toplu veri çekme hatası: {e}")
            time.sleep(2)


def batch_modify(service: Any, modifications: List[Dict[str, Any]]) -> None:
    """Mesaj etiketlerini paketler halinde günceller ve hız limitine karşı yeniden dener.

    Args:
        service (Any): Gmail API servis nesnesi.
        modifications (List[Dict[str, Any]]): Mesaj kimliğini ve değiştirme gövdesini içeren liste.
    """
    if not modifications:
        return

    failed: List[Dict[str, Any]] = []

    def _cb(request_id: str, response: Any, exception: Any) -> None:
        """Her bir değiştirme isteği için geri çağırma fonksiyonu."""
        log.debug(f"Toplu etiket modifikasyonu (İstek: {request_id}) yanıtı: {response}")
        
        if exception:
            if isinstance(exception, HttpError) and cast(Any, exception).resp.status == 429:
                failed.append(modifications[int(request_id)])
            else:
                log.error(f"Etiket uygulama hatası (İstek kimliği {request_id}): {exception}")

    batch_size: int = 10
    i: int
    for i in range(0, len(modifications), batch_size):
        chunk: List[Dict[str, Any]] = modifications[i:i + batch_size]
        batch: Any = service.new_batch_http_request(callback=_cb)
        
        j: int
        mod: Dict[str, Any]
        for j, mod in enumerate(chunk):
            msg_id_val: str = str(mod.get("id", ""))
            batch.add(
                service.users().messages().modify(
                    userId="me", id=msg_id_val, body=mod.get("body", {})
                ),
                request_id=str(i + j),
            )
            
        try:
            batch.execute()
        except Exception as e:
            log.error(f"Toplu etiket güncelleme hatası: {e}")
            failed.extend(chunk)
            
        time.sleep(0.5)

    attempt: int
    for attempt in range(1, 4):
        if not failed:
            break
            
        retry_list: List[Dict[str, Any]] = failed[:]
        failed = []
        wait: int = attempt * 3
        
        log.info(f"🔄 Hız limiti denemesi #{attempt}: {len(retry_list)} e-posta ({wait}s bekleniyor)...")
        time.sleep(wait)

        for mod in retry_list:
            msg_id_retry: str = str(mod.get("id", ""))
            try:
                service.users().messages().modify(
                    userId="me", id=msg_id_retry, body=mod.get("body", {})
                ).execute()
                time.sleep(0.3)
            except HttpError as e:
                if cast(Any, e).resp.status == 429:
                    failed.append(mod)
                else:
                    log.error(f"Etiket hatası (Kimlik {msg_id_retry}): {e}")
            except Exception as e:
                log.error(f"Etiket hatası (Kimlik {msg_id_retry}): {e}")

    if failed:
        log.warning(f"⚠️ {len(failed)} e-postaya hız limiti nedeniyle etiket uygulanamadı.")