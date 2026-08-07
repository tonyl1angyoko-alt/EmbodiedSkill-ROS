import unittest

from embodied_skill_ros.backends.base_backend import (
    ParameterDomain, SkillSemantics,
)
from embodied_skill_ros.backends.mock_backend import MockRobotBackend, ObservationModel
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.base_skill import (
    DeclarativeSkill, EffectSpec, ParameterSpec, SkillContract,
)
from embodied_skill_ros.skills.registry import build_default_registry, SkillRegistry

from test_models_and_registry import ready_state


class EpistemicExecutionTests(unittest.TestCase):
    def _move(self, backend):
        registry = build_default_registry()
        return SkillExecutor(registry, backend).execute(
            TaskPlan("move", [PlanStep("move", "move_agv", {"distance_m": 1.0})])
        )

    def test_unknown_safety_field_refreshes_then_executes(self):
        backend = MockRobotBackend(
            ready_state(),
            ObservationModel(
                hidden_fields=frozenset({"right_arm_safe"}),
                refreshable_fields=frozenset({"right_arm_safe"}),
            ),
        )
        report = self._move(backend)
        self.assertTrue(report.success)
        self.assertIn("OBSERVE", report.trace.decisions)
        self.assertEqual([name for name, _ in backend.command_log], ["move_agv"])

    def test_stale_safety_field_refreshes_then_executes(self):
        backend = MockRobotBackend(
            ready_state(),
            ObservationModel(
                stale_fields=frozenset({"right_arm_safe"}),
                refreshable_fields=frozenset({"right_arm_safe"}),
            ),
        )
        report = self._move(backend)
        self.assertTrue(report.success)
        self.assertIn("OBSERVE", report.trace.decisions)

    def test_failed_refresh_never_dispatches_unsafe_motion(self):
        backend = MockRobotBackend(
            ready_state(),
            ObservationModel(
                hidden_fields=frozenset({"right_arm_safe"}),
                refreshable_fields=frozenset({"right_arm_safe"}),
                refresh_failures=(("right_arm_safe", 1),),
            ),
        )
        report = self._move(backend)
        self.assertFalse(report.success)
        self.assertNotIn("move_agv", [name for name, _ in backend.command_log])

    def test_permanent_unknown_safety_field_stops_before_command(self):
        backend = MockRobotBackend(
            ready_state(),
            ObservationModel(hidden_fields=frozenset({"right_arm_safe"})),
        )
        report = self._move(backend)
        self.assertFalse(report.success)
        self.assertEqual(backend.command_log, [])

    def test_unknown_noncritical_field_does_not_block(self):
        backend = MockRobotBackend(
            ready_state(head_yaw_deg=None),
            ObservationModel(hidden_fields=frozenset({"head_pitch_deg"})),
        )
        report = SkillExecutor(build_default_registry(), backend).execute(
            TaskPlan("head", [PlanStep("head", "set_head", {"yaw_deg": 15.0})])
        )
        self.assertTrue(report.success)

    def test_contradictory_safety_observations_do_not_pick_a_convenient_value(self):
        backend = MockRobotBackend(
            ready_state(),
            ObservationModel(
                contradictions=(("right_arm_safe", (True, False)),),
            ),
        )
        report = self._move(backend)
        self.assertFalse(report.success)
        self.assertEqual(backend.command_log, [])


class CapabilitySemanticsTests(unittest.TestCase):
    @staticmethod
    def _registry(allowed=frozenset()):
        registry = SkillRegistry()
        registry.register(DeclarativeSkill(SkillContract(
            "retract_one", "Retract exactly one arm.",
            {"arm": ParameterSpec(str, choices=("left", "right"))},
            frozenset({"arm"}), (),
            (EffectSpec("{arm}_arm_safe", value=True),), 1.0,
            allowed_backend_side_effects=allowed,
        )))
        return registry

    @staticmethod
    def _backend(domain=frozenset({"left", "right"})):
        backend = MockRobotBackend(ready_state(left_arm_safe=False, right_arm_safe=False))
        backend.register_handler(
            "retract_one",
            lambda _world, _args: {"left_arm_safe": True, "right_arm_safe": True},
            SkillSemantics(
                "retract_one",
                (ParameterDomain("arm", choices=domain),),
                frozenset({"left_arm_safe", "right_arm_safe"}),
            ),
        )
        return backend

    def test_unavoidable_bilateral_side_effect_is_rejected_preflight(self):
        backend = self._backend()
        report = SkillExecutor(self._registry(), backend).execute(
            TaskPlan("left only", [PlanStep("r", "retract_one", {"arm": "left"})])
        )
        self.assertFalse(report.success)
        self.assertIn("undeclared unavoidable effects", report.message)
        self.assertEqual(backend.command_log, [])

    def test_parameter_domain_mismatch_is_rejected_preflight(self):
        backend = self._backend(frozenset({"left"}))
        report = SkillExecutor(
            self._registry(frozenset({"left_arm_safe"})), backend
        ).execute(
            TaskPlan("right", [PlanStep("r", "retract_one", {"arm": "right"})])
        )
        self.assertFalse(report.success)
        self.assertIn("parameter domain rejects", report.message)
        self.assertEqual(backend.command_log, [])

    def test_explicitly_permitted_side_effect_allows_dispatch(self):
        backend = self._backend()
        registry = self._registry(frozenset({"left_arm_safe", "right_arm_safe"}))
        report = SkillExecutor(registry, backend).execute(
            TaskPlan("left with allowed bilateral effect", [
                PlanStep("r", "retract_one", {"arm": "left"})
            ])
        )
        self.assertTrue(report.success)
        self.assertEqual(backend.command_log[0][0], "retract_one")


if __name__ == "__main__":
    unittest.main()
