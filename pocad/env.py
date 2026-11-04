"""PoCAD'in ortam kökleri. Yalnız standart kütüphane.

Yol kodda sabit yazılmaz; ortam değişkeninden okunur (kaynak: oguz-atolye tools/env.py
@ca27b1b, `OGUZ_*` → `POCAD_*`; Windows kayıt defteri geri dönüşü taşınmadı).
"""
from __future__ import annotations

import os
from pathlib import Path


def env_path(name: str) -> Path | None:
    """Değişkenin değeri Path olarak; tanımlı değilse None."""
    value = os.environ.get(name)
    return Path(value) if value else None
