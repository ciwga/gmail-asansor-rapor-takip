# -*- coding: utf-8 -*-
"""
Merkezi Kaynak Kod ve Dizin Yolları Modülü.

Bu modül, projenin kaynak kod hiyerarşisindeki sabit yolları güvenli ve 
işletim sisteminden bağımsız bir şekilde tanımlar.
"""

from pathlib import Path
from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectPaths:
    """Projedeki sabit dizin ve dosya yollarını barındıran salt-okunur veri sınıfı."""

    BASE_DIR: Path
    APP_DIR: Path
    
    DOWNLOADERS_DIR: Path
    WEB_DIR: Path
    STATIC_DIR: Path
    TEMPLATES_DIR: Path
    PARSERS_DIR: Path
    
    SCRAPING_PROFILES: Path

    SECURE_PATH: Path
    MASTER_KEY_FILE: Path
    DEFAULT_DB_PATH: Path
    LEGACY_DB_PATH: Path
    DEFAULT_LOG_PATH: Path


def _initialize_paths() -> ProjectPaths:
    """Proje kök dizinini baz alarak tüm sabit kaynak kod yollarını hiyerarşik olarak hesaplar.
    
    Returns:
        ProjectPaths: Projenin iskelet yollarını içeren değiştirilemez veri yapısı.
    """
    secure_dir: Path = Path.home() / ".AsansorRaporlari"
    base_dir: Path = Path(__file__).resolve().parent.parent
    app_dir: Path = base_dir / "app"
    
    web_dir: Path = app_dir / "web"
    downloaders_dir: Path = app_dir / "downloaders"
    parsers_dir: Path = app_dir / "parsers"
    
    return ProjectPaths(
        BASE_DIR=base_dir,
        APP_DIR=app_dir,
        DOWNLOADERS_DIR=downloaders_dir,
        WEB_DIR=web_dir,
        STATIC_DIR=web_dir / "static",
        TEMPLATES_DIR=web_dir / "templates",
        PARSERS_DIR=parsers_dir,
        SCRAPING_PROFILES=downloaders_dir / "scraping_profiles.json",
        SECURE_PATH=secure_dir,
        MASTER_KEY_FILE=secure_dir / ".master.key",
        DEFAULT_DB_PATH=secure_dir / "asansor_denetcisi.db",
        LEGACY_DB_PATH=secure_dir / "data/asansor_denetcisi.db",
        DEFAULT_LOG_PATH=secure_dir / "asansor_denetcisi.log"
    )


paths: ProjectPaths = _initialize_paths()