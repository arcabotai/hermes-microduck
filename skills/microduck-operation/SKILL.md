---
name: microduck-operation
description: How to drive Pollen Robotics' Microduck (simulated) with the hermes-microduck tools - look first, small verified moves, ball-kicking, reading interlock refusals, e-stop discipline.
---

# Driving the Microduck

The duck is a 25 cm bipedal robot walking on a **trained RL policy** (from Pollen Robotics / Hugging Face). You send it
high-level commands; the policy decides the joint motions. It can fall over. Be a careful, honest pilot.

## Pre-flight
1. `duck_status` - backend (`sim` = MuJoCo with the real policies, `mock` = kinematic stand-in), pose, ball, limits, e-stop.
2. `duck_look` (view `duck_eye`) - look before you move and say what you see.

## Moving
- Coordinates: arena is 3 x 3 m centred on (0, 0); +x points at the goal; yaw 0° faces the goal; + angles are to the left.
- `duck_walk forward_mps=0.25` is the trained walking speed; below ~0.2 m/s the policy just stands. Real speed ≈ 0.1 m/s.
- Use `duck_turn degrees=...` to change heading (it arcs, so expect 10-20 cm of drift). Check `duck_status` after.
- Keep walks short (≤ 8 s each) and re-check the pose. Stay away from the walls.

## Kicking the ball
- `duck_kick_ball` does the whole approach + line-up + kick toward the goal and reports `goal_scored`.
- If the ball stopped short, it is fine to call it again; report honestly how many kicks it took.

## Posture and gestures
- `duck_sit` / `duck_stand`; `duck_head yaw=0.5` looks left, `pitch=0.3` looks up; `yaw=0, pitch=0` re-centres.

## When the interlock says no
`hermes-microduck interlock BLOCKED ... [rule]` is final for that request. Do **not** retry it, split it into many smaller
"legal" walks to reach the same result, or look for another way to move the duck. Tell the user what was refused and why,
and offer a safe alternative (e.g. "I can walk at 0.25 m/s for 8 s") - but do not run that alternative until the user
says yes. The duck stays put after a refusal.
`estop_latched`: stop and tell the user only they can clear it with `/duck clear`.

## E-stop
If the user says stop / halt, or the duck fell or is near a wall: `duck_stop estop=true` first, explain after.

## Honesty
Report what the duck actually did (poses, `goal_scored`, `end_reason`), not what you intended. Show pictures with the
`MEDIA:` line from `duck_look`.
