#!/usr/bin/env python3
"""Report unittest discovery counts without maintaining a hard-coded total."""

from __future__ import annotations

import argparse
import json
import unittest
from collections import Counter
from collections.abc import Iterator


def iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from iter_tests(item)
        else:
            yield item


def category(test: unittest.TestCase) -> str:
    test_id = test.id()
    if test_id.startswith("integration.test_jaka_kargo_ros2_runtime."):
        return "external_interface_gated"
    if test_id.startswith(("test_ros2_runtime.", "test_ros2_fake_robot_runtime.")):
        return "ros2_humble_gated"
    return "portable"


def inventory(start_dir: str = "tests") -> dict[str, int]:
    tests = list(iter_tests(unittest.defaultTestLoader.discover(start_dir)))
    counts = Counter(category(test) for test in tests)
    return {
        "discovered_total": len(tests),
        "portable": counts["portable"],
        "ros2_humble_gated": counts["ros2_humble_gated"],
        "external_interface_gated": counts["external_interface_gated"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit one JSON object")
    args = parser.parse_args()
    result = inventory()
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        for name, count in result.items():
            print(f"{name}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
