import json
import unittest

from embodied_skill_ros.models.skill_result import CommandReceipt
from embodied_skill_ros.visualization.rviz_comparison_bridge import (
    FALSE_SUCCESS,
    REPAIR,
    LaneSignals,
    panel_text,
    parse_runtime_event,
    update_lane_signals,
)
from embodied_skill_ros.visualization.rviz_comparison_runner import (
    baseline_middleware_success,
    comparison_definition,
    comparison_endpoints,
)
from embodied_skill_ros.visualization.rviz_demo_bridge import VisualTargets


class RvizComparisonProjectionTests(unittest.TestCase):
    def test_runtime_event_parser_rejects_malformed_data(self):
        self.assertIsNone(parse_runtime_event("not-json"))
        self.assertIsNone(parse_runtime_event("[]"))
        self.assertEqual(parse_runtime_event(json.dumps({"event": "x"})), {"event": "x"})

    def test_signal_updates_follow_real_runtime_events(self):
        signals = LaneSignals()
        update_lane_signals(
            signals,
            {"event": "action_execution_started", "skill": "move_agv"},
        )
        self.assertTrue(signals.action_started)
        self.assertEqual(signals.current_skill, "move_agv")
        update_lane_signals(
            signals,
            {
                "event": "action_succeeded",
                "skill": "move_agv",
                "physical_transition": False,
            },
        )
        self.assertTrue(signals.action_succeeded)
        self.assertFalse(signals.physical_transition)
        update_lane_signals(signals, {"event": "safe_stop_received"})
        self.assertTrue(signals.safe_stop_received)

    def test_repair_panels_make_policy_difference_explicit(self):
        unsafe = VisualTargets(False, 0.0, 1)
        baseline = panel_text(REPAIR, "baseline", unsafe, LaneSignals())
        embodied = panel_text(REPAIR, "embodied", unsafe, LaneSignals())
        self.assertIn("TRUST PLAN", baseline)
        self.assertIn("PRECONDITION FAILED", embodied)
        self.assertIn("DECISION: REPAIR", embodied)

    def test_false_success_panels_diverge_after_same_ros_success(self):
        observed = VisualTargets(True, 0.0, 2)
        baseline_signals = LaneSignals(action_succeeded=True, physical_transition=False)
        embodied_signals = LaneSignals(
            action_succeeded=True,
            physical_transition=False,
            safe_stop_received=True,
        )
        baseline = panel_text(FALSE_SUCCESS, "baseline", observed, baseline_signals)
        embodied = panel_text(FALSE_SUCCESS, "embodied", observed, embodied_signals)
        self.assertIn("FINAL: SUCCESS", baseline)
        self.assertIn("VERIFY: FAILED", embodied)
        self.assertIn("FINAL: STOP", embodied)


class RvizComparisonRunnerTests(unittest.TestCase):
    def test_comparison_scenarios_use_same_initial_state(self):
        for case in (REPAIR, FALSE_SUCCESS):
            definition = comparison_definition(case)
            self.assertEqual(
                definition.baseline_scenario["initial_state"],
                definition.embodied_scenario["initial_state"],
            )

    def test_comparison_endpoints_are_process_isolated(self):
        baseline = comparison_endpoints("baseline")
        embodied = comparison_endpoints("embodied")
        self.assertNotEqual(baseline.fake_robot_node, embodied.fake_robot_node)
        self.assertEqual(baseline.state_topic, "/comparison/baseline/state")
        self.assertEqual(embodied.state_topic, "/comparison/embodied/state")

    def test_baseline_success_is_middleware_only(self):
        accepted = CommandReceipt(
            True,
            "accepted",
            call_result={"status": "SUCCEEDED"},
        )
        rejected = CommandReceipt(
            False,
            "rejected",
            call_result={"status": "SUCCEEDED"},
        )
        aborted = CommandReceipt(
            True,
            "accepted",
            call_result={"status": "ABORTED"},
        )
        self.assertTrue(baseline_middleware_success(accepted))
        self.assertFalse(baseline_middleware_success(rejected))
        self.assertFalse(baseline_middleware_success(aborted))


if __name__ == "__main__":
    unittest.main()
