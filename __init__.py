"""hermes-microduck: let Hermes drive Pollen Robotics' Microduck (real RL policies in MuJoCo) behind a safety interlock."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import schemas
from .commands import make_command
from .runtime import Runtime
from .tools import make_handlers

_RUNTIME: Optional[Runtime] = None


def get_runtime() -> Optional[Runtime]:
    return _RUNTIME


def register(ctx) -> None:
    """Register the duck tools, the pre_tool_call interlock, /duck and the bundled skill. Opens no connections."""
    global _RUNTIME
    try:
        data_dir = Path(ctx.state.data_dir)
    except Exception:
        data_dir = None
    rt = Runtime(get_config=ctx.get_config, data_dir=data_dir)
    _RUNTIME = rt
    handlers = make_handlers(rt)
    for schema in schemas.ALL:
        ctx.register_tool(name=schema["name"], toolset="duck", schema=schema, handler=handlers[schema["name"]],
                          emoji="🦆", description=schema["description"].split(". ")[0])
    ctx.register_hook("pre_tool_call", rt.interlock.pre_tool_call)
    ctx.register_command("duck", make_command(rt), description="Microduck link and safety: status, estop, clear, log, reset, stop",
                         args_hint="[status|estop|clear|log|reset|stop]")
    skill = Path(__file__).parent / "skills" / "microduck-operation" / "SKILL.md"
    if skill.exists():
        ctx.register_skill("microduck-operation", skill)
    ctx.on_unload(rt.shutdown)
