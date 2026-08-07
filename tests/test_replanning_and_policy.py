import unittest

from embodied_skill_ros.backends.mock_backend import (
    FaultEvent, MockRobotBackend, ObservationModel,
)
from embodied_skill_ros.execution.skill_executor import SkillExecutor
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.planner.goal_replanner import GoalDirectedReplanner
from embodied_skill_ros.skills.base_skill import (
    DeclarativeSkill, EffectSpec, SkillContract, StatePredicate,
)
from embodied_skill_ros.skills.registry import SkillRegistry

from test_models_and_registry import ready_state


def declarative(name, effect_field, *, needs=(), policy=None):
    kwargs = {}
    if policy is not None:
        kwargs["recovery_policy"] = policy
    return DeclarativeSkill(SkillContract(
        name, name, {}, frozenset({name}),
        tuple(
            StatePredicate(field, value, f"NEED_{field.upper()}", field)
            for field, value in needs
        ),
        (EffectSpec(effect_field, value=True),), 1.0,
        **kwargs,
    ))


class GenuineReplanningTests(unittest.TestCase):
    def _run_case(self, primary, alternative, effect_field, *, final_skill=None,
                  prerequisite_field=None):
        registry = SkillRegistry()
        registry.register(declarative(primary, prerequisite_field or effect_field))
        registry.register(declarative(alternative, prerequisite_field or effect_field))
        if final_skill:
            registry.register(declarative(
                final_skill, effect_field, needs=((prerequisite_field, True),)
            ))
        backend = MockRobotBackend(ready_state(**{
            effect_field: False,
            **({prerequisite_field: False} if prerequisite_field else {}),
        }))
        for name, field in ((primary, prerequisite_field or effect_field),
                            (alternative, prerequisite_field or effect_field)):
            backend.register_handler(name, lambda _world, _args, f=field: {f: True})
        if final_skill:
            backend.register_handler(
                final_skill, lambda _world, _args: {effect_field: True}
            )
        backend.inject_permanent(primary, FaultEvent("command_failure", "permanent outage"))
        steps = [PlanStep("primary", primary, {})]
        if final_skill:
            steps.append(PlanStep("goal", final_skill, {}))
        plan = TaskPlan(
            effect_field, steps,
            metadata={"goal_state": {effect_field: True}},
        )
        report = SkillExecutor(
            registry, backend, max_retries=1, max_replans=1,
            replanner=GoalDirectedReplanner(registry),
        ).execute(plan)
        self.assertTrue(report.success)
        self.assertEqual(report.decision, "REPLAN")
        self.assertIn("REPLAN", report.trace.decisions)
        replanned_skills = [step.skill for step in report.plan.steps]
        self.assertNotIn(primary, replanned_skills)
        self.assertIn(alternative, replanned_skills)
        self.assertTrue(report.plan.metadata["replan_structurally_changed"])

        counterfactual_backend = MockRobotBackend(ready_state(**{
            effect_field: False,
            **({prerequisite_field: False} if prerequisite_field else {}),
        }))
        counterfactual_backend.register_handler(
            primary, lambda _world, _args: {prerequisite_field or effect_field: True}
        )
        if final_skill:
            counterfactual_backend.register_handler(
                final_skill, lambda _world, _args: {effect_field: True}
            )
        counterfactual_backend.inject_permanent(
            primary, FaultEvent("command_failure", "permanent outage")
        )
        counterfactual = SkillExecutor(
            registry, counterfactual_backend, max_retries=2, max_replans=0,
        ).execute(plan)
        self.assertFalse(counterfactual.success)
        self.assertFalse(counterfactual_backend.oracle_state().raw_value(effect_field))
        return report

    def test_navigation_replans_to_backup_drive(self):
        self._run_case("primary_drive", "backup_drive", "arrived")

    def test_payload_replans_to_alternative_clamp(self):
        self._run_case("primary_lock", "backup_clamp", "payload_locked")

    def test_power_dead_path_changes_intermediate_subgoal(self):
        report = self._run_case(
            "main_power", "backup_power", "process_done",
            final_skill="run_process", prerequisite_field="power_available",
        )
        self.assertEqual(
            [step.skill for step in report.plan.steps],
            ["backup_power", "run_process"],
        )


class RecoveryPolicyMatrixTests(unittest.TestCase):
    def _single(self, policy, *, initial=None, observation_model=None):
        registry = SkillRegistry()
        registry.register(declarative("act", "done", policy=policy))
        backend = MockRobotBackend(
            initial or ready_state(done=False), observation_model
        )
        backend.register_handler("act", lambda _world, _args: {"done": True})
        return registry, backend, TaskPlan(
            "done", [PlanStep("act", "act", {})],
            metadata={"goal_state": {"done": True}},
        )

    def test_safe_stop_policy_overrides_transient_recoverability(self):
        registry, backend, plan = self._single(("safe_stop",))
        backend.inject("act", FaultEvent("physical_failure"))
        report = SkillExecutor(registry, backend, max_retries=5).execute(plan)
        self.assertFalse(report.success)
        self.assertEqual([name for name, _ in backend.command_log], ["act", "safe_stop"])

    def test_retry_alias_then_safe_stop_policy_retries_once(self):
        registry, backend, plan = self._single(("retry", "safe_stop"))
        backend.inject("act", FaultEvent("physical_failure"))
        report = SkillExecutor(registry, backend, max_retries=1).execute(plan)
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log], ["act", "act"])
        self.assertIn("LOCAL_RETRY", report.trace.decisions)

    def test_repair_policy_synthesizes_preparation(self):
        registry = SkillRegistry()
        registry.register(declarative("prepare", "ready"))
        registry.register(declarative(
            "act", "done", needs=(("ready", True),),
            policy=("repair", "replan", "safe_stop"),
        ))
        backend = MockRobotBackend(ready_state(ready=False, done=False))
        backend.register_handler("prepare", lambda _world, _args: {"ready": True})
        backend.register_handler("act", lambda _world, _args: {"done": True})
        report = SkillExecutor(registry, backend).execute(
            TaskPlan("done", [PlanStep("act", "act", {})])
        )
        self.assertTrue(report.success)
        self.assertEqual([name for name, _ in backend.command_log], ["prepare", "act"])
        self.assertIn("REPAIR", report.trace.decisions)

    def test_observe_then_repair_policy_observes_first(self):
        registry = SkillRegistry()
        registry.register(declarative(
            "act", "done", needs=(("ready", True),),
            policy=("observe", "repair", "safe_stop"),
        ))
        backend = MockRobotBackend(
            ready_state(ready=True, done=False),
            ObservationModel(
                stale_fields=frozenset({"ready"}),
                refreshable_fields=frozenset({"ready"}),
            ),
        )
        backend.register_handler("act", lambda _world, _args: {"done": True})
        report = SkillExecutor(registry, backend).execute(
            TaskPlan("done", [PlanStep("act", "act", {})])
        )
        self.assertTrue(report.success)
        self.assertEqual(report.trace.decisions[0], "OBSERVE")
        self.assertEqual([name for name, _ in backend.command_log], ["act"])


if __name__ == "__main__":
    unittest.main()
