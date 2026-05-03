"""
Etiket çözümleyici: Düz veya ağaç yapısındaki Gmail etiketlerini yönetir.

Düz mod (use_tree: false):
  "Kırmızı Etiketli" → "Kırmızı Etiketli"

Ağaç modu (use_tree: true, tree_parent: "Asansör Raporları"):
  "Kırmızı Etiketli" → "Asansör Raporları/Kırmızı Etiketli"
  "Kent Belgelendirme" → "Asansör Raporları/Kent Belgelendirme"

Gmail ağaç yapısındaki etiketler "/" karakteri ile birbirinden ayrılır.
"""

from typing import Dict, List, Optional, Any


class LabelResolver:
    """Yapılandırma ayarlarındaki etiket ayarlarından etiket isimlerini çözümler.
    
    Attributes:
        _parent (str): Ağaç yapısı kullanılıyorsa ana etiket (parent) adı.
        _use_tree (bool): Etiketlerin hiyerarşik (ağaç) yapıda olup olmadığı.
        _colors (Dict[str, str]): Renk isimleri ve etiket karşılıkları haritası.
        _appt (str): Randevu e-postaları için kullanılacak etiket adı.
    """

    def __init__(self, config: Dict[str, Any]) -> None:
        """LabelResolver sınıfını verilen yapılandırma ile başlatır.

        Args:
            config (Dict[str, Any]): Uygulama yapılandırma verilerini içeren sözlük.
        """
        ls: Dict[str, Any] = config.get("label_settings", {})
        
        self._parent: str = ls.get("tree_parent", "").strip().rstrip("/")
        self._use_tree: bool = ls.get("use_tree", False) and bool(self._parent)
        self._colors: Dict[str, str] = ls.get("colors", {
            "Kırmızı": "Kırmızı Etiketli",
            "Sarı": "Sarı Etiketli",
            "Mavi": "Mavi Etiketli",
            "Yeşil": "Yeşil Etiketli",
        })
        self._appt: str = ls.get("appointment_label", "Randevu")

    def color_label(self, color: str) -> str:
        """Renk adından tam Gmail etiket adını üretir.
        
        Örn: 'Kırmızı' → 'Kırmızı Etiketli' (Düz) veya 'Raporlar/Kırmızı Etiketli' (Ağaç).

        Args:
            color (str): Çözümlenecek renk adı.

        Returns:
            str: Sisteme uygun tam etiket yolu/adı.
        """
        name: str = self._colors.get(color, "")
        
        if not name:
            for c, n in self._colors.items():
                if color in n or n in color:
                    name = n
                    break
                    
        if not name:
            name = f"{color} Etiketli"
            
        return self._prefix(name)

    def appointment_label(self) -> str:
        """Randevu etiketi için tam yolu döndürür.

        Returns:
            str: Çözümlenmiş randevu etiket adı.
        """
        return self._prefix(self._appt)

    def source_label(self, label_name: str) -> str:
        """Kaynak (firma adı) etiketini hiyerarşik yapıya uygun olarak döndürür.

        Args:
            label_name (str): Kaynak firma için belirlenen kısa etiket adı.

        Returns:
            str: Ön ek eklenmiş tam kaynak etiket adı.
        """
        return self._prefix(label_name) if label_name else ""

    def all_color_labels(self) -> List[str]:
        """Tüm renk etiketlerini ve randevu etiketini içeren bir liste döndürür.

        Returns:
            List[str]: Çözümlenmiş tüm operasyonel etiketlerin listesi.
        """
        labels: List[str] = [self._prefix(n) for n in self._colors.values()]
        labels.append(self.appointment_label())
        return labels

    def all_labels_for_config(self) -> List[str]:
        """Yapılandırma işlemleri için tüm renk etiketleri listesini döndürür.

        Returns:
            List[str]: Renk etiketleri listesi.
        """
        return self.all_color_labels()

    def _prefix(self, name: str) -> str:
        """Eğer ağaç yapısı aktifse etiketin başına ana klasör yolunu ekler.

        Args:
            name (str): Ham etiket adı.

        Returns:
            str: Ön ek (prefix) eklenmiş etiket yolu.
        """
        if self._use_tree and self._parent:
            return f"{self._parent}/{name}"
        return name

    def strip_parent(self, full_label: str) -> str:
        """Tam etiket yolundan ana (parent) etiketi çıkararak sadece etiket adını döndürür.

        Args:
            full_label (str): Gmail'den gelen tam etiket yolu.

        Returns:
            str: Temizlenmiş, sadece etiket adını içeren dizge.
        """
        if self._use_tree and self._parent and full_label.startswith(self._parent + "/"):
            return full_label[len(self._parent) + 1:]
        return full_label

    def find_color_for_label(self, label_name: str) -> Optional[str]:
        """Verilen bir etiket adından ilgili renk kodunu bulur.
        
        Örn: 'Asansör Raporları/Kırmızı Etiketli' → 'Kırmızı'.

        Args:
            label_name (str): Aranacak tam etiket adı.

        Returns:
            Optional[str]: Eşleşen renk adı veya bulunamazsa None.
        """
        stripped: str = self.strip_parent(label_name)
        
        for color, name in self._colors.items():
            if stripped == name or color in stripped:
                return color
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Sınıfın mevcut ayarlarını bir sözlük olarak döndürür.

        Returns:
            Dict[str, Any]: Sınıf durumunu temsil eden sözlük.
        """
        return {
            "use_tree": self._use_tree,
            "tree_parent": self._parent,
            "colors": self._colors,
            "appointment_label": self._appt,
        }