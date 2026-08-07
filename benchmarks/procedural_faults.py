#!/usr/bin/env python3
from __future__ import annotations

import random
from typing import Any


def generate_trials(seed: int, count: int) -> list[dict[str, Any]]:
    """Generate deterministic transient-fault trials without fixture-file reuse.

    This is not a scientific holdout: its templates and fault model were present
    while the recovery implementation was developed.
    """

    rng = random.Random(seed)
    templates = (
        ("set_head", lambda: {"yaw_deg": float(rng.randint(-45, 45))}, "head_yaw_deg"),
        ("set_lift", lambda: {"height_mm": float(rng.randint(50, 700))}, "lift_height_mm"),
        ("move_agv", lambda: {"distance_m": rng.choice((-1.0, -0.5, 0.5, 1.0))}, "agv_position_m"),
    )
    modes = ("none", "physical_failure", "command_failure", "timeout")
    trials = []
    for index in range(count):
        skill, arguments_factory, target_field = rng.choice(templates)
        arguments = arguments_factory()
        mode = rng.choice(modes)
        trials.append({
            "id": f"procedural_{seed}_{index:04d}",
            "skill": skill,
            "arguments": arguments,
            "target_field": target_field,
            "fault_mode": mode,
        })
    return trials
