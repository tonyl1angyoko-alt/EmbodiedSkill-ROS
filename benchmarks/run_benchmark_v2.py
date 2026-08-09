#!/usr/bin/env python3
"""Run frozen-core adversarial, ablation, and post-freeze holdout suites."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from adversarial_v2 import PROFILES, run_suite, verify_core_freeze


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "local_validation_outputs",
    )
    args = parser.parse_args()
    manifest = verify_core_freeze()
    full = next(item for item in PROFILES if item.name == "F_full")

    # Design suite and holdout use disjoint parameter ranges.  No core changes
    # are permitted after either result is inspected.
    adversarial = run_suite(full, range(0, 5))
    holdout = run_suite(full, range(100, 106))
    ablations = {
        profile.name: run_suite(profile, range(0, 5))
        for profile in PROFILES
    }
    common = {
        "core_freeze": {
            "frozen_at": manifest["frozen_at"],
            "total_core_lines": manifest["total_core_lines"],
            "manifest": "benchmarks/core_freeze_manifest.json",
            "verified_unchanged": True,
        }
    }
    outputs = {
        "adversarial_v2_results.json": {**common, **adversarial},
        "holdout_results.json": {
            **common,
            "holdout_status": "post-freeze; not used to modify core",
            "variant_range": [100, 105],
            **holdout,
        },
        "ablation_results.json": {**common, "profiles": ablations},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for filename, payload in outputs.items():
        path = args.output_dir / filename
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {path}")
    print(json.dumps({
        "adversarial_full": adversarial["metrics"],
        "holdout_full": holdout["metrics"],
        "ablations": {
            name: result["metrics"] for name, result in ablations.items()
        },
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
