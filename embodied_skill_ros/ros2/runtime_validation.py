from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable

from ..backends.base_backend import BackendCapabilities, RobotBackend, SkillSemantics
from ..execution.skill_executor import ExecutionReport, SkillExecutor
from ..grounding.plan_grounder import EmbodiedPlanGrounder
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt
from ..models.task_plan import PlanStep, TaskPlan
from ..planner.goal_replanner import GoalDirectedReplanner
from ..skills.base_skill import (
    DeclarativeSkill,
    EffectSpec,
    SkillContract,
    StatePredicate,
)
from ..skills.registry import SkillRegistry, build_default_registry
from .ros2_backend import Ros2RobotBackend


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, type):
        return value.__name__
    return value


def _contract(skill: Any) -> dict[str, Any]:
    contract = skill.contract
    parameters = {}
    for name, spec in contract.parameters.items():
        python_types = spec.python_type if isinstance(spec.python_type, tuple) else (spec.python_type,)
        parameters[name] = {
            "types": [item.__name__ for item in python_types],
            "required": spec.required,
            "minimum": spec.minimum,
            "maximum": spec.maximum,
            "choices": list(spec.choices),
        }
    effects = []
    for effect in contract.effects:
        item = {
            "field": effect.field,
            "operation": effect.operation,
            "argument": effect.argument,
            "when_argument": effect.when_argument,
            "tolerance": effect.tolerance,
        }
        if effect.argument is None:
            item["literal_value"] = effect.value
        effects.append(item)
    return {
        "name": contract.name,
        "description": contract.description,
        "parameters": parameters,
        "resources": sorted(contract.resources),
        "preconditions": [_jsonable(item) for item in contract.preconditions],
        "effects": _jsonable(effects),
        "timeout_s": contract.timeout_s,
        "recovery_policy": list(contract.recovery_policy),
        "allowed_backend_side_effects": sorted(contract.allowed_backend_side_effects),
    }


def _skill(
    name: str,
    effect_field: str,
    *,
    needs: tuple[tuple[str, Any, float | None], ...] = (),
    timeout_s: float = 1.0,
    policy: tuple[str, ...] = ("observe", "repair", "local_retry", "replan", "safe_stop"),
) -> DeclarativeSkill:
    return DeclarativeSkill(SkillContract(
        name=name,
        description=f"ROS2 validation-only declarative skill {name}",
        parameters={},
        resources=frozenset({name}),
        preconditions=tuple(
            StatePredicate(field, expected, f"NEED_{field.upper()}", field, max_age)
            for field, expected, max_age in needs
        ),
        effects=(EffectSpec(effect_field, value=True),),
        timeout_s=timeout_s,
        recovery_policy=policy,
    ))


def _single_registry(skill: DeclarativeSkill, *alternatives: DeclarativeSkill) -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(skill)
    for item in alternatives:
        registry.register(item)
    return registry


def _plan(
    scenario_id: str,
    skill_name: str,
    goal_field: str,
    arguments: dict[str, Any] | None = None,
    target: Any = True,
) -> TaskPlan:
    return TaskPlan(
        goal=f"{goal_field}={target!r}",
        steps=[PlanStep(f"{scenario_id.lower()}_step", skill_name, arguments or {})],
        plan_id=scenario_id,
        metadata={"goal_state": {goal_field: target}},
    )


class _CapabilityOverrideBackend(RobotBackend):
    def __init__(self, backend: Ros2RobotBackend, capabilities: BackendCapabilities):
        self.backend = backend
        self._capabilities = capabilities

    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def observe(self) -> RobotState:
        return self.backend.observe()

    def acquire(self, fields: set[str]) -> RobotState:
        return self.backend.acquire(fields)

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        return self.backend.command(skill_name, arguments)

    def stop(self) -> CommandReceipt:
        return self.backend.stop()


@dataclass
class _ScenarioRun:
    report: ExecutionReport
    evidence: dict[str, Any]
    hidden: dict[str, Any]


