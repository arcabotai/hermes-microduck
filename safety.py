"""Safety interlock for the duck's motion tools, enforced from a ``pre_tool_call`` hook.

Rules (``plugins.entries.hermes-microduck.settings.safety``):

* speed caps     - forward / backward / turn command magnitudes (0.25 m/s is the policy's trained limit)
* duration cap   - every walk is bounded; a default is injected when the model omits it
* geofence       - the walk's projected path (dead-reckoned from the current pose) must stay inside the arena
                   rectangle minus a margin; ball-chasing is refused if the ball or duck is outside it
* head limits    - head yaw / pitch offsets are capped
* e-stop latch   - once engaged, every motion tool is refused until a human runs ``/duck clear``;
                   the agent has no tool that clears it
* fail closed    - handlers refuse to act unless the hook vetted the call (per-process nonce)
* audit trail    - every refusal is logged (logger, ring buffer, ``blocked.jsonl``) and shown by ``/duck log``

Stopping is never blocked.
"""
from __future__ import annotations

import json
import logging
import math
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("hermes_microduck.interlock")

MOTION_TOOLS = {"duck_walk", "duck_turn", "duck_kick_ball", "duck_kick", "duck_sit", "duck_stand", "duck_head"}
READ_TOOLS = {"duck_status", "duck_look"}
STOP_TOOLS = {"duck_stop"}
ALL_TOOLS = MOTION_TOOLS | READ_TOOLS | STOP_TOOLS


class Blocked(Exception):
    def __init__(self, rule: str, reason: str):
        super().__init__(reason)
        self.rule, self.reason = rule, reason


def _num(v: Any, what: str, default: Optional[float] = None) -> float:
    if v is None:
        if default is None:
            raise Blocked("invalid_args", f"{what} is required")
        return default
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        raise Blocked("invalid_args", f"{what} must be a number, got {type(v).__name__}")
    try:
        f = float(v)
    except ValueError:
        raise Blocked("invalid_args", f"{what} must be a number, got {v!r}")
    if not math.isfinite(f):
        raise Blocked("invalid_args", f"{what} must be finite, got {v!r}")
    return f


def project_path(x: float, y: float, yaw: float, vx: float, wz: float, duration: float, dt: float = 0.1) -> List[Tuple[float, float]]:
    pts = [(x, y)]
    steps = max(1, int(math.ceil(duration / dt)))
    step = duration / steps
    for _ in range(steps):
        x += vx * math.cos(yaw) * step
        y += vx * math.sin(yaw) * step
        yaw += wz * step
        pts.append((x, y))
    return pts


