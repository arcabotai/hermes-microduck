"""Plugin settings: defaults deep-merged over ``plugins.entries.hermes-microduck.settings`` (re-read on every call)."""
from __future__ import annotations

import copy
from typing import Any, Callable, Dict

DEFAULTS: Dict[str, Any] = {
    "backend": "mock",  # "mock" (kinematic duck, no deps) | "sim" (MuJoCo + real Microduck ONNX policies)
    "sim": {"url": "http://127.0.0.1:8765", "timeout_s": 90},
    "safety": {
        # 0.25 m/s forward is the Microduck walking policy's trained command limit (Pollen's runtime uses the same)
        "max_forward_mps": 0.25,
        "max_backward_mps": 0.2,
        "max_turn_rps": 1.0,
        "max_duration_s": 8.0,
        "default_duration_s": 2.0,
        "max_head_rad": 0.6,
        "geofence": {"enabled": True, "x_min": -1.5, "x_max": 1.5, "y_min": -1.5, "y_max": 1.5, "margin_m": 0.2},
        "blocked_log_max": 500,
    },
    "camera": {"width": 640, "height": 480, "return_mode": "path", "keep_last": 20},
}


def deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


class Settings:
    def __init__(self, getter: Callable[[str, Any], Any] | None = None, overrides: Dict[str, Any] | None = None):
        self._getter = getter
        self._overrides = overrides or {}

    def snapshot(self) -> Dict[str, Any]:
        merged = copy.deepcopy(DEFAULTS)
        for key in DEFAULTS:
            value = None
            if self._getter is not None:
                try:
                    value = self._getter(key, None)
                except Exception:
                    value = None
            if value is None:
                continue
            if isinstance(DEFAULTS[key], dict) and isinstance(value, dict):
                merged[key] = deep_merge(DEFAULTS[key], value)
            elif not isinstance(DEFAULTS[key], dict):
                merged[key] = value
        return deep_merge(merged, self._overrides)

    def __getitem__(self, key: str) -> Any:
        return self.snapshot()[key]
