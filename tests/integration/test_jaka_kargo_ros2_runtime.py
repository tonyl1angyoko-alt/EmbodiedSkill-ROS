from __future__ import annotations

import unittest


def _legacy_interfaces_available() -> bool:
    try:
        import jagv_interfaces.msg  # noqa: F401
        import jaka_toolbox_interfaces.srv  # noqa: F401
        import rclpy  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(
    _legacy_interfaces_available(),
    "external JAKA/Kargo ROS2 interface packages are not sourced",
)
class JakaKargoRos2RuntimeTests(unittest.TestCase):
    def test_process_separated_legacy_compatible_scenarios(self):
        from embodied_skill_ros.integrations.jaka_kargo.runtime_validation import (
            run_scenarios,
        )

        scenarios = run_scenarios()
        self.assertEqual(len(scenarios), 9)
        self.assertTrue(all(item["passed"] for item in scenarios), scenarios)


if __name__ == "__main__":
    unittest.main()
