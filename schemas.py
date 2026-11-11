"""Tool schemas (what the model reads)."""

_SAFETY = ("Passes through the hermes-microduck safety interlock (speed / duration caps, arena geofence, e-stop latch); "
           "a refused call returns the rule and reason - do not retry the same call or split it into pieces to get around "
           "a limit. Do not substitute a smaller, slower or shorter version of a refused request on your own: tell the user what "
           "was refused and why, offer a safe alternative, and wait for them to choose. ")

DUCK_STATUS = {
    "name": "duck_status",
    "description": "Where is the duck and what is it doing: pose (x, y in metres, yaw in degrees; the arena is a 3 x 3 m square "
                   "centred on 0,0, +x points at the goal), posture (standing / walking / sitting / recovering), whether it is "
                   "upright, the ball's position with its distance and bearing from the duck (+ = to the duck's left), the goal, "
                   "the active safety limits and the e-stop state. Read-only. Call before the first move.",
    "parameters": {"type": "object", "properties": {}},
}

DUCK_LOOK = {
    "name": "duck_look",
    "description": "Take ONE picture and return it. view='duck_eye' is the duck's own head camera (what it sees ahead), "
                   "'chase' is a camera behind the duck, 'overhead' a top-down view of the whole arena. Use it to see the "
                   "ball, the goal and the walls. Read-only.",
    "parameters": {"type": "object", "properties": {
        "view": {"type": "string", "enum": ["duck_eye", "chase", "overhead"], "default": "duck_eye"},
    }},
}

DUCK_WALK = {
    "name": "duck_walk",
    "description": "Walk with the duck's trained RL walking policy: `forward_mps` (+ forward, - backward), `turn_rps` "
                   "(+ = turn left), for `duration_s` seconds, then stop. The policy was trained for commands up to 0.25 m/s "
                   "forward and needs about 0.2 m/s or more to start stepping; its real ground speed is about 0.1 m/s, so "
                   "1 m takes roughly 10 s. Turning while walking works far better than turning in place - use duck_turn "
                   "to change heading. " + _SAFETY + "Returns the pose before and after.",
    "parameters": {"type": "object", "properties": {
        "forward_mps": {"type": "number", "description": "Forward command in m/s (0.25 is the trained walking speed)."},
        "turn_rps": {"type": "number", "description": "Turn command in rad/s, + = left / counter-clockwise.", "default": 0},
        "duration_s": {"type": "number", "description": "How long to walk, seconds."},
    }, "required": ["forward_mps"]},
}

DUCK_TURN = {
    "name": "duck_turn",
    "description": "Turn the duck by `degrees` (+ = left / counter-clockwise, - = right), closed-loop on its heading. It "
                   "turns by walking a tight arc, so it moves a little (about 10-20 cm) while turning. " + _SAFETY,
    "parameters": {"type": "object", "properties": {
        "degrees": {"type": "number", "description": "Relative turn in degrees, between -360 and 360."},
    }, "required": ["degrees"]},
}

DUCK_KICK_BALL = {
    "name": "duck_kick_ball",
    "description": "Go and kick the ball toward the goal: the duck walks to the ball, lines it up in front of a foot "
                   "(chosen automatically unless `foot` is given) and fires Pollen's trained kick policy. Takes 10-30 s. "
                   "Returns where the ball went and whether it went into the goal (`goal_scored`). One kick sends the ball "
                   "about 1 m, so a far ball may need a second kick. " + _SAFETY,
    "parameters": {"type": "object", "properties": {
        "foot": {"type": "string", "enum": ["auto", "left", "right"], "default": "auto"},
    }},
}

DUCK_KICK = {
    "name": "duck_kick",
    "description": "One kick in place with the left or right foot (Pollen's blind 0.5 s kick policy). Only useful when the "
                   "ball is already right in front of that foot; to score, use duck_kick_ball. " + _SAFETY,
    "parameters": {"type": "object", "properties": {
        "foot": {"type": "string", "enum": ["left", "right"]},
    }, "required": ["foot"]},
}

DUCK_SIT = {
    "name": "duck_sit",
    "description": "Sit down on the hull (Pollen's trained sit/stand policy). The duck cannot walk while sitting; use "
                   "duck_stand first. " + _SAFETY,
    "parameters": {"type": "object", "properties": {}},
}

DUCK_STAND = {
    "name": "duck_stand",
    "description": "Stand back up from sitting (sit/stand policy), then hand back to the walking policy. " + _SAFETY,
    "parameters": {"type": "object", "properties": {}},
}

DUCK_HEAD = {
    "name": "duck_head",
    "description": "Point the duck's head: `yaw` (+ = look left) and `pitch` (+ = look up) in radians, held for `hold_s` "
                   "seconds. Call with 0, 0 to look straight ahead again. Good for looking around or nodding. " + _SAFETY,
    "parameters": {"type": "object", "properties": {
        "yaw": {"type": "number", "default": 0},
        "pitch": {"type": "number", "default": 0},
        "hold_s": {"type": "number", "default": 1.0},
    }},
}

DUCK_STOP = {
    "name": "duck_stop",
    "description": "STOP the duck now (zero commands, cancel any walk / approach). With estop=true also LATCH the e-stop: all "
                   "motion is then refused until the human clears it with /duck clear. Never blocked. Use estop=true if the "
                   "user says stop / halt / emergency or anything looks unsafe.",
    "parameters": {"type": "object", "properties": {
        "estop": {"type": "boolean", "default": False},
        "reason": {"type": "string"},
    }},
}

ALL = [DUCK_STATUS, DUCK_LOOK, DUCK_WALK, DUCK_TURN, DUCK_KICK_BALL, DUCK_KICK, DUCK_SIT, DUCK_STAND, DUCK_HEAD, DUCK_STOP]
