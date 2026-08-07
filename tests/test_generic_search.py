import unittest

from embodied_skill_ros.grounding.plan_grounder import EmbodiedPlanGrounder
from embodied_skill_ros.grounding.plan_repairer import PlanRepairer
from embodied_skill_ros.models.task_plan import PlanStep, TaskPlan
from embodied_skill_ros.skills.base_skill import (
    DeclarativeSkill, EffectSpec, SkillContract, StatePredicate,
)
from embodied_skill_ros.skills.registry import SkillRegistry

from test_models_and_registry import ready_state


def skill(name, *, needs=(), effects=()):
    return DeclarativeSkill(SkillContract(
        name=name,
        description=name,
        parameters={},
        resources=frozenset({name}),
        preconditions=tuple(
            StatePredicate(field, target, f"NEED_{field.upper()}", field)
            for field, target in needs
        ),
        effects=tuple(EffectSpec(field, value=value) for field, value in effects),
        timeout_s=1.0,
    ))


class GenericRepairSearchTests(unittest.TestCase):
    def test_multistep_backward_search_synthesizes_b_a_goal(self):
        registry = SkillRegistry()
        registry.register(skill("make_q", needs=(("r", True),), effects=(("q", True),)))
        registry.register(skill("make_p", needs=(("q", True),), effects=(("p", True),)))
        registry.register(skill("goal_action", needs=(("p", True),), effects=(("done", True),)))
        state = ready_state(r=True, q=False, p=False, done=False)
        plan = TaskPlan("done", [PlanStep("goal", "goal_action", {})])
        grounder = EmbodiedPlanGrounder(registry)
        repairer = PlanRepairer(registry)
        repaired = repairer.repair(plan, state, grounder.ground(plan, state))
        self.assertEqual(
            [step.skill for step in repaired.steps],
            ["make_q", "make_p", "goal_action"],
        )
        self.assertEqual(repairer.last_search_stats["selected_steps"], 2)

    def test_cycle_is_detected(self):
        registry = SkillRegistry()
        registry.register(skill("make_p", needs=(("q", True),), effects=(("p", True),)))
        registry.register(skill("make_q", needs=(("p", True),), effects=(("q", True),)))
        registry.register(skill("goal", needs=(("p", True),), effects=(("done", True),)))
        state = ready_state(p=False, q=False, done=False)
        plan = TaskPlan("done", [PlanStep("goal", "goal", {})])
        grounder = EmbodiedPlanGrounder(registry)
        repairer = PlanRepairer(registry)
        self.assertIsNone(repairer.repair(plan, state, grounder.ground(plan, state)))
        self.assertGreater(repairer.last_search_stats["cycles"], 0)

    def test_no_solution_is_explicit(self):
        registry = SkillRegistry()
        registry.register(skill("goal", needs=(("missing", True),), effects=(("done", True),)))
        state = ready_state(missing=False, done=False)
        plan = TaskPlan("done", [PlanStep("goal", "goal", {})])
        grounder = EmbodiedPlanGrounder(registry)
        repairer = PlanRepairer(registry)
        self.assertIsNone(repairer.repair(plan, state, grounder.ground(plan, state)))
        self.assertEqual(repairer.last_search_stats["candidates_considered"], 0)

    def test_depth_bound_prevents_unbounded_chain(self):
        registry = SkillRegistry()
        registry.register(skill("make_a", needs=(("b", True),), effects=(("a", True),)))
        registry.register(skill("make_b", needs=(("c", True),), effects=(("b", True),)))
        registry.register(skill("make_c", needs=(("d", True),), effects=(("c", True),)))
        registry.register(skill("goal", needs=(("a", True),), effects=(("done", True),)))
        state = ready_state(a=False, b=False, c=False, d=True, done=False)
        plan = TaskPlan("done", [PlanStep("goal", "goal", {})])
        grounder = EmbodiedPlanGrounder(registry)
        repairer = PlanRepairer(registry, max_depth=2)
        self.assertIsNone(repairer.repair(plan, state, grounder.ground(plan, state)))
        self.assertGreater(repairer.last_search_stats["depth_limit_hits"], 0)

    def test_shorter_candidate_path_is_selected(self):
        registry = SkillRegistry()
        registry.register(skill("long_p", needs=(("q", True),), effects=(("p", True),)))
        registry.register(skill("make_q", effects=(("q", True),)))
        registry.register(skill("short_p", effects=(("p", True),)))
        registry.register(skill("goal", needs=(("p", True),), effects=(("done", True),)))
        state = ready_state(p=False, q=False, done=False)
        plan = TaskPlan("done", [PlanStep("goal", "goal", {})])
        grounder = EmbodiedPlanGrounder(registry)
        repaired = PlanRepairer(registry).repair(plan, state, grounder.ground(plan, state))
        self.assertEqual([item.skill for item in repaired.steps], ["short_p", "goal"])

    def test_parallel_contradictory_effects_are_unsatisfiable(self):
        registry = SkillRegistry()
        registry.register(skill("heat", effects=(("temperature", "hot"),)))
        registry.register(skill("cool", effects=(("temperature", "cold"),)))
        plan = TaskPlan("contradiction", [
            PlanStep("heat", "heat", {}, parallel_group="g"),
            PlanStep("cool", "cool", {}, parallel_group="g"),
        ])
        report = EmbodiedPlanGrounder(registry).ground(
            plan, ready_state(temperature="ambient")
        )
        self.assertTrue(report.requires_stop)
        self.assertIn("PARALLEL_EFFECT_CONFLICT", {item.code for item in report.issues})


if __name__ == "__main__":
    unittest.main()
