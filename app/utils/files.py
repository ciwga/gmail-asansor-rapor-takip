"""Dosya sistemi yardımcı araçları."""

import os


def ensure_dir(path: str) -> str:
    """Klasörün var olduğundan emin olur, yoksa oluşturur.

    Args:
        path (str): Oluşturulacak veya kontrol edilecek klasör yolu.

    Returns:
        str: İşlem yapılan klasörün yolu.
    """
    os.makedirs(path, exist_ok=True)
    return path