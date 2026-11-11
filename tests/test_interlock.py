import pytest


def test_status_is_readonly_and_reports_limits(duck):
    r = duck.call("duck_status")
    assert r["ok"] and r["backend"] == "mock" and r["limits"]["max_forward_mps"] == 0.25
    assert r["estop"] == {"latched": False}


def test_walk_within_limits_moves(duck):
    r = duck.call("duck_walk", {"forward_mps": 0.25, "duration_s": 5})
    assert r["ok"] and r["displacement_m"] > 0.3 and "geofence ok" in r["interlock"]


@pytest.mark.parametrize("args,rule", [
    ({"forward_mps": 2.0, "duration_s": 3}, "over_speed_forward"),
    ({"forward_mps": -0.5, "duration_s": 1}, "over_speed_backward"),
    ({"forward_mps": 0.25, "turn_rps": 3, "duration_s": 1}, "over_speed_turn"),
    ({"forward_mps": 0.25, "duration_s": 30}, "over_duration"),
    ({"forward_mps": "fast"}, "invalid_args"),
    ({"forward_mps": float("nan")}, "invalid_args"),
])
def test_unsafe_walks_blocked(duck, args, rule):
    r = duck.call("duck_walk", args)
    assert r["blocked"] and f"[{rule}]" in r["message"]
    assert duck.rt.interlock.recent_blocked(1)[0]["rule"] == rule


def test_full_speed_thirty_seconds_is_blocked(duck):
    r = duck.call("duck_walk", {"forward_mps": 0.25, "duration_s": 30})
    assert r["blocked"] and "over_duration" in r["message"]


def test_default_duration_injected(duck):
    r = duck.call("duck_walk", {"forward_mps": 0.25})
    assert r["ok"] and any("defaulted" in n for n in r["interlock"])


def test_geofence_blocks_walk_into_wall(make):
    h = make({"safety": {"max_duration_s": 60}})
    # duck starts at (-0.6, 0) facing +x; 0.25 m/s for 60 s projects far past the +x wall
    r = h.call("duck_walk", {"forward_mps": 0.25, "duration_s": 60})
    assert r["blocked"] and "[geofence]" in r["message"]


def test_handler_refuses_without_hook(duck):
    r = duck.raw("duck_walk", {"forward_mps": 0.25, "duration_s": 1})
    assert not r["ok"] and "interlock_not_applied" in r["error"]
    r = duck.raw("duck_walk", {"forward_mps": 0.25, "_interlock": {"nonce": "forged"}})
    assert not r["ok"] and "interlock_not_applied" in r["error"]


def test_estop_latch_blocks_everything_until_human_clears(duck):
    r = duck.call("duck_stop", {"estop": True, "reason": "test"})
    assert r["ok"] and r["estop"]["latched"]
    for tool, args in [("duck_walk", {"forward_mps": 0.25}), ("duck_kick_ball", {}), ("duck_sit", {}), ("duck_turn", {"degrees": 90}),
                       ("duck_head", {"yaw": 0.2})]:
        assert "[estop_latched]" in duck.call(tool, args)["message"]
    assert duck.call("duck_stop")["ok"]  # stopping is never blocked
    assert duck.call("duck_status")["ok"]
    assert duck.rt.interlock.clear_estop("human")
    assert duck.call("duck_walk", {"forward_mps": 0.25, "duration_s": 1})["ok"]


def test_estop_persists_across_runtimes(make):
    a = make(); a.call("duck_stop", {"estop": True})
    b = make()
    assert "[estop_latched]" in b.call("duck_walk", {"forward_mps": 0.25})["message"]


def test_head_limits(duck):
    assert "[over_head_limit]" in duck.call("duck_head", {"yaw": 1.5})["message"]
    assert duck.call("duck_head", {"yaw": 0.5, "pitch": 0.2})["ok"]


def test_kick_ball_scores_in_mock(duck):
    r = duck.call("duck_kick_ball")
    assert r["ok"] and r["ball_travel_m"] > 0.5 and r["foot"] in ("left", "right")


def test_kick_ball_refused_when_ball_out_of_fence(duck):
    duck.rt.backend().reset(0.0, 1.45)
    r = duck.call("duck_kick_ball")
    assert r["blocked"] and "[geofence]" in r["message"]


def test_unreachable_sim_fails_closed(make):
    h = make({"backend": "sim", "sim": {"url": "http://127.0.0.1:9", "timeout_s": 1}})
    r = h.call("duck_walk", {"forward_mps": 0.25, "duration_s": 1})
    assert r["blocked"] and "[no_state]" in r["message"]
    r = h.call("duck_status")
    assert not r["ok"] and "cannot reach" in r["error"]


def test_look_returns_png(duck, tmp_path):
    r = duck.call("duck_look", {"view": "overhead"})
    assert r["ok"] and r["media_tag"].startswith("MEDIA:")
    from pathlib import Path
    assert Path(r["path"]).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_sit_then_walk_refused_by_mock_until_stand(duck):
    duck.call("duck_sit")
    r = duck.call("duck_walk", {"forward_mps": 0.25, "duration_s": 1})
    assert "sitting" in r["end_reason"]
    duck.call("duck_stand")
    assert duck.call("duck_walk", {"forward_mps": 0.25, "duration_s": 2})["displacement_m"] > 0