class Interlock:
    def __init__(self, settings_fn: Callable[[], Dict[str, Any]],
                 state_fn: Callable[[], Optional[Dict[str, Any]]],
                 data_dir_fn: Callable[[], Optional[Path]] = lambda: None):
        self._settings_fn = settings_fn
        self._state_fn = state_fn
        self._data_dir_fn = data_dir_fn
        self._lock = threading.RLock()
        self.nonce = secrets.token_hex(12)
        self._latched: Optional[Dict[str, Any]] = None
        self._latch_loaded = False
        self.blocked: Deque[Dict[str, Any]] = deque(maxlen=500)
        self.counters = {"allowed": 0, "blocked": 0, "modified": 0}

    # ------------------------------------------------------------------ e-stop
    def _latch_path(self) -> Optional[Path]:
        d = self._data_dir_fn()
        return None if d is None else Path(d) / "estop.json"

    def _load_latch(self) -> None:
        if self._latch_loaded:
            return
        self._latch_loaded = True
        p = self._latch_path()
        if p and p.exists():
            try:
                data = json.loads(p.read_text())
                if data.get("latched"):
                    self._latched = data
            except Exception:
                self._latched = {"latched": True, "reason": "estop.json unreadable (failing closed)", "ts": time.time()}

    def estop_status(self) -> Dict[str, Any]:
        with self._lock:
            self._load_latch()
            return dict(self._latched) if self._latched else {"latched": False}

    @property
    def latched(self) -> bool:
        with self._lock:
            self._load_latch()
            return self._latched is not None

    def engage_estop(self, reason: str = "", source: str = "agent") -> Dict[str, Any]:
        with self._lock:
            self._load_latch()
            rec = {"latched": True, "reason": reason or "e-stop engaged", "source": source, "ts": time.time()}
            self._latched = rec
            self._write_latch(rec)
        logger.warning("E-STOP engaged by %s: %s", source, rec["reason"])
        return rec

    def clear_estop(self, source: str = "human") -> bool:
        with self._lock:
            self._load_latch()
            was = self._latched is not None
            self._latched = None
            self._write_latch({"latched": False, "cleared_by": source, "ts": time.time()})
        return was

    def _write_latch(self, rec: Dict[str, Any]) -> None:
        p = self._latch_path()
        if not p:
            return
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec))
            tmp.replace(p)
        except OSError as exc:
            logger.error("could not persist e-stop latch: %s", exc)

    # --------------------------------------------------------------- audit log
    def record_block(self, tool: str, args: Dict[str, Any], rule: str, reason: str) -> Dict[str, Any]:
        safe_args = {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}
        text = json.dumps(safe_args, default=str)
        entry = {"ts": time.time(), "iso": time.strftime("%H:%M:%S"), "tool": tool, "rule": rule,
                 "reason": reason, "args": text if len(text) < 400 else text[:400] + "…"}
        with self._lock:
            self.blocked.append(entry)
            self.counters["blocked"] += 1
        logger.warning("BLOCKED %s [%s]: %s | args=%s", tool, rule, reason, entry["args"])
        d = self._data_dir_fn()
        if d:
            try:
                path = Path(d) / "blocked.jsonl"
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(entry) + "\n")
            except OSError:
                pass
        return entry

    def recent_blocked(self, n: int = 20) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self.blocked)[-n:]

    # ------------------------------------------------------------------- rules
    def _fence(self, cfg: Dict[str, Any]) -> Optional[Tuple[float, float, float, float]]:
        gf = cfg.get("geofence") or {}
        if not gf.get("enabled"):
            return None
        m = float(gf.get("margin_m", 0.0))
        return (float(gf["x_min"]) + m, float(gf["x_max"]) - m, float(gf["y_min"]) + m, float(gf["y_max"]) - m)

    def _state(self) -> Dict[str, Any]:
        st = self._state_fn()
        if not st:
            raise Blocked("no_state", "cannot read the duck's pose (is the sim server running?); refusing to move blind")
        return st

    def evaluate(self, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
        cfg = self._settings_fn()["safety"]
        notes: List[str] = []
        patch: Dict[str, Any] = {}
        if self.latched:
            raise Blocked("estop_latched", f"e-stop is latched ({self.estop_status().get('reason')}); all motion is refused "
                          "until a human clears it with /duck clear")
        fence = self._fence(cfg)

        if tool == "duck_walk":
            vx = _num(args.get("forward_mps"), "forward_mps", 0.0)
            wz = _num(args.get("turn_rps"), "turn_rps", 0.0)
            fmax, bmax, tmax = float(cfg["max_forward_mps"]), float(cfg["max_backward_mps"]), float(cfg["max_turn_rps"])
            if vx > fmax + 1e-9:
                raise Blocked("over_speed_forward", f"forward speed {vx:.2f} m/s exceeds the limit of {fmax:.2f} m/s "
                              "(the Microduck walking policy is only trained up to 0.25 m/s)")
            if -vx > bmax + 1e-9:
                raise Blocked("over_speed_backward", f"backward speed {-vx:.2f} m/s exceeds the limit of {bmax:.2f} m/s")
            if abs(wz) > tmax + 1e-9:
                raise Blocked("over_speed_turn", f"turn rate {abs(wz):.2f} rad/s exceeds the limit of {tmax:.2f} rad/s")
            dmax = float(cfg["max_duration_s"])
            if args.get("duration_s") is None:
                dur = float(cfg["default_duration_s"])
                notes.append(f"no duration given; defaulted to {dur:.1f}s")
            else:
                dur = _num(args.get("duration_s"), "duration_s")
                if dur <= 0:
                    raise Blocked("invalid_args", "duration_s must be > 0")
                if dur > dmax + 1e-9:
                    raise Blocked("over_duration", f"duration {dur:.1f}s exceeds the maximum of {dmax:.1f}s per walk command")
            if fence and (vx != 0.0 or wz != 0.0):
                st = self._state()
                p = st["pose"]
                pts = project_path(p["x"], p["y"], math.radians(p["yaw_deg"]), vx, wz, dur)
                x0, x1, y0, y1 = fence
                for i, (px, py) in enumerate(pts):
                    if not (x0 <= px <= x1 and y0 <= py <= y1):
                        t = dur * i / max(1, len(pts) - 1)
                        raise Blocked("geofence", f"at the commanded speed the walk would leave the arena geofence "
                                      f"x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] after ≈{t:.1f}s near ({px:.2f}, {py:.2f}); "
                                      f"the duck is at ({p['x']:.2f}, {p['y']:.2f}) facing {p['yaw_deg']:.0f}°. "
                                      "Choose a shorter or different move.")
                notes.append("geofence ok")
                patch["fence"] = {"x_min": x0, "x_max": x1, "y_min": y0, "y_max": y1}
            patch.update({"forward_mps": vx, "turn_rps": wz, "duration_s": dur})
        elif tool == "duck_turn":
            deg = _num(args.get("degrees"), "degrees")
            if abs(deg) > 360:
                raise Blocked("invalid_args", "degrees must be between -360 and 360")
            if fence:
                st = self._state(); p = st["pose"]; x0, x1, y0, y1 = fence
                if not (x0 + 0.1 <= p["x"] <= x1 - 0.1 and y0 + 0.1 <= p["y"] <= y1 - 0.1):
                    raise Blocked("geofence", f"the duck is too close to the arena edge at ({p['x']:.2f}, {p['y']:.2f}) to "
                                  "turn (turning walks a small arc); back off first")
            patch["degrees"] = deg
        elif tool == "duck_kick_ball":
            if fence:
                st = self._state(); b = st["ball"]; x0, x1, y0, y1 = fence
                # the goal sits at the +x edge, so the ball may be beyond the fence's +x side; anything else is out of bounds
                if not (y0 <= b["y"] <= y1 and x0 <= b["x"]):
                    raise Blocked("geofence", f"the ball is at ({b['x']:.2f}, {b['y']:.2f}), outside the arena geofence; "
                                  "the duck will not chase it there")
                if b["x"] > x1:
                    raise Blocked("geofence", f"the ball is at ({b['x']:.2f}, {b['y']:.2f}), too close to the far wall to "
                                  "walk behind it safely")
        elif tool == "duck_head":
            hmax = float(cfg["max_head_rad"])
            for k in ("yaw", "pitch"):
                v = _num(args.get(k), k, 0.0)
                if abs(v) > hmax + 1e-9:
                    raise Blocked("over_head_limit", f"head {k} {v:.2f} rad exceeds the limit of ±{hmax:.2f} rad")
            hold = _num(args.get("hold_s"), "hold_s", 1.0)
            if not 0 <= hold <= 5:
                raise Blocked("invalid_args", "hold_s must be between 0 and 5 seconds")
        elif tool == "duck_kick":
            if args.get("foot") not in ("left", "right"):
                raise Blocked("invalid_args", "foot must be 'left' or 'right'")
        return {"patch": patch, "notes": notes}

    # -------------------------------------------------------------- the hook
    def pre_tool_call(self, tool_name: str = "", args: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Optional[Dict[str, Any]]:
        """Hermes ``pre_tool_call`` callback. Fails closed for the duck's motion tools."""
        if tool_name not in MOTION_TOOLS:
            return None
        args = args if isinstance(args, dict) else {}
        try:
            result = self.evaluate(tool_name, args)
        except Blocked as b:
            self.record_block(tool_name, args, b.rule, b.reason)
            return {"action": "block", "message": f"hermes-microduck interlock BLOCKED {tool_name} [{b.rule}]: {b.reason} "
                    "The duck did not move. Do not retry with a smaller, shorter or slower version on your own: tell the "
                    "user what was refused and why, offer a safe alternative, and wait for their answer."}
        except Exception as exc:  # never fail open
            logger.exception("interlock error")
            self.record_block(tool_name, args, "interlock_error", repr(exc))
            return {"action": "block", "message": f"hermes-microduck interlock BLOCKED {tool_name} [interlock_error]: {exc!r} (failing closed)"}
        with self._lock:
            self.counters["modified" if result["notes"] else "allowed"] += 1
        patch = dict(result["patch"])
        patch["_interlock"] = {"nonce": self.nonce, "notes": result["notes"]}
        return {"action": "modify", "args": patch}

    def verify_token(self, args: Dict[str, Any]) -> List[str]:
        tok = args.get("_interlock")
        if not isinstance(tok, dict) or tok.get("nonce") != self.nonce:
            raise Blocked("interlock_not_applied", "this call was not vetted by the hermes-microduck safety interlock "
                          "(pre_tool_call hook did not run); refusing to act")
        return list(tok.get("notes") or [])
