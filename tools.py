"""Tool handlers. Every handler returns JSON text (or a multimodal envelope for duck_look) and never raises."""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Callable, Dict

from .backends import BackendError
from .runtime import Runtime
from .safety import Blocked


def _ok(**kw: Any) -> str:
    return json.dumps({"ok": True, **kw}, default=str)


def _err(msg: str) -> str:
    return json.dumps({"ok": False, "error": msg})


def _f(v: Any, d: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _limits(rt: Runtime) -> Dict[str, Any]:
    s = rt.settings.snapshot()["safety"]
    return {k: s[k] for k in ("max_forward_mps", "max_backward_mps", "max_turn_rps", "max_duration_s", "max_head_rad")} | {
        "geofence": s["geofence"]}


def make_handlers(rt: Runtime) -> Dict[str, Callable[..., Any]]:
    def guarded(fn: Callable[[Dict[str, Any]], Any]) -> Callable[..., Any]:
        def handler(args: Dict[str, Any], **kwargs: Any) -> Any:
            args = args if isinstance(args, dict) else {}
            try:
                return fn(args)
            except Blocked as b:
                rt.interlock.record_block(fn.__name__, args, b.rule, b.reason)
                return _err(f"hermes-microduck interlock BLOCKED [{b.rule}]: {b.reason}")
            except BackendError as exc:
                return _err(str(exc))
            except Exception as exc:
                return _err(f"{type(exc).__name__}: {exc}")
        handler.__name__ = fn.__name__
        return handler

    def _clean(res: Dict[str, Any]) -> Dict[str, Any]:
        res = dict(res)
        res.pop("ok", None)
        return res

    def duck_status(a):
        be = rt.backend()
        st = be.status()
        return _ok(backend=be.name, via=be.description, **st, limits=_limits(rt), estop=rt.interlock.estop_status(),
                   recent_blocked=[f"{r['tool']} [{r['rule']}]" for r in rt.interlock.recent_blocked(3)])

    def duck_look(a):
        view = a.get("view") or "duck_eye"
        if view not in ("duck_eye", "chase", "overhead"):
            view = "duck_eye"
        cam = rt.settings.snapshot()["camera"]
        be = rt.backend()
        png = be.frame(view, int(cam["width"]), int(cam["height"]))
        out_dir = rt.snapshot_dir()
        path = out_dir / f"duck-{view}-{time.strftime('%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png"
        path.write_bytes(png)
        snaps = sorted(out_dir.glob("duck-*.png"))
        for old in snaps[:-int(cam.get("keep_last", 20))]:
            try:
                old.unlink()
            except OSError:
                pass
        st = be.status()
        text = _ok(view=view, path=str(path), media_tag=f"MEDIA:{path}", ball=st.get("ball"), pose=st.get("pose"),
                   next_step=(f"Call vision_analyze with image_url='{path}' to see it. " if str(cam.get("return_mode")) != "inline" else "")
                   + f"To show the picture to the user, include the line MEDIA:{path} in your reply.")
        if str(cam.get("return_mode", "path")).lower() == "inline":
            return {"_multimodal": True,
                    "content": [{"type": "text", "text": text},
                                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}],
                    "text_summary": text}
        return text

    def duck_walk(a):
        notes = rt.interlock.verify_token(a)
        res = rt.backend().walk(_f(a.get("forward_mps"), 0.0), _f(a.get("turn_rps"), 0.0), _f(a.get("duration_s"), 2.0), a.get("fence"))
        return _ok(interlock=notes, **_clean(res))

    def duck_turn(a):
        notes = rt.interlock.verify_token(a)
        return _ok(interlock=notes, **_clean(rt.backend().turn(_f(a.get("degrees"), 0.0))))

    def duck_kick_ball(a):
        notes = rt.interlock.verify_token(a)
        foot = a.get("foot") if a.get("foot") in ("left", "right") else "auto"
        return _ok(interlock=notes, **_clean(rt.backend().kick_ball(foot)))

    def duck_kick(a):
        notes = rt.interlock.verify_token(a)
        return _ok(interlock=notes, **_clean(rt.backend().kick(a.get("foot"))))

    def duck_sit(a):
        notes = rt.interlock.verify_token(a)
        return _ok(interlock=notes, **_clean(rt.backend().sit()))

    def duck_stand(a):
        notes = rt.interlock.verify_token(a)
        return _ok(interlock=notes, **_clean(rt.backend().stand()))

    def duck_head(a):
        notes = rt.interlock.verify_token(a)
        return _ok(interlock=notes, **_clean(rt.backend().head(_f(a.get("yaw"), 0.0), _f(a.get("pitch"), 0.0), _f(a.get("hold_s"), 1.0))))

    def duck_stop(a):
        err = None
        try:
            st = rt.backend().stop().get("status")
        except Exception as exc:  # still latch if asked
            st, err = None, str(exc)
        latched = None
        if a.get("estop"):
            latched = rt.interlock.engage_estop(a.get("reason") or "agent e-stop", source="agent")
        return _ok(stopped=err is None, stop_error=err, estop=latched or rt.interlock.estop_status(), status=st,
                   note="e-stop latched: only the human can clear it with /duck clear" if latched else "")

    fns = [duck_status, duck_look, duck_walk, duck_turn, duck_kick_ball, duck_kick, duck_sit, duck_stand, duck_head, duck_stop]
    return {f.__name__: guarded(f) for f in fns}
