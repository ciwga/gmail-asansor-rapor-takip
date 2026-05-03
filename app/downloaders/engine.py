"""
İndirme motoru: Profil dosyasını okur ve her sağlayıcı için uygun indirme stratejisini yürütür.

Bir web sitesinin yapısı değiştiğinde, Python kodunu değiştirmek yerine 
yalnızca profil dosyasını düzenlemek yeterlidir.
"""

import json
import logging
import os
import re
import uuid
import html
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app.downloaders.common import (
    save_pdf, is_pdf_response, DEFAULT_HEADERS, DEFAULT_TIMEOUT,
)
from app.utils.text import sanitize_filename
from app.utils.logging import get_logger
from app.paths import paths

log: logging.Logger = get_logger(__name__)

_profiles: Optional[Dict[str, Any]] = None


def _load_profiles() -> Dict[str, Any]:
    """Kazıma profillerini yükler ve ilk çağrıdan sonra önbelleğe alır.
    
    Returns:
        Dict[str, Any]: Yüklenen profil verilerini içeren sözlük.
    """
    global _profiles
    if _profiles is not None:
        return _profiles

    profile_path: Path = paths.SCRAPING_PROFILES
    
    if not profile_path.exists():
        log.warning(f"scraping_profiles.json bulunamadı.")
        assert "Scraping profili olmadan sistem çalışamaz."
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            data: Dict[str, Any] = json.load(f)
        _profiles = {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        log.error(f"Profil yükleme hatası: {e}")
        _profiles = {}
        
    return _profiles


def reload_profiles() -> None:
    """Profilleri zorla yeniden yükler."""
    global _profiles
    _profiles = None
    _load_profiles()


def find_download_url(content: str, processor: str) -> Optional[str]:
    """E-posta gövdesinde işlemci profiline uygun bir indirme bağlantısı arar.
    
    HTML varlıklarını çözer ve düzenli ifade ile bağlantıyı ayıklar.

    Args:
        content (str): E-posta metin içeriği.
        processor (str): Kullanılacak işlemci profil anahtarı.

    Returns:
        Optional[str]: Bulunan bağlantı veya bulunamazsa None.
    """
    profiles: Dict[str, Any] = _load_profiles()
    profile: Optional[Dict[str, Any]] = profiles.get(processor)
    
    if not profile or "url_pattern" not in profile:
        return None

    clean: str = html.unescape(content)
    clean = re.sub(r'<(https?://[^>]+)>', r' \1 ', clean)

    m: Optional[re.Match] = re.search(profile["url_pattern"], clean)
    if m:
        url: str = m.group(0)
        return html.unescape(url)

    log.debug(f"URL bulunamadı ({processor}): pattern={profile['url_pattern'][:50]}...")
    return None


def download(processor: str, folder: str, **kwargs: Any) -> Tuple[List[str], str]:
    """Belirtilen işlemci profilini kullanarak PDF dosyalarını indirir.

    Args:
        processor (str): Profil anahtarı.
        folder (str): Hedef indirme klasörü.
        **kwargs (Any): Ek veriler.

    Returns:
        Tuple[List[str], str]: İndirilen dosya yolları listesi ve durum bilgisi.
    """
    profiles: Dict[str, Any] = _load_profiles()
    profile: Optional[Dict[str, Any]] = profiles.get(processor)

    if not profile:
        log.warning(f"İşlemci için kazıma profili bulunamadı: {processor}")
        return [], "failed"

    strategy: str = profile.get("type", "")

    try:
        if strategy == "direct_download":
            return _download_direct(profile, folder, kwargs.get("url", ""))
        elif strategy == "aspnet_form":
            return _download_aspnet_form(profile, folder, kwargs.get("url", ""))
        elif strategy == "mmo_multi_step":
            return _download_mmo(profile, folder, kwargs)
        elif strategy == "html_scrape_download":
            return _download_html_scrape(profile, folder, kwargs.get("url", ""))
        else:
            log.error(f"Bilinmeyen indirme stratejisi: {strategy}")
            return [], "failed"
    except Exception as e:
        log.error(f"İndirme hatası ({processor}): {e}")
        return [], "failed"


def _download_direct(
    profile: Dict[str, Any], folder: str, url: str
) -> Tuple[List[str], str]:
    """Doğrudan bağlantı üzerinden PDF indirme stratejisi.

    Args:
        profile (Dict[str, Any]): Profil verileri.
        folder (str): Hedef klasör.
        url (str): İndirme bağlantısı.

    Returns:
        Tuple[List[str], str]: İndirme sonucu.
    """
    if not url:
        return [], "failed"

    timeout: int = profile.get("timeout", DEFAULT_TIMEOUT)
    try:
        r: requests.Response = requests.get(url, stream=True, headers=DEFAULT_HEADERS, timeout=timeout)
        r.raise_for_status()

        if is_pdf_response(r):
            fname: str = url.split("/")[-1] or f"download_{uuid.uuid4().hex[:8]}.pdf"
            path: Optional[str]
            status: str
            path, status = save_pdf(r, fname, folder)
            return ([path] if path else []), status
    except Exception:
        pass

    fname_from_url: str = url.split("/")[-1].split("?")[0] if "/" in url else ""
    if fname_from_url:
        safe: str = sanitize_filename(fname_from_url)
        if not safe.lower().endswith(".pdf"):
            safe += ".pdf"
            
        existing: str = os.path.join(folder, safe)
        if os.path.exists(existing):
            return [existing], "skipped"

    return [], "failed"


def _download_aspnet_form(
    profile: Dict[str, Any], folder: str, url: str
) -> Tuple[List[str], str]:
    """ASP.NET form simülasyonu ile indirme stratejisi.
    
    Sayfayı yükler, form verilerini ve gizli alanları toplar ve POST yapar.

    Args:
        profile (Dict[str, Any]): Profil verileri.
        folder (str): Hedef klasör.
        url (str): Formun bulunduğu sayfa bağlantısı.

    Returns:
        Tuple[List[str], str]: İndirme sonucu.
    """
    if not url:
        return [], "failed"

    timeout: int = profile.get("timeout", DEFAULT_TIMEOUT)
    form_selector: str = profile.get("form_selector", "#form1")
    submit_fields: Dict[str, Any] = profile.get("submit_fields", {})

    session: requests.Session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    r1: requests.Response = session.get(url, timeout=timeout)
    soup: BeautifulSoup = BeautifulSoup(r1.text, "html.parser")

    form: Any = soup.select_one(form_selector)
    if not form:
        log.warning(f"Form bulunamadı (Selector: {form_selector})")
        return [], "failed"

    data: Dict[str, str] = {}
    for inp in form.find_all("input"):
        name: Optional[str] = inp.get("name")
        if name:
            data[name] = inp.get("value", "")

    data.update(submit_fields)

    action: str = form.get("action") or ""
    post_url: str = urljoin(url, action)

    r2: requests.Response = session.post(post_url, data=data, timeout=timeout)

    if is_pdf_response(r2):
        path: Optional[str]
        status: str
        path, status = save_pdf(r2, f"report_{uuid.uuid4().hex[:8]}.pdf", folder)
        return ([path] if path else []), status

    cd: str = r2.headers.get("content-disposition", "")
    if cd:
        m: Optional[re.Match] = re.search(r'filename="?([^"]+)"?', cd)
        if m:
            fname: str
            try:
                fname = m.group(1).encode("latin1").decode("utf-8", errors="ignore")
            except Exception:
                fname = m.group(1)
                
            safe: str = sanitize_filename(fname)
            if not safe.lower().endswith(".pdf"):
                safe += ".pdf"
                
            existing: str = os.path.join(folder, safe)
            if os.path.exists(existing):
                return [existing], "skipped"

    return [], "failed"


def _download_html_scrape(
    profile: Dict[str, Any], folder: str, url: str
) -> Tuple[List[str], str]:
    """HTML sayfası içindeki bir indirme bağlantısını bulup indirme stratejisi.

    Args:
        profile (Dict[str, Any]): Profil verileri.
        folder (str): Hedef klasör.
        url (str): Ziyaret edilecek sayfa bağlantısı.

    Returns:
        Tuple[List[str], str]: İndirme sonucu.
    """
    if not url:
        return [], "failed"

    timeout: int = profile.get("timeout", 120)
    base_url: str = profile.get("base_url", "")
    link_selector: str = profile.get("pdf_link_selector", "a[download]")
    link_attr: str = profile.get("pdf_link_attr", "href")

    session: requests.Session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    try:
        i_m: Optional[re.Match] = re.search(r"[?&]i=(\d+)", url)
        cache_prefix: str = i_m.group(1) if i_m else uuid.uuid4().hex[:8]

        os.makedirs(folder, exist_ok=True)
        for fname in os.listdir(folder):
            if fname.startswith(cache_prefix) and fname.endswith(".pdf"):
                return [os.path.join(folder, fname)], "skipped"

        r: requests.Response = session.get(url, timeout=timeout)
        r.raise_for_status()

        soup: BeautifulSoup = BeautifulSoup(r.text, "html.parser")
        link_el: Any = soup.select_one(link_selector)
        if not link_el:
            log.warning(f"PDF bağlantısı bulunamadı (Selector: {link_selector})")
            return [], "failed"

        href: str = link_el.get(link_attr, "")
        if not href:
            return [], "failed"

        href = href.replace("\\", "/")
        pdf_url: str = urljoin(base_url + "/", href) if not href.startswith("http") else href

        r_pdf: requests.Response = session.get(pdf_url, timeout=timeout)
        r_pdf.raise_for_status()

        if not is_pdf_response(r_pdf) and b"%PDF" not in r_pdf.content[:10]:
            log.warning(f"PDF olmayan yanıt alındı: {pdf_url}")
            return [], "failed"

        fname_pdf: str = f"{cache_prefix}_imzali.pdf"
        path: str = os.path.join(folder, fname_pdf)
        
        with open(path, "wb") as f:
            f.write(r_pdf.content)
            
        return [path], "downloaded"

    except Exception as e:
        log.error(f"HTML kazıma indirme hatası: {e}")

        for fname_err in os.listdir(folder) if os.path.isdir(folder) else []:
            if cache_prefix in fname_err and fname_err.endswith(".pdf"):
                return [os.path.join(folder, fname_err)], "skipped"

        return [], "failed"


def _download_mmo(
    profile: Dict[str, Any], folder: str, params: Dict[str, Any]
) -> Tuple[List[str], str]:
    """Çok aşamalı indirme stratejisi.

    Args:
        profile (Dict[str, Any]): Profil verileri.
        folder (str): Hedef klasör.
        params (Dict[str, Any]): Bina ve başvuru bilgilerini içeren sözlük.

    Returns:
        Tuple[List[str], str]: İndirilen dosyalar ve durum.
    """
    base_url: str = profile.get("base_url", "")
    timeout: int = profile.get("timeout", DEFAULT_TIMEOUT)
    bina_id: str = params.get("bina_id", "")
    basvuru_id: str = params.get("basvuru_id", "")

    if not bina_id or not basvuru_id:
        return [], "failed"

    session: requests.Session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    csrf_url: str = base_url + profile.get("csrf_page", "/rapor-ara")
    csrf_selector: str = profile.get("csrf_selector", "meta[name='csrf-token']")

    token: Optional[str] = _get_csrf_token(session, csrf_url, csrf_selector, timeout)
    if not token:
        log.error("MMO: CSRF token alınamadı.")
        return [], "failed"

    query_url: str = base_url + profile.get("query_endpoint", "/basvuru-sorgula")
    payload: Dict[str, Any] = _fill_template(
        profile.get("query_payload_template", {}),
        csrf_token=token, bina_id=bina_id, basvuru_id=basvuru_id,
    )

    r_query: requests.Response = session.post(query_url, data=payload, timeout=timeout)
    soup: BeautifulSoup = BeautifulSoup(r_query.text, "html.parser")

    id_selector: str = profile.get("report_id_selector", "input[name='kontrol_id']")
    inputs: List[Any] = soup.select(id_selector)
    kontrol_ids: List[str] = [inp["value"] for inp in inputs if inp.get("value")]

    if not kontrol_ids:
        return [], "failed"

    download_url: str = base_url + profile.get("download_endpoint", "/rapor")
    downloaded: List[str] = []
    status: str = "failed"

    for kid in kontrol_ids:
        fpath: str = os.path.join(folder, f"mmo_{bina_id}_{basvuru_id}_{kid}.pdf")

        if os.path.exists(fpath):
            downloaded.append(fpath)
            status = "skipped" if status == "failed" else status
            continue

        fresh_token: Optional[str] = _get_csrf_token(session, csrf_url, csrf_selector, timeout)
        if not fresh_token:
            continue

        dl_payload: Dict[str, Any] = _fill_template(
            profile.get("download_payload_template", {}),
            csrf_token=fresh_token, kontrol_id=kid,
        )

        r_pdf: requests.Response = session.post(download_url, data=dl_payload, timeout=timeout)

        if is_pdf_response(r_pdf):
            os.makedirs(folder, exist_ok=True)
            with open(fpath, "wb") as f:
                f.write(r_pdf.content)
            downloaded.append(fpath)
            status = "downloaded"

    return downloaded, status


def _get_csrf_token(
    session: requests.Session, url: str, selector: str, timeout: int
) -> Optional[str]:
    """Bir sayfadan güvenlik belirtecini ayıklar.

    Args:
        session (requests.Session): Mevcut HTTP oturumu.
        url (str): Belirtecin alınacağı sayfa.
        selector (str): Stil seçici.
        timeout (int): Zaman aşımı süresi.

    Returns:
        Optional[str]: Bulunan belirteç değeri veya None.
    """
    try:
        r: requests.Response = session.get(url, timeout=timeout)
        soup: BeautifulSoup = BeautifulSoup(r.text, "html.parser")
        tag: Any = soup.select_one(selector)
        
        if tag and "content" in tag.attrs:
            return tag["content"]
        if tag and "value" in tag.attrs:
            return tag["value"]
    except Exception as e:
        log.error(f"CSRF token alma hatası: {e}")
        
    return None


def _fill_template(template: Dict[str, Any], **values: Any) -> Dict[str, Any]:
    """Veri şablonundaki yer tutucuları gerçek değerlerle doldurur.

    Args:
        template (Dict[str, Any]): Şablon sözlüğü.
        **values (Any): Yer tutucular yerine geçecek değerler.

    Returns:
        Dict[str, Any]: Doldurulmuş verilerle yeni sözlük.
    """
    result: Dict[str, Any] = {}
    for key, val in template.items():
        if isinstance(val, str):
            for k, v in values.items():
                val = val.replace(f"{{{k}}}", str(v))
        result[key] = val
    return result