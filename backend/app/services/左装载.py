"""左轨（渠道回执）装载。双边幂等逻辑统一在 services.装载核。"""
from __future__ import annotations

from app.services import 装载核


def 装一批(体: dict) -> dict:
    return 装载核.装("左", 体)
