"""Load the repo root as the importable package ``hermes_microduck`` (the repo *is* the plugin directory)."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if "hermes_microduck" not in sys.modules:
    spec = importlib.util.spec_from_file_location("hermes_microduck", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hermes_microduck"] = mod
    spec.loader.exec_module(mod)

from hermes_microduck.runtime import Runtime  # noqa: E402
from hermes_microduck.tools import make_handlers  # noqa: E402


class Harness:
    """Runs tool calls the way Hermes does: pre_tool_call hook first, then the handler."""

    def __init__(self, tmp_path, overrides=None):
        self.rt = Runtime(None, tmp_path, overrides)
        self.handlers = make_handlers(self.rt)

    def call(self, tool, args=None):
        args = dict(args or {})
        directive = self.rt.interlock.pre_tool_call(tool_name=tool, args=args)
        if directive and directive.get("action") == "block":
            return {"blocked": True, "message": directive["message"]}
        if directive and directive.get("action") == "modify":
            args.update(directive["args"])
        out = self.handlers[tool](args)
        if isinstance(out, dict):
            out = out["text_summary"]
        res = json.loads(out)
        res["blocked"] = False
        return res

    def raw(self, tool, args=None):
        return json.loads(self.handlers[tool](dict(args or {})))


@pytest.fixture
def make(tmp_path):
    return lambda overrides=None: Harness(tmp_path, overrides)


@pytest.fixture
def duck(make):
    return make()
