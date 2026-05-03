"""Çok kanallı e-posta işleme ve iş parçacığı yönetimi."""

import base64
import html
import os
import queue
import re
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Set, Tuple

from app.core.appointments import parse_appointment
from app.core.database import Database
from app.downloaders.engine import download, find_download_url
from app.gmail.client import batch_modify, BATCH_SIZE_MODIFY
from app.parsers.registry import detect_and_parse
from app.utils.logging import get_logger
from app.utils.patterns import MMO_BINA_ID_PATTERN, MMO_BASVURU_ID_PATTERN
from app.utils.text import to_lower_tr, sanitize_filename

log: Any = get_logger(__name__)


def get_pdf_attachments(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """E-posta parçaları arasından PDF eklerini özyineli olarak bulur.
    
    Args:
        parts (List[Dict[str, Any]]): E-posta payload parçaları.
        
    Returns:
        List[Dict[str, Any]]: Bulunan PDF eklerinin listesi.
    """
    atts: List[Dict[str, Any]] = []
    
    if not parts:
        return atts
        
    for p in parts:
        mime: str = p.get("mimeType", "").lower()
        fname: str = p.get("filename", "").lower()
        
        if mime == "application/pdf" or fname.endswith(".pdf"):
            atts.append(p)
            
        if p.get("parts"):
            atts.extend(get_pdf_attachments(p["parts"]))
            
    return atts


def extract_plain_text(payload: Dict[str, Any]) -> str:
    """E-posta payload'undan düz metni güvenli bir şekilde çıkarır.
    
    HTML içerik gelirse etiketleri temizler, bağlantıları korur ve blok etiketlerini
    satır sonlarına dönüştürerek metinlerin birbirine yapışmasını önler.
    
    Args:
        payload (Dict[str, Any]): E-posta veri yapısı.
        
    Returns:
        str: Temizlenmiş ve çözülmüş metin içeriği.
    """
    mime: str = payload.get("mimeType", "")
    data: str
    
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
            except Exception as e:
                log.debug(f"Düz metin decode hatası: {e}")
                
    for part in payload.get("parts", []):
        result: str = extract_plain_text(part)
        if result:
            return result
            
    if mime == "text/html":
        data = payload.get("body", {}).get("data", "")
        if data:
            try:
                raw: str = base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
                raw = re.sub(
                    r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
                    r'\2 \1', raw, flags=re.IGNORECASE | re.DOTALL
                )
                raw = re.sub(r'<(br|/?div|/?p|/?tr|/?table|/?h\d)[^>]*>', '\n', raw, flags=re.IGNORECASE)
                text: str = re.sub(r"<[^>]+>", " ", raw)
                return html.unescape(text)
            except Exception as e:
                log.debug(f"HTML decode hatası: {e}")
                
    data = payload.get("body", {}).get("data", "")
    if data:
        try:
            return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
        except Exception:
            pass
            
    return ""


def _hdr(headers: List[Dict[str, str]], name: str) -> str:
    """Belirtilen e-posta başlığını arar ve değerini döndürür.

    Args:
        headers (List[Dict[str, str]]): Başlık listesi.
        name (str): Aranacak başlık adı (örn: 'From').

    Returns:
        str: Başlık değeri veya bulunamazsa boş string.
    """
    n: str = name.lower()
    return next((h["value"] for h in headers if h["name"].lower() == n), "")


def _check_date(result: Dict[str, Any], config: Dict[str, Any]) -> bool:
    """Rapor tarihinin yapılandırmadaki limitlere göre güncel olup olmadığını kontrol eder.

    Args:
        result (Dict[str, Any]): Rapor verilerini içeren sözlük.
        config (Dict[str, Any]): Uygulama yapılandırması.

    Returns:
        bool: Rapor kabul edilebilir tarihteyse True, çok eskiyse False.
    """
    try:
        ds: str = result.get("inspection_date", "")
        label: str = result.get("label_color", "")
        
        if not ds or not label or ds in ("-", "N/A"):
            return True
            
        days_map: Dict[str, Any] = config.get("search_settings", {}).get("label_specific_days_before", {})
        key: Optional[str] = next((k for k in days_map if label in k), None)
        
        if key:
            limit: Any = days_map[key]
            if isinstance(limit, int) and limit > 0:
                pdf_date: datetime = datetime.strptime(ds.replace("/", "."), "%d.%m.%Y")
                if pdf_date < datetime.now() - timedelta(days=limit):
                    log.warning(f"⚠️ [TARİH LİMİTİ] Bu rapor çok eski, işlenmeyecek: {result.get('building_name')} ({ds}, limit: {limit} gün)")
                    return False
    except Exception as e:
        log.debug(f"Tarih kontrolü başarısız: {e}")
        
    return True


def _label_body(
    config: Dict[str, Any],
    source: Optional[Dict[str, str]],
    result: Dict[str, Any],
    msg: Dict[str, Any],
    label_map: Dict[str, str]
) -> Dict[str, Any]:
    """Gmail için etiketleme gövdesini hazırlar.

    İşlenen raporun sonucuna (renk, kaynak vb.) göre hangi etiketlerin ekleneceğini
    veya kaldırılacağını (okundu, inbox vb.) belirler.

    Args:
        config (Dict[str, Any]): Uygulama yapılandırması.
        source (Optional[Dict[str, str]]): E-posta kaynağı tanımı.
        result (Dict[str, Any]): İşleme sonucu verileri.
        msg (Dict[str, Any]): Orijinal Gmail mesaj verisi.
        label_map (Dict[str, str]): Etiket adı -> ID eşleşme haritası.

    Returns:
        Dict[str, Any]: addLabelIds ve removeLabelIds içeren Gmail API isteği gövdesi.
    """
    search_cfg: Dict[str, Any] = config.get("search_settings", {})
    q_cfg: Dict[str, Any] = config.get("quarantine_settings", {})
    q_lid: Optional[str] = label_map.get(q_cfg.get("quarantine_label_name", ""))

    resolver: Any = config.get("_label_resolver")

    body: Dict[str, List[str]] = {"addLabelIds": [], "removeLabelIds": []}
    
    if search_cfg.get("mark_as_read_after_processing"):
        body["removeLabelIds"].append("UNREAD")
    if search_cfg.get("archive_after_processing"):
        body["removeLabelIds"].append("INBOX")
    if q_lid and q_lid in msg.get("labelIds", []):
        body["removeLabelIds"].append(q_lid)

    if source:
        src_name: str = source.get("label_name", "")
        full_name: str = resolver.source_label(src_name) if resolver else src_name
        lid: Optional[str] = label_map.get(full_name)
        if lid:
            body["addLabelIds"].append(lid)

    color: str = result.get("label_color", "")
    if color:
        if resolver:
            color_name: str = resolver.color_label(color)
            lid = label_map.get(color_name)
            if lid:
                body["addLabelIds"].append(lid)
        else:
            for suffix in [" Etiketli", ""]:
                lid = label_map.get(color + suffix)
                if lid:
                    body["addLabelIds"].append(lid)
                    break

    if not body["addLabelIds"]:
        del body["addLabelIds"]
    if not body["removeLabelIds"]:
        del body["removeLabelIds"]
        
    return body


def _worker(
    job_q: queue.Queue,
    result_q: queue.Queue,
    config: Dict[str, Any],
    processed_ids: Set[str],
    mmo_ids: Set[Tuple[str, str]],
    lock: threading.Lock,
    service: Any,
    db: Any
) -> None:
    """İş parçacığı ana döngüsü.
    
    E-postaları sırayla alır, filtreler, indirme işlemlerini yapar ve ayrıştırır.
    Lock mekanizması sadece paylaşılan kümelere erişim için kullanılır.

    Args:
        job_q (queue.Queue): İşlenecek mesajların bulunduğu kuyruk.
        result_q (queue.Queue): Sonuçların gönderileceği kuyruk.
        config (Dict[str, Any]): Uygulama yapılandırması.
        processed_ids (Set[str]): İşlenmiş rapor UUID'lerini takip eden küme.
        mmo_ids (Set[Tuple[str, str]]): MMO bazlı mükerrer kontrol kümesi.
        lock (threading.Lock): Paylaşılan kaynaklar için iş parçacığı kilidi.
        service (Any): Gmail API servis istemcisi.
        db (Any): Veritabanı erişim nesnesi.
    """
    search_cfg: Dict[str, Any] = config.get("search_settings", {})
    ex_kw: List[str] = [to_lower_tr(k) for k in search_cfg.get("exceptional_keywords", [])]
    ex_snd: List[str] = [to_lower_tr(s) for s in search_cfg.get("exceptional_senders", [])]
    label_map: Dict[str, str] = config.get("_internal_labels_map", {})
    dl_folder: str = config.get("paths", {}).get("download_folder", "data/raporlar")
    force: bool = config.get("database_settings", {}).get("force_reprocess_all", False)
    skip_dup: bool = config.get("database_settings", {}).get("skip_duplicate_downloads", True)
    resolver: Any = config.get("_label_resolver")
    appt_label_name: str = resolver.appointment_label() if resolver else config.get("appointment_email_settings", {}).get("randevu_label_name", "Randevu")

    while True:
        msg: Optional[Dict[str, Any]] = job_q.get()
        if msg is None:
            break

        mid: str = msg["id"]
        try:
            hdrs: List[Dict[str, str]] = msg.get("payload", {}).get("headers", [])
            sender: str = to_lower_tr(_hdr(hdrs, "From"))
            subject: str = to_lower_tr(_hdr(hdrs, "Subject"))
            sender_orig: str = _hdr(hdrs, "From")
            subject_orig: str = _hdr(hdrs, "Subject")
            
            date_ms: int = int(msg.get("internalDate", 0))
            email_date_str: str = datetime.fromtimestamp(date_ms / 1000.0).strftime('%d.%m.%Y %H:%M')
            
            search_hint: str = f"Tarih: {email_date_str} | Gönderen: {sender_orig} | Konu: {subject_orig}"
            
            sender_clean: str = sender_orig.split('<')[0].strip() or sender_orig
            msg_tag: str = f"{sender_clean} | Konu: {subject_orig[:45]}"
            if len(subject_orig) > 45: 
                msg_tag += "..."

            if any(s in sender for s in ex_snd):
                log.info(f"🚫 [FİLTRE] İstenmeyen gönderici, atlandı: {msg_tag}")
                job_q.task_done()
                continue

            content: str = extract_plain_text(msg["payload"])
            
            content = content.replace('*', '')
            content = re.sub(r'(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})', r'\1.\2.\3', content)
            content_lower: str = to_lower_tr(content)
            
            kw: Optional[str] = next((k for k in ex_kw if k in subject or k in content_lower), None)
            if kw:
                log.info(f"🚫 [FİLTRE] Hariç tutulan kelime ('{kw}'), atlandı: {msg_tag}")
                job_q.task_done()
                continue

            source: Optional[Dict[str, str]] = next((s for s in config.get("sources", []) if s["query"] in sender), None)
            proc: str = source.get("processor", "") if source else ""
            appt_cfg: Dict[str, Any] = config.get("appointment_email_settings", {})

            is_appt_source: bool = (proc == "appointment" or (proc == "optimaldenge" and "randevu" in subject))
            appt_parsed: bool = False

            if is_appt_source and appt_cfg.get("enabled", True):
                log.debug(f"📆 [ANALİZ] Randevu/Bilgilendirme içeriği taranıyor: {msg_tag}")
                appts: Optional[List[Dict[str, Any]]] = parse_appointment(content, subject_orig, sender_orig, date_ms)
                
                if appts:
                    for appt in appts:
                        uid: str = appt.get("uuid", appt.get("file_name"))
                        
                        if appt_cfg.get("filter_past_dates", True):
                            try:
                                if datetime.strptime(appt.get("inspection_date", ""), "%d.%m.%Y").date() < datetime.now().date():
                                    log.info(f"⏭️ [TARİH FİLTRESİ] Geçmiş tarihli randevu olduğu için atlandı: {appt.get('building_name', '?')} ({appt.get('inspection_date')})")
                                    result_q.put(("skipped_success", mid))
                                    appt_parsed = True
                                    continue
                            except (ValueError, TypeError):
                                pass
                        
                        with lock:
                            if uid in processed_ids and not force:
                                log.info(f"⏭️ [MÜKERRER] Zaten veritabanında kayıtlı, atlandı: {appt.get('building_name', '?')} ({appt.get('inspection_date')})")
                                result_q.put(("skipped_success", mid))
                                appt_parsed = True
                                continue
                            processed_ids.add(uid)
                            
                        mod: Dict[str, Any] = _label_body(config, source, appt, msg, label_map)
                        rl: Optional[str] = label_map.get(appt_label_name)
                        if rl:
                            mod.setdefault("addLabelIds", []).append(rl)
                        
                        log.info(f"✅ [RANDEVU EKLENDİ] {appt.get('building_name','?')} | Tarih: {appt.get('inspection_date','?')}")
                        result_q.put(("success", mid, appt, mod, "randevu"))
                        appt_parsed = True

                if appt_parsed:
                    job_q.task_done()
                    continue
                else:
                    log.debug(f"⚠️ [ANALİZ] İçerikte tarih/asansör no bulunamadı, PDF raporu olarak aranacak: {msg_tag}")
            
            fpaths: List[str] = []
            status: str = "failed"

            if source and proc and not is_appt_source:
                if proc == "mmo":
                    bid_m: Optional[re.Match] = MMO_BINA_ID_PATTERN.search(content)
                    bas_m: Optional[re.Match] = MMO_BASVURU_ID_PATTERN.search(content)
                    
                    if bid_m and bas_m:
                        key: Tuple[str, str] = (bid_m.group(1), bas_m.group(1))
                        skip: bool = False
                        
                        if skip_dup:
                            with lock:
                                if key in mmo_ids:
                                    skip = True
                                else:
                                    mmo_ids.add(key)
                                    
                        if skip:
                            log.info(f"⏭️ [MÜKERRER] Aynı başvuru aynı işlem döngüsünde çekilmiş, atlanıyor: Bina {key[0]}")
                            job_q.task_done()
                            continue
                        
                        log.debug(f"⬇️ [{proc.upper()}] Rapor linki oluşturuluyor: {msg_tag}")
                        fpaths, status = download("mmo", dl_folder, bina_id=bid_m.group(1), basvuru_id=bas_m.group(1))
                    else:
                        log.debug(f"ℹ️ [{proc.upper()}] Rapor bağlantısı/ID'leri bulunamadı, randevu olabilir: {msg_tag}")
                        status = "failed"
                else:
                    url: Optional[str] = find_download_url(content, proc)
                    if url:
                        log.debug(f"⬇️ [{proc.upper()}] E-postada indirme butonu bulundu, işlem başlatıldı: {msg_tag}")
                        fpaths, status = download(proc, dl_folder, url=url)
                    else:
                        log.debug(f"❌ [{proc.upper()}] E-postada tıklanabilir bir buton veya link bulunamadı: {msg_tag}")
                        status = "failed"

                if status == "downloaded":
                    log.debug(f"✅ [{proc.upper()}] Rapor indirildi ({len(fpaths)} dosya).")
                elif status == "skipped":
                    log.debug(f"📂 [{proc.upper()}] Rapor dosyası yerelde zaten mevcut.")

            if status not in ("downloaded", "skipped"):
                pdf_parts: List[Dict[str, Any]] = get_pdf_attachments(msg["payload"].get("parts", []))
                real_atts: List[Dict[str, Any]] = [p for p in pdf_parts if p.get("body", {}).get("attachmentId")]
                
                if real_atts:
                    log.debug(f"📎 [E-POSTA EKİ] E-postada doğrudan eklenmiş PDF dosyaları bulundu, indiriliyor: {msg_tag}")
                    for part in real_atts:
                        att_id: str = part["body"]["attachmentId"]
                        try:
                            att: Dict[str, Any] = service.users().messages().attachments().get(
                                userId="me", messageId=mid, id=att_id).execute()
                            data: bytes = base64.urlsafe_b64decode(att["data"])
                            fname: str = part.get("filename") or f"ek_{mid}.pdf"
                            fpath: str = os.path.join(dl_folder, sanitize_filename(fname))
                            
                            os.makedirs(dl_folder, exist_ok=True)
                            with open(fpath, "wb") as f:
                                f.write(data)

                            result: Any = detect_and_parse(fpath, db=db)
                            
                            if result and _check_date(result.to_dict(), config):
                                rdict: Dict[str, Any] = result.to_dict()
                                uid = result.unique_key
                                
                                with lock:
                                    already: bool = uid in processed_ids
                                    
                                if already and not force:
                                    log.info(f"⏭️ [MÜKERRER] Rapor zaten sistemde kayıtlı: {uid}")
                                    result_q.put(("skipped_success", mid))
                                else:
                                    if not force:
                                        processed_ids.add(uid)
                                    mod = _label_body(config, source, rdict, msg, label_map)
                                    log.info(f"✅ [RAPOR EKLENDİ (EK)] {result.building_name}")
                                    result_q.put(("success", mid, rdict, mod))
                        except Exception as e:
                            log.error(f"Ek (Attachment) indirme hatası ({mid}): {e}")
                            
                    job_q.task_done()
                    continue

            if status in ("downloaded", "skipped") and fpaths:
                for fpath in fpaths:
                    result = detect_and_parse(fpath, db=db)
                    if result and _check_date(result.to_dict(), config):
                        rdict = result.to_dict()
                        uid = result.unique_key
                        with lock:
                            already = uid in processed_ids
                            
                        if already and not force:
                            log.info(f"⏭️ [MÜKERRER] Rapor zaten sistemde kayıtlı: {uid}")
                            result_q.put(("skipped_success", mid))
                        else:
                            if not force:
                                processed_ids.add(uid)
                            mod = _label_body(config, source, rdict, msg, label_map)
                            log.info(f"✅ [RAPOR EKLENDİ] {result.building_name}")
                            result_q.put(("success", mid, rdict, mod))
                    else:
                        log.warning(f"⚠️ [PDF OKUMA HATASI] Desteklenmiyor veya tarihi çok eski: {os.path.basename(fpath)}")
                        result_q.put(("fail", mid))
            else:
                if not is_appt_source and appt_cfg.get("enabled", True):
                    appts = parse_appointment(content, subject_orig, sender_orig, date_ms)
                    if appts:
                        for appt in appts:
                            uid = appt.get("uuid", appt.get("file_name"))
                            if appt_cfg.get("filter_past_dates", True):
                                try:
                                    if datetime.strptime(appt.get("inspection_date", ""), "%d.%m.%Y").date() < datetime.now().date():
                                        log.info(f"⏭️ [TARİH FİLTRESİ] Geçmiş tarihli randevu olduğu için atlandı: {appt.get('building_name', '?')} ({appt.get('inspection_date')})")
                                        result_q.put(("skipped_success", mid))
                                        continue
                                except (ValueError, TypeError):
                                    pass
                                    
                            with lock:
                                if uid in processed_ids and not force:
                                    log.info(f"⏭️ [MÜKERRER] Zaten veritabanında kayıtlı: {appt.get('building_name', '?')} ({appt.get('inspection_date')})")
                                    result_q.put(("skipped_success", mid))
                                    continue
                                processed_ids.add(uid)
                                
                            mod = _label_body(config, source, appt, msg, label_map)
                            rl = label_map.get(appt_label_name)
                            if rl:
                                mod.setdefault("addLabelIds", []).append(rl)
                                
                            log.info(f"✅ [RANDEVU KURTARILDI] {appt.get('building_name','?')} | {appt.get('inspection_date','?')}")
                            result_q.put(("success", mid, appt, mod, "randevu"))
                            
                        job_q.task_done()
                        continue
                
                if source:
                    if is_appt_source:
                        log.info(f"ℹ️ [BİLGİLENDİRME] Bu bir duyuru mesajı (Tarih/Asansör no eksik), atlandı.\n"
                                 f"   🔍 GMAIL'DE BULMAK İÇİN -> {search_hint}")
                        result_q.put(("skipped_success", mid))
                    else:
                        log.warning(f"❌ [BAŞARISIZ] E-posta içeriğinden ne PDF ne de geçerli bir randevu bulunabildi.\n"
                                    f"   🔍 GMAIL'DE BULMAK İÇİN -> {search_hint}")
                        result_q.put(("fail", mid))

        except Exception as e:
            log.error(f"Worker iç hatası ({mid}): {e}", exc_info=True)

        job_q.task_done()


def process_messages(
    messages: List[Dict[str, Any]],
    service: Any,
    config: Dict[str, Any],
    db: Any,
    proc_map: Dict[str, Dict[str, Any]],
    proc_ids: Set[str],
    mmo_ids: Set[Tuple[str, str]],
    resolution_filter: Optional[Any] = None,
    num_workers: int = 10,
    force_ids: Optional[Set[str]] = None
) -> List[Dict[str, Any]]:
    """E-postaları paralel iş parçacıklarıyla işler ve sonuçları toplar.

    Args:
        messages (List[Dict[str, Any]]): İşlenecek mesaj özet listesi.
        service (Any): Gmail API servis nesnesi.
        config (Dict[str, Any]): Uygulama yapılandırması.
        db (Any): Veritabanı yönetim nesnesi.
        proc_map (Dict[str, Dict[str, Any]]): Mevcut işleme verileri haritası.
        proc_ids (Set[str]): İşlenmiş rapor kimlikleri.
        mmo_ids (Set[Tuple[str, str]]): MMO başvuru takip kümesi.
        resolution_filter (Optional[Any]): Akıllı çözümleme filtresi nesnesi.
        num_workers (int): Başlatılacak iş parçacığı sayısı.
        force_ids (Optional[Set[str]]): Zorunlu olarak tekrar işlenecek mesaj kimlikleri.

    Returns:
        List[Dict[str, Any]]: İşlem sonucu üretilen yeni raporların listesi.
    """
    from app.gmail.client import batch_fetch_messages

    q_cfg: Dict[str, Any] = config.get("quarantine_settings", {})
    q_en: bool = q_cfg.get("enabled", False)
    q_max: int = q_cfg.get("max_fail_count", 5)
    q_cut: datetime = datetime.now() - timedelta(days=q_cfg.get("quarantine_days", 1))
    force: bool = config.get("database_settings", {}).get("force_reprocess_all", False)
    force_set: Set[str] = force_ids or set()

    to_fetch: List[str] = []
    skipped_by_db: int = 0
    
    for m in messages:
        mid: str = m["id"]
        if mid in force_set:
            to_fetch.append(mid)
            continue
            
        data: Optional[Dict[str, Any]] = proc_map.get(mid)
        if not force:
            if data and data.get("fail_count", 0) == 0 and data.get("last_fail_time") is None:
                skipped_by_db += 1
                continue
            if q_en and data and data.get("fail_count", 0) >= q_max:
                if data.get("last_fail_time") and datetime.fromisoformat(data["last_fail_time"]) > q_cut:
                    skipped_by_db += 1
                    continue
        to_fetch.append(mid)

    if skipped_by_db:
        log.info(f"📊 [ÖN FİLTRE] {skipped_by_db} adet e-posta veritabanında başarıyla tamamlanmış görünüyor (Atlandı).")
    
    log.info(f"⚙️ [MOTOR] Kalan {len(to_fetch)} adet e-posta işlem sırasına alınıyor... (Zorla Tekrar İşle: {force})")

    if not to_fetch:
        log.info("İşlenecek yeni e-posta yok.")
        return []

    log.info(f"📥 [GMAIL API] {len(to_fetch)} adet e-postanın içerikleri Google'dan indiriliyor...")
    full_msgs: Dict[str, Dict[str, Any]] = {}

    def _cb(rid: str, res: Any, exc: Any) -> None:
        if exc:
            log.warning(f"İçerik çekme hatası ({rid}): {exc}")
        elif res:
            full_msgs[res["id"]] = res

    batch_fetch_messages(service, to_fetch, _cb)

    final_msgs: List[Dict[str, Any]] = []
    skipped: int = 0
    
    if resolution_filter:
        log.info("🛡️ [AKILLI FİLTRE] Binaların son durumları kontrol ediliyor (Yeşil/Mavi olanların eski raporları elenecek)...")
        for mid, msg in full_msgs.items():
            hdrs: List[Dict[str, str]] = msg.get("payload", {}).get("headers", [])
            subj: str = _hdr(hdrs, "Subject")
            sndr: str = _hdr(hdrs, "From")
            snip: str = msg.get("snippet", "")
            d: int = int(msg.get("internalDate", 0))
            if resolution_filter.is_resolved(subj, snip, sndr, d):
                skipped += 1
            else:
                final_msgs.append(msg)
        if skipped:
            log.info(f"🛡️ [AKILLI FİLTRE] {skipped} adet eski e-posta 'bina durumu zaten çözülmüş' kabul edilerek atlandı.")
    else:
        final_msgs = list(full_msgs.values())

    if not final_msgs:
        log.info("Filtreleme sonrası işlenecek e-posta kalmadı.")
        return []

    log.info(f"🚀 [SİSTEM] {num_workers} adet İş Parçacığı (Worker) görevlendiriliyor ({len(final_msgs)} e-posta için)...")
    job_q: queue.Queue = queue.Queue()
    res_q: queue.Queue = queue.Queue()
    lock: threading.Lock = threading.Lock()

    threads: List[threading.Thread] = []
    for _ in range(num_workers):
        t: threading.Thread = threading.Thread(
            target=_worker,
            args=(job_q, res_q, config, proc_ids, mmo_ids, lock, service, db),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for msg in final_msgs:
        job_q.put(msg)
    job_q.join()

    for _ in range(num_workers):
        job_q.put(None)
    for t in threads:
        t.join(timeout=5)

    new_results: List[Dict[str, Any]] = []
    modifications: List[Dict[str, Any]] = []
    success_emails: List[Tuple[str, str]] = []
    success_reports: List[str] = []
    fail_emails: List[str] = []
    seen_mods: Set[str] = set()

    while not res_q.empty():
        item: Tuple = res_q.get()
        if item[0] == "success":
            mid = item[1]
            result = item[2]
            mod = item[3]
            etype: str = item[4] if len(item) > 4 else "normal"
            new_results.append(result)
            success_emails.append((mid, etype))
            success_reports.append(result.get("uuid", result.get("file_name")))
            if mod and mid not in seen_mods:
                modifications.append({"id": mid, "body": mod})
                seen_mods.add(mid)
        elif item[0] == "skipped_success":
            success_emails.append((item[1], "normal"))
        elif item[0] == "fail":
            fail_emails.append(item[1])

    if modifications:
        log.info(f"🏷️ [GMAIL API] Başarıyla tamamlanan {len(modifications)} e-postanın etiketleri güncelleniyor...")
        batch_modify(service, modifications)

    for mid, etype in set(success_emails):
        db.mark_email_success(mid, etype)
    for rid in set(success_reports):
        db.add_report(rid)
    for mid in set(fail_emails):
        db.increment_fail(mid)

    return new_results