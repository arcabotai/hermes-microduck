from pathlib import Path

import pytest
import yaml

import hermes_microduck
from hermes_microduck import config, schemas

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = yaml.safe_load((ROOT / "plugin.yaml").read_text())


class FakeCtx:
    def __init__(self, tmp_path):
        self.tools, self.hooks, self.commands, self.skills, self.unload = {}, {}, {}, {}, []
        self.state = type("S", (), {"data_dir": tmp_path})()

    def get_config(self, key, default=None):
        return default

    def register_tool(self, **kw):
        self.tools[kw["name"]] = kw

    def register_hook(self, name, fn):
        self.hooks.setdefault(name, []).append(fn)

    def register_command(self, name, handler, **kw):
        self.commands[name] = (handler, kw)

    def register_skill(self, name, path, description=""):
        self.skills[name] = Path(path)

    def on_unload(self, fn):
        self.unload.append(fn)


@pytest.fixture
def ctx(tmp_path):
    c = FakeCtx(tmp_path)
    hermes_microduck.register(c)
    return c


def test_tools_match_manifest(ctx):
    assert sorted(ctx.tools) == sorted(MANIFEST["provides_tools"]) and len(ctx.tools) == 10
    for name, t in ctx.tools.items():
        assert t["toolset"] == "duck" and callable(t["handler"]) and t["schema"]["name"] == name


def test_hook_command_skill(ctx):
    assert list(ctx.hooks) == MANIFEST["provides_hooks"] == ["pre_tool_call"]
    assert "duck" in ctx.commands and "microduck-operation" in ctx.skills and ctx.skills["microduck-operation"].exists()


def test_manifest_defaults_match_config(ctx):
    for key, spec in MANIFEST["config_schema"].items():
        assert spec["default"] == config.DEFAULTS[key], key


def test_slash_command(ctx):
    handler = ctx.commands["duck"][0]
    assert "backend: mock" in handler("status")
    assert "LATCHED" in handler("estop testing")
    assert "cleared" in handler("clear")
    assert "No blocked" in handler("log")
