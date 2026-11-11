"""``/duck`` slash command: human-only controls (the agent cannot type slash commands)."""
from __future__ import annotations

import json
from typing import Callable

from .runtime import Runtime

HELP = """hermes-microduck - duck link and safety controls
  /duck status          backend, pose, ball, limits, e-stop
  /duck estop [reason]  latch the e-stop now (all motion refused)
  /duck clear           clear the e-stop latch (human-only)
  /duck log [n]         last n blocked calls with reasons
  /duck reset [x y]     respawn the duck (and put the ball at x, y)
  /duck stop            stop now (no latch)"""


def make_command(rt: Runtime) -> Callable[[str], str]:
    from .tools import make_handlers
    h = make_handlers(rt)

    def handle(raw_args: str = "") -> str:
        parts = (raw_args or "").strip().split()
        sub = parts[0].lower() if parts else "status"
        if sub in ("help", "-h", "--help"):
            return HELP
        if sub == "estop":
            rec = rt.interlock.engage_estop(" ".join(parts[1:]) or "human e-stop via /duck estop", source="human")
            try:
                rt.backend().stop()
            except Exception:
                pass
            return f"E-STOP LATCHED ({rec['reason']}). All duck motion is refused. Clear with /duck clear."
        if sub == "clear":
            return "E-stop cleared." if rt.interlock.clear_estop("human") else "E-stop was not latched."
        if sub == "stop":
            return h["duck_stop"]({})
        if sub == "reset":
            try:
                if len(parts) >= 3:
                    rt.backend().reset(float(parts[1]), float(parts[2]))
                else:
                    rt.backend().reset()
                return "Duck respawned."
            except Exception as exc:
                return f"reset failed: {exc}"
        if sub == "log":
            n = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
            rows = rt.interlock.recent_blocked(n)
            if not rows:
                return "No blocked calls this session."
            return "\n".join(f"{r['iso']}  {r['tool']}  [{r['rule']}]  {r['reason']}" for r in rows)
        if sub == "status":
            res = json.loads(h["duck_status"]({}))
            if not res.get("ok"):
                return res.get("error", "status failed")
            p, b, lim, est = res["pose"], res["ball"], res["limits"], res["estop"]
            return "\n".join([
                f"backend: {res['backend']} ({res['via']})",
                f"duck: x={p['x']:.2f} y={p['y']:.2f} yaw={p['yaw_deg']:.0f}°  {res['posture']}  upright={res['upright']}",
                f"ball: x={b['x']:.2f} y={b['y']:.2f}  {b['distance_m']:.2f} m away, bearing {b['bearing_deg']:.0f}°",
                f"limits: ≤{lim['max_forward_mps']} m/s fwd, ≤{lim['max_turn_rps']} rad/s turn, ≤{lim['max_duration_s']} s per walk",
                f"e-stop: {'LATCHED - ' + str(est.get('reason')) if est.get('latched') else 'clear'}",
                f"interlock: {rt.interlock.counters}"])
        return f"unknown subcommand {sub!r}\n{HELP}"

    return handle
