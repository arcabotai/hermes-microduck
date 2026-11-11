"""Plugin runtime: settings, backend lifecycle, interlock, data directory."""
from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .backends import BackendError, MockBackend, SimBackend
from .config import Settings
from .safety import Interlock


class Runtime:
    def __init__(self, get_config: Optional[Callable[[str, Any], Any]] = None,
                 data_dir: Optional[Path] = None, overrides: Optional[Dict[str, Any]] = None):
        self.settings = Settings(get_config, overrides)
        self._data_dir = Path(data_dir) if data_dir else None
        self._backend: Any = None
        self._key: Any = None
        self._lock = threading.RLock()
        self.interlock = Interlock(self.settings.snapshot, self._state_for_interlock, lambda: self.data_dir)

    @property
    def data_dir(self) -> Path:
        if self._data_dir is None:
            self._data_dir = Path(tempfile.mkdtemp(prefix="hermes-microduck-"))
        return self._data_dir

    def snapshot_dir(self) -> Path:
        d = self.data_dir / "snapshots"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def backend(self):
        cfg = self.settings.snapshot()
        kind = str(cfg["backend"]).lower()
        key = (kind, cfg["sim"]["url"]) if kind == "sim" else (kind,)
        with self._lock:
            if self._backend is None or key != self._key:
                if kind == "mock":
                    self._backend = MockBackend()
                elif kind == "sim":
                    self._backend = SimBackend(cfg["sim"]["url"], cfg["sim"].get("timeout_s", 90))
                else:
                    raise BackendError(f"unknown backend {kind!r}; use 'mock' or 'sim'")
                self._key = key
            return self._backend

    def _state_for_interlock(self) -> Optional[Dict[str, Any]]:
        try:
            return self.backend().status()
        except BackendError:
            return None

    def shutdown(self) -> None:
        with self._lock:
            self._backend = None
