import unittest

from embodied_skill_ros.grounding.constraint_checker import ConstraintChecker
from embodied_skill_ros.grounding.plan_grounder import EmbodiedPlanGrounder
from embodied_skill_ros.grounding.plan_repairer import PlanRepairer
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.registry import build_default_registry

from test_models_and_registry import ready_state


class GroundingAndRepairTests(unittest.TestCase):
    def setUp(self):
        self.registry = build_default_registry()
        self.grounder = EmbodiedPlanGrounder(self.registry)

    def test_preconditions_satisfied(self):
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        self.assertTrue(self.grounder.ground(plan, ready_state()).valid)

    def test_precondition_not_satisfied(self):
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        report = self.grounder.ground(plan, ready_state(right_arm_safe=False))
        self.assertFalse(report.valid)
        self.assertIn("RIGHT_ARM_UNSAFE_FOR_AGV", {issue.code for issue in report.issues})

    def test_unknown_precondition_is_not_assumed_safe(self):
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        self.assertFalse(self.grounder.ground(plan, ready_state(right_arm_safe=None)).valid)

    def test_resource_busy_detected(self):
        plan = TaskPlan("head", [PlanStep("s1", "set_head", {"yaw_deg": 2})])
        report = self.grounder.ground(plan, ready_state(active_resources={"head"}))
        self.assertIn("RESOURCE_BUSY", {issue.code for issue in report.issues})

    def test_parallel_resource_conflict_detected(self):
        steps = [
            PlanStep("s1", "retract_arm", {"arm": "left"}, parallel_group="g"),
            PlanStep("s2", "extend_arm", {"arm": "right"}, parallel_group="g"),
        ]
        violations = ConstraintChecker().check_parallel(
            steps, {name: self.registry.get(name) for name in self.registry.names()}
        )
        self.assertIn("PARALLEL_RESOURCE_CONFLICT", {v.code for v in violations})

    def test_body_conflict_detected(self):
        plan = TaskPlan("conflict", [
            PlanStep("s1", "extend_arm", {"arm": "right"}, parallel_group="g"),
            PlanStep("s2", "move_agv", {"distance_m": 1.0}, parallel_group="g"),
        ])
        report = self.grounder.ground(plan, ready_state())
        self.assertIn("BODY_CONFLICT", {issue.code for issue in report.issues})

    def test_repair_inserts_transport_pose(self):
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        state = ready_state(right_arm_safe=False)
        repaired = PlanRepairer().repair(plan, state, self.grounder.ground(plan, state))
        self.assertEqual([s.skill for s in repaired.steps], ["retract_arm", "move_agv"])
        self.assertEqual(repaired.steps[0].arguments, {"arm": "right"})

    def test_repair_serializes_parallel_plan(self):
        plan = TaskPlan("parallel", [
            PlanStep("s1", "set_head", {"yaw_deg": 5}, parallel_group="g"),
            PlanStep("s2", "set_head", {"pitch_deg": -5}, parallel_group="g"),
        ])
        report = self.grounder.ground(plan, ready_state())
        repaired = PlanRepairer().repair(plan, ready_state(), report)
        self.assertTrue(all(step.parallel_group is None for step in repaired.steps))

    def test_emergency_stop_is_nonrepairable(self):
        plan = TaskPlan("move", [PlanStep("s1", "move_agv", {"distance_m": 1.0})])
        report = self.grounder.ground(plan, ready_state(emergency_stop=True))
        self.assertTrue(report.requires_stop)

    def test_lift_plan_gets_arm_preparation(self):
        plan = TaskPlan("lift", [PlanStep("s1", "set_lift", {"height_mm": 300.0})])
        state = ready_state(left_arm_safe=False, right_arm_safe=False)
        repaired = PlanRepairer().repair(plan, state, self.grounder.ground(plan, state))
        self.assertEqual([s.skill for s in repaired.steps], ["retract_arm", "retract_arm", "set_lift"])

    def test_unverifiable_declared_effect_is_rejected(self):
        plan = TaskPlan("invented effect", [
            PlanStep("s1", "set_head", {"yaw_deg": 5}, {"object_grasped": True})
        ])
        report = self.grounder.ground(plan, ready_state())
        self.assertTrue(report.requires_stop)
        self.assertIn("UNVERIFIABLE_EXPECTED_EFFECT", {issue.code for issue in report.issues})


if __name__ == "__main__":
    unittest.main()