class FakeRobotProcess:
    def __init__(self) -> None:
        self.log_dir = Path(tempfile.mkdtemp(prefix="embodied_skill_ros2_logs."))
        self.log_path = self.log_dir / "fake_robot.log"
        environment = dict(os.environ)
        environment["ROS_LOG_DIR"] = str(self.log_dir / "ros")
        environment.setdefault("ROS_LOCALHOST_ONLY", "1")
        environment.setdefault("RCUTILS_COLORIZED_OUTPUT", "0")
        self._log = self.log_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "embodied_skill_ros.ros2.fake_robot_node"],
            stdout=self._log,
            stderr=subprocess.STDOUT,
            text=True,
            env=environment,
        )

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGINT)
            try:
                self.process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=3.0)
        self._log.close()

    def __enter__(self) -> "FakeRobotProcess":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


class Ros2RuntimeValidation:
    def __init__(self, backend: Ros2RobotBackend):
        self.backend = backend
        self.results: list[dict[str, Any]] = []

    @staticmethod
    def _goal_true(world: dict[str, Any], goal: dict[str, Any]) -> bool:
        for field_name, target in goal.items():
            actual = world.get(field_name)
            if isinstance(target, float):
                if not isinstance(actual, (int, float)) or abs(float(actual) - target) > 1e-3:
                    return False
            elif actual != target:
                return False
        return True

    def _execute(
        self,
        scenario: dict[str, Any],
        registry: SkillRegistry,
        plan: TaskPlan,
        *,
        expected_behavior: str,
        backend_view: RobotBackend | None = None,
        max_retries: int = 1,
        max_replans: int = 1,
        max_observation_attempts: int = 1,
        replanner: Callable[[TaskPlan, RobotState], TaskPlan | None] | None = None,
    ) -> _ScenarioRun:
        event_start = len(self.backend.events)
        observation_start = len(self.backend.observation_history)
        initial = self.backend.configure_scenario(scenario)
        selected_backend = backend_view or self.backend
        capabilities = selected_backend.capabilities()
        grounding = EmbodiedPlanGrounder(registry).ground(plan, initial, capabilities)
        executor = SkillExecutor(
            registry,
            selected_backend,
            max_retries=max_retries,
            max_replans=max_replans,
            max_observation_attempts=max_observation_attempts,
            replanner=replanner,
        )
        report = executor.execute(plan)
        final_observation = self.backend.observe()
        hidden = self.backend.test_snapshot()
        relevant_skill_names = {step.skill for step in report.plan.steps} | {
            step.skill for step in plan.steps
        }
        goal_state = plan.metadata.get("goal_state", {})
        oracle_goal_true = self._goal_true(hidden["world"], goal_state)
        task_completion = bool(report.success and oracle_goal_true)
        safe_handling = bool(
            expected_behavior == "SAFE_STOP"
            and not report.success
            and report.decision == "STOP"
        )
        evidence = {
            "id": scenario["id"],
            "expected_behavior": expected_behavior,
            "input_plan": plan.to_dict(),
            "final_plan": report.plan.to_dict(),
            "contracts": {
                name: _contract(registry.get(name)) for name in sorted(relevant_skill_names)
            },
            "initial_observation": initial.to_dict(),
            "pre_execution_grounding": {
                "valid": grounding.valid,
                "requires_stop": grounding.requires_stop,
                "issues": [_jsonable(item) for item in grounding.issues],
            },
            "capability_preflight": _jsonable(capabilities),
            "report": {
                "success": report.success,
                "decision": report.decision,
                "message": report.message,
                "results": [_jsonable(item) for item in report.results],
                "trace": report.trace.to_dict() if report.trace else None,
            },
            "ros_events": self.backend.events[event_start:],
            "observation_history": self.backend.observation_history[observation_start:],
            "post_execution_observation": final_observation.to_dict(),
            "independent_ros_oracle": hidden,
            "scores": {
                "oracle_goal_true": oracle_goal_true,
                "task_completion": task_completion,
                "correct_safe_handling": safe_handling,
            },
        }
        return _ScenarioRun(report, evidence, hidden)

    @staticmethod
    def _events(evidence: dict[str, Any], name: str, *, source: str | None = None) -> list[dict[str, Any]]:
        return [
            item for item in evidence["ros_events"]
            if item.get("event") == name and (source is None or item.get("source") == source)
        ]

    def _record(
        self,
        run: _ScenarioRun,
        checks: dict[str, bool],
        *,
        status: str = "PASSED",
        notes: str = "",
    ) -> dict[str, Any]:
        failed = [name for name, passed in checks.items() if not passed]
        run.evidence["checks"] = checks
        run.evidence["passed"] = not failed
        run.evidence["status"] = status if not failed else "FAILED"
        run.evidence["failed_checks"] = failed
        if notes:
            run.evidence["notes"] = notes
        self.results.append(run.evidence)
        return run.evidence

    def r1_nominal(self) -> dict[str, Any]:
        registry = build_default_registry()
        plan = _plan("R1", "set_head", "head_yaw_deg", {"yaw_deg": 25.0}, 25.0)
        run = self._execute({"id": "R1_nominal"}, registry, plan, expected_behavior="COMPLETE")
        return self._record(run, {
            "task_completed": run.evidence["scores"]["task_completion"],
            "action_succeeded": bool(self._events(run.evidence, "action_result")),
            "physical_transition_observed": run.hidden["world"]["head_yaw_deg"] == 25.0,
        })

    def r2_rejection(self) -> dict[str, Any]:
        skill = _skill("reject_move", "reject_position", policy=("safe_stop",))
        registry = _single_registry(skill)
        run = self._execute(
            {
                "id": "R2_command_rejection",
                "initial_state": {"reject_position": False},
                "behaviors": {"reject_move": [{"mode": "reject"}]},
            },
            registry,
            _plan("R2", "reject_move", "reject_position"),
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "stopped": run.evidence["scores"]["correct_safe_handling"],
            "goal_rejected": bool(self._events(run.evidence, "action_goal_rejected")),
            "no_physical_effect": run.hidden["world"]["reject_position"] is False,
        })

    def r3_accepted_no_motion(self) -> dict[str, Any]:
        skill = _skill("no_motion_move", "no_motion_position", policy=("safe_stop",))
        registry = _single_registry(skill)
        run = self._execute(
            {
                "id": "R3_accepted_no_motion",
                "initial_state": {"no_motion_position": False},
                "behaviors": {"no_motion_move": [{"mode": "no_motion"}]},
            },
            registry,
            _plan("R3", "no_motion_move", "no_motion_position"),
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        accepted = any(
            item.get("event") == "action_goal_response" and item.get("accepted")
            for item in run.evidence["ros_events"]
        )
        result = run.report.results[0] if run.report.results else None
        return self._record(run, {
            "ros_goal_accepted": accepted,
            "ros_action_succeeded": any(
                item.get("event") == "action_result" and item.get("status") == "SUCCEEDED"
                for item in run.evidence["ros_events"]
            ),
            "verifier_rejected": bool(result and not result.physical_outcome_achieved),
            "oracle_confirms_no_motion": run.hidden["world"]["no_motion_position"] is False,
            "system_stopped": run.evidence["scores"]["correct_safe_handling"],
        }, notes="Transport/action success was not treated as physical success.")

    def r4_delayed_observation(self) -> dict[str, Any]:
        skill = _skill("delayed_move", "delayed_position", policy=("safe_stop",))
        registry = _single_registry(skill)
        run = self._execute(
            {
                "id": "R4_delayed_observation",
                "initial_state": {"delayed_position": False},
                "behaviors": {
                    "delayed_move": [{"mode": "normal", "observation_delay_s": 0.20}]
                },
            },
            registry,
            _plan("R4", "delayed_move", "delayed_position"),
            expected_behavior="COMPLETE",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "observation_was_scheduled": bool(self._events(run.evidence, "observation_scheduled")),
            "adapter_waited_for_post_command_sample": bool(
                self._events(run.evidence, "post_command_observation")
            ),
            "task_completed": run.evidence["scores"]["task_completion"],
        })

    def _guarded(self, scenario_id: str, *, policy: tuple[str, ...]) -> tuple[SkillRegistry, TaskPlan]:
        skill = _skill(
            "guarded_inspection",
            "inspection_done",
            needs=(("hazard_clear", True, 0.25),),
            policy=policy,
        )
        return _single_registry(skill), _plan(
            scenario_id, "guarded_inspection", "inspection_done"
        )

    def r5_stale(self) -> dict[str, Any]:
        registry, plan = self._guarded("R5", policy=("observe", "safe_stop"))
        run = self._execute(
            {
                "id": "R5_stale_observation",
                "initial_state": {"hazard_clear": True, "inspection_done": False},
                "observation": {"stale_fields": ["hazard_clear"]},
                "refresh": {"succeeds": False},
            },
            registry,
            plan,
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "stale_detected": any(
                item.get("knowledge") == "STALE"
                for item in run.evidence["pre_execution_grounding"]["issues"]
            ),
            "refresh_attempted": bool(self._events(run.evidence, "refresh_completed")),
            "motion_blocked": not self._events(run.evidence, "action_goal_sent"),
            "safe_handling": run.evidence["scores"]["correct_safe_handling"],
        })

    def r6_unknown(self) -> dict[str, Any]:
        registry, plan = self._guarded("R6", policy=("safe_stop",))
        run = self._execute(
            {
                "id": "R6_unknown_safety",
                "initial_state": {"hazard_clear": True, "inspection_done": False},
                "observation": {"unknown_fields": ["hazard_clear"]},
            },
            registry,
            plan,
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "unknown_detected": any(
                item.get("knowledge") == "UNKNOWN"
                for item in run.evidence["pre_execution_grounding"]["issues"]
            ),
            "not_interpreted_as_safe": not run.report.success,
            "no_command": not self._events(run.evidence, "action_goal_sent"),
        })

    def r7_refresh_succeeds(self) -> dict[str, Any]:
        registry, plan = self._guarded("R7", policy=("observe", "safe_stop"))
        run = self._execute(
            {
                "id": "R7_refresh_succeeds",
                "initial_state": {"hazard_clear": True, "inspection_done": False},
                "observation": {"unknown_fields": ["hazard_clear"]},
                "refresh": {"succeeds": True, "values": {"hazard_clear": True}},
            },
            registry,
            plan,
            expected_behavior="COMPLETE",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "refresh_succeeded": any(
                item.get("event") == "refresh_completed" and item.get("succeeded")
                for item in run.evidence["ros_events"]
            ),
            "observation_preceded_command": bool(
                run.report.trace and run.report.trace.decisions[0] == "OBSERVE"
            ),
            "task_completed": run.evidence["scores"]["task_completion"],
        })

    def r8_refresh_fails(self) -> dict[str, Any]:
        registry, plan = self._guarded("R8", policy=("observe", "safe_stop"))
        run = self._execute(
            {
                "id": "R8_refresh_fails",
                "initial_state": {"hazard_clear": True, "inspection_done": False},
                "observation": {"unknown_fields": ["hazard_clear"]},
                "refresh": {"succeeds": False},
            },
            registry,
            plan,
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "refresh_failed": any(
                item.get("event") == "refresh_completed" and not item.get("succeeded")
                for item in run.evidence["ros_events"]
            ),
            "no_guessed_execution": not self._events(run.evidence, "action_goal_sent"),
            "safe_handling": run.evidence["scores"]["correct_safe_handling"],
        })

    def r9_transient_retry(self) -> dict[str, Any]:
        registry = build_default_registry()
        run = self._execute(
            {
                "id": "R9_transient_actuator_failure",
                "behaviors": {
                    "set_head": [{"mode": "no_motion"}, {"mode": "normal"}]
                },
            },
            registry,
            _plan("R9", "set_head", "head_yaw_deg", {"yaw_deg": 30.0}, 30.0),
            expected_behavior="COMPLETE",
            max_retries=1,
            max_replans=0,
        )
        decisions = run.report.trace.decisions if run.report.trace else []
        run.evidence["recovery_classification"] = "RETRY" if "LOCAL_RETRY" in decisions else None
        return self._record(run, {
            "two_action_attempts": len(self._events(run.evidence, "action_goal_response")) == 2,
            "classified_retry": run.evidence["recovery_classification"] == "RETRY",
            "not_replan": "REPLAN" not in decisions,
            "task_completed": run.evidence["scores"]["task_completion"],
        })

    def r10_generic_repair(self) -> dict[str, Any]:
        registry = build_default_registry()
        run = self._execute(
            {
                "id": "R10_generic_repair",
                "initial_state": {"left_arm_safe": False, "agv_position_m": 0.0},
            },
            registry,
            _plan("R10", "move_agv", "agv_position_m", {"distance_m": 1.0}, 1.0),
            expected_behavior="COMPLETE",
            max_retries=0,
            max_replans=0,
        )
        skills = [step.skill for step in run.report.plan.steps]
        inserted = [step for step in run.report.plan.steps if step.inserted_by]
        return self._record(run, {
            "contract_effect_repair_inserted": skills == ["retract_arm", "move_agv"],
            "repair_provenance": bool(inserted and inserted[0].inserted_by.startswith("PlanRepairer:")),
            "repair_decision": bool(run.report.trace and "REPAIR" in run.report.trace.decisions),
            "task_completed": run.evidence["scores"]["task_completion"],
        })

    def r11_replan(self) -> dict[str, Any]:
        primary = _skill(
            "primary_route", "arrived", policy=("replan", "safe_stop")
        )
        alternate = _skill(
            "alternate_route", "arrived", policy=("safe_stop",)
        )
        registry = _single_registry(primary, alternate)
        plan = _plan("R11", "primary_route", "arrived")
        run = self._execute(
            {
                "id": "R11_genuine_replan",
                "initial_state": {"arrived": False},
                "behaviors": {"primary_route": [{"mode": "no_motion"}]},
            },
            registry,
            plan,
            expected_behavior="COMPLETE",
            max_retries=0,
            max_replans=1,
            replanner=GoalDirectedReplanner(registry),
        )

        retry_primary = _skill(
            "primary_route", "arrived", policy=("local_retry", "safe_stop")
        )
        counter_registry = _single_registry(retry_primary)
        counter = self._execute(
            {
                "id": "R11_retry_only_counterfactual",
                "initial_state": {"arrived": False},
                "behaviors": {
                    "primary_route": [
                        {"mode": "no_motion"},
                        {"mode": "no_motion"},
                        {"mode": "no_motion"},
                    ]
                },
            },
            counter_registry,
            plan,
            expected_behavior="SAFE_STOP",
            max_retries=2,
            max_replans=0,
        )
        run.evidence["retry_only_counterfactual"] = counter.evidence
        return self._record(run, {
            "structural_replan": (
                run.report.decision == "REPLAN"
                and [step.skill for step in run.report.plan.steps] == ["alternate_route"]
            ),
            "alternate_completed": run.evidence["scores"]["task_completion"],
            "retry_only_fails": (
                not counter.report.success and counter.hidden["world"]["arrived"] is False
            ),
        })

    def r12_capability_mismatch(self) -> dict[str, Any]:
        registry = build_default_registry()
        base = self.backend.capabilities()
        mismatch = BackendCapabilities(
            backend_name="BilateralArmRos2Adapter",
            supported_skills=base.supported_skills,
            observable_fields=base.observable_fields,
            supports_safe_stop=base.supports_safe_stop,
            runtime=base.runtime,
            refreshable_fields=base.refreshable_fields,
            skill_semantics=(SkillSemantics(
                "retract_arm",
                unavoidable_effect_fields=frozenset({"left_arm_safe", "right_arm_safe"}),
            ),),
        )
        view = _CapabilityOverrideBackend(self.backend, mismatch)
        run = self._execute(
            {"id": "R12_capability_mismatch", "initial_state": {"left_arm_safe": False}},
            registry,
            _plan("R12", "retract_arm", "left_arm_safe", {"arm": "left"}),
            expected_behavior="SAFE_STOP",
            backend_view=view,
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "semantic_mismatch_detected": any(
                item.get("code") == "BACKEND_SEMANTIC_MISMATCH"
                for item in run.evidence["pre_execution_grounding"]["issues"]
            ),
            "rejected_before_transmission": not self._events(run.evidence, "action_goal_sent"),
            "safe_handling": run.evidence["scores"]["correct_safe_handling"],
        })

    def r13_timeout(self) -> dict[str, Any]:
        skill = _skill(
            "timeout_move", "test_position", timeout_s=0.12,
            policy=("local_retry", "safe_stop"),
        )
        registry = _single_registry(skill)
        previous_timeout = self.backend.action_timeout_s
        self.backend.action_timeout_s = 0.16
        try:
            run = self._execute(
                {
                    "id": "R13_timeout",
                    "initial_state": {"test_position": False},
                    "behaviors": {
                        "timeout_move": [{"mode": "stall"}, {"mode": "normal"}]
                    },
                },
                registry,
                _plan("R13", "timeout_move", "test_position"),
                expected_behavior="COMPLETE",
                max_retries=1,
                max_replans=0,
            )
        finally:
            self.backend.action_timeout_s = previous_timeout
        decisions = run.report.trace.decisions if run.report.trace else []
        return self._record(run, {
            "timeout_recorded": bool(run.report.results and run.report.results[0].timed_out),
            "ros_cancel_sent": bool(self._events(run.evidence, "action_cancel_response")),
            "recovery_is_retry": "LOCAL_RETRY" in decisions and "REPLAN" not in decisions,
            "second_attempt_completed": run.evidence["scores"]["task_completion"],
        })

    def r14_cancellation(self) -> dict[str, Any]:
        skill = _skill(
            "cancel_move", "cancel_position", timeout_s=5.0, policy=("safe_stop",)
        )
        registry = _single_registry(skill)
        plan = _plan("R14", "cancel_move", "cancel_position")
        event_start = len(self.backend.events)
        observation_start = len(self.backend.observation_history)
        initial = self.backend.configure_scenario({
            "id": "R14_cancellation",
            "initial_state": {"cancel_position": False},
            "behaviors": {"cancel_move": [{"mode": "normal", "duration_s": 2.0}]},
        })
        grounding = EmbodiedPlanGrounder(registry).ground(
            plan, initial, self.backend.capabilities()
        )
        executor = SkillExecutor(registry, self.backend, max_retries=0, max_replans=0)
        holder: dict[str, ExecutionReport] = {}
        failure: list[BaseException] = []

        def run_executor() -> None:
            try:
                holder["report"] = executor.execute(plan)
            except BaseException as exc:  # surfaced in the main validation thread
                failure.append(exc)

        self.backend.current_goal_event.clear()
        thread = threading.Thread(target=run_executor, name="r14-core-executor")
        thread.start()
        goal_became_active = self.backend.current_goal_event.wait(3.0)
        cancel_accepted = self.backend.cancel_current_goal() if goal_became_active else False
        thread.join(timeout=6.0)
        if failure:
            raise failure[0]
        if thread.is_alive() or "report" not in holder:
            raise TimeoutError("R14 executor did not terminate after cancellation")
        report = holder["report"]
        final_observation = self.backend.observe()
        hidden = self.backend.test_snapshot()
        events = self.backend.events[event_start:]
        evidence = {
            "id": "R14_cancellation",
            "expected_behavior": "SAFE_STOP",
            "input_plan": plan.to_dict(),
            "final_plan": report.plan.to_dict(),
            "contracts": {"cancel_move": _contract(skill)},
            "initial_observation": initial.to_dict(),
            "pre_execution_grounding": {
                "valid": grounding.valid,
                "requires_stop": grounding.requires_stop,
                "issues": [_jsonable(item) for item in grounding.issues],
            },
            "capability_preflight": _jsonable(self.backend.capabilities()),
            "report": {
                "success": report.success,
                "decision": report.decision,
                "message": report.message,
                "results": [_jsonable(item) for item in report.results],
                "trace": report.trace.to_dict() if report.trace else None,
            },
            "ros_events": events,
            "observation_history": self.backend.observation_history[observation_start:],
            "post_execution_observation": final_observation.to_dict(),
            "independent_ros_oracle": hidden,
            "scores": {
                "oracle_goal_true": hidden["world"]["cancel_position"] is True,
                "task_completion": False,
                "correct_safe_handling": not report.success and report.decision == "STOP",
            },
        }
        run = _ScenarioRun(report, evidence, hidden)
        return self._record(run, {
            "goal_became_active": goal_became_active,
            "cancel_accepted": cancel_accepted,
            "ros_terminal_canceled": any(
                item.get("event") == "action_result" and item.get("status") == "CANCELED"
                for item in events
            ),
            "no_partial_transition": hidden["world"]["cancel_position"] is False,
            "epistemic_state_coherent": final_observation.raw_value("cancel_position") is False,
            "safe_stop_after_cancel": hidden["safe_stop_count"] >= 1,
        })

    def r15_safe_stop(self) -> dict[str, Any]:
        registry = build_default_registry()
        run = self._execute(
            {
                "id": "R15_safe_stop",
                "initial_state": {"emergency_stop": True, "agv_position_m": 0.0},
            },
            registry,
            _plan("R15", "move_agv", "agv_position_m", {"distance_m": 1.0}, 1.0),
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        return self._record(run, {
            "terminal_decision_safe_stop": run.report.decision == "STOP",
            "emergency_stop_detected": any(
                item.get("code") == "EMERGENCY_STOP"
                for item in run.evidence["pre_execution_grounding"]["issues"]
            ),
            "prohibited_action_not_sent": not self._events(run.evidence, "action_goal_sent"),
            "physical_position_unchanged": run.hidden["world"]["agv_position_m"] == 0.0,
        })

    def limitation_toctou(self) -> dict[str, Any]:
        registry = build_default_registry()
        run = self._execute(
            {
                "id": "L1_toctou_after_fresh_observation",
                "initial_state": {"left_arm_safe": True, "agv_position_m": 0.0},
                "behaviors": {
                    "move_agv": [{
                        "mode": "toctou", "field": "left_arm_safe", "value": False,
                    }]
                },
            },
            registry,
            _plan("L1", "move_agv", "agv_position_m", {"distance_m": 1.0}, 1.0),
            expected_behavior="COMPLETE",
            max_retries=0,
            max_replans=0,
        )
        unsafe_execution = bool(
            run.report.success
            and run.hidden["world"]["left_arm_safe"] is False
            and run.hidden["world"]["agv_position_m"] == 1.0
        )
        run.evidence["unsafe_execution"] = unsafe_execution
        return self._record(
            run,
            {
                "fresh_precondition_was_seen": run.evidence["pre_execution_grounding"]["valid"],
                "world_changed_before_command_transition": bool(
                    self._events(run.evidence, "exogenous_state_change_before_transition")
                ),
                "freshness_alone_failed": unsafe_execution,
            },
            status="EXPECTED_LIMITATION_REPRODUCED",
            notes=(
                "The runtime guard and action server do not share an atomic lease; "
                "a fresh sample can become false before physical transition."
            ),
        )

    def limitation_fresh_spoof(self) -> dict[str, Any]:
        registry = build_default_registry()
        plan = _plan("L2", "set_head", "head_yaw_deg", {"yaw_deg": 25.0}, 25.0)
        run = self._execute(
            {
                "id": "L2_fresh_sensor_spoof",
                "initial_state": {"head_yaw_deg": 0.0},
                "observation": {"overrides": {"head_yaw_deg": 25.0}},
                "behaviors": {"set_head": [{"mode": "fresh_spoof"}]},
            },
            registry,
            plan,
            expected_behavior="SAFE_STOP",
            max_retries=0,
            max_replans=0,
        )
        false_positive = bool(
            run.report.success and run.hidden["world"]["head_yaw_deg"] == 0.0
        )
        run.evidence["unsafe_execution"] = false_positive
        return self._record(
            run,
            {
                "ros_observation_was_fresh": not run.evidence["post_execution_observation"]["stale_fields"],
                "executor_false_positive": false_positive,
                "oracle_rejects_goal": not run.evidence["scores"]["oracle_goal_true"],
            },
            status="EXPECTED_LIMITATION_REPRODUCED",
            notes="ROS runtime preserves the frozen single-source trust-model limitation.",
        )

    def run_all(self) -> dict[str, Any]:
        required = [
            self.r1_nominal(),
            self.r2_rejection(),
            self.r3_accepted_no_motion(),
            self.r4_delayed_observation(),
            self.r5_stale(),
            self.r6_unknown(),
            self.r7_refresh_succeeds(),
            self.r8_refresh_fails(),
            self.r9_transient_retry(),
            self.r10_generic_repair(),
            self.r11_replan(),
            self.r12_capability_mismatch(),
            self.r13_timeout(),
            self.r14_cancellation(),
            self.r15_safe_stop(),
        ]
        limitations = [self.limitation_toctou(), self.limitation_fresh_spoof()]
        return {
            "schema_version": 1,
            "transport": {
                "observation": "std_msgs/msg/String topic with timestamped JSON",
                "command_lifecycle": "action_tutorials_interfaces/action/Fibonacci validation envelope",
                "configuration_and_refresh": "rcl_interfaces/srv/SetParameters",
                "capabilities_safe_stop_oracle": "std_srvs/srv/Trigger",
                "process_isolation": True,
            },
            "required_scenarios": required,
            "limitations": limitations,
            "summary": {
                "required_passed": sum(bool(item["passed"]) for item in required),
                "required_total": len(required),
                "limitations_reproduced": sum(bool(item["passed"]) for item in limitations),
                "limitations_total": len(limitations),
                "all_required_passed": all(item["passed"] for item in required),
                "all_limitations_reproduced": all(item["passed"] for item in limitations),
            },
        }


def run_validation(output: Path | None = None) -> dict[str, Any]:
    with FakeRobotProcess() as fake_robot:
        with Ros2RobotBackend(
            action_timeout_s=1.0,
            observation_timeout_s=0.8,
            service_timeout_s=2.0,
        ) as backend:
            result = Ros2RuntimeValidation(backend).run_all()
        result["fake_robot"] = {
            "pid": fake_robot.process.pid,
            "shutdown_returncode": None,
            "log_path": str(fake_robot.log_path),
        }
    result["fake_robot"]["shutdown_returncode"] = fake_robot.process.returncode
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run process-separated ROS2 validation scenarios")
    parser.add_argument(
        "--output", type=Path,
        default=Path("local_validation_outputs/ros2_runtime_scenarios.json"),
    )
    args = parser.parse_args()
    result = run_validation(args.output)
    print(json.dumps(result["summary"], indent=2, sort_keys=True))
    print(f"evidence: {args.output}")
    return 0 if (
        result["summary"]["all_required_passed"]
        and result["summary"]["all_limitations_reproduced"]
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
