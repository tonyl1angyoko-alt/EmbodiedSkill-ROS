from __future__ import annotations

from collections import deque
from dataclasses import fields
from datetime import datetime, timezone
import json
import threading
import time
from typing import Any

from ..models.robot_state import RobotState


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_world() -> dict[str, Any]:
    return {
        "left_arm_ready": True,
        "right_arm_ready": True,
        "left_arm_safe": True,
        "right_arm_safe": True,
        "agv_ready": True,
        "agv_moving": False,
        "agv_position_m": 0.0,
        "lift_ready": True,
        "lift_height_mm": 100.0,
        "head_ready": True,
        "head_yaw_deg": 0.0,
        "head_pitch_deg": 0.0,
        "emergency_stop": False,
        "fault": None,
        "last_skill_result": None,
    }


def build_node() -> Any:
    """Build an independent deterministic robot process for ROS runtime tests."""

    from action_tutorials_interfaces.action import Fibonacci
    from rcl_interfaces.msg import SetParametersResult
    from rclpy.action import ActionServer, CancelResponse, GoalResponse
    from rclpy.callback_groups import ReentrantCallbackGroup
    from rclpy.node import Node
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String
    from std_srvs.srv import Trigger

    class FakeRobotNode(Node):
        """Process-isolated hidden world with ROS-only command and observation I/O.

        ``Fibonacci`` is used as a validation-only action lifecycle envelope.  Its
        integer goal is a correlation id; the typed JSON command is installed by
        the standard ROS parameter service before the goal is sent.  This avoids
        pretending the test protocol is a production robot action definition.
        """

        def __init__(self) -> None:
            super().__init__("embodied_skill_fake_robot")
            self._lock = threading.RLock()
            self._world = _default_world()
            self._sequence = 0
            self._scenario: dict[str, Any] = {}
            self._behaviors: dict[str, deque[dict[str, Any]]] = {}
            self._active_behavior: dict[int, dict[str, Any]] = {}
            self._command_envelope: dict[str, Any] = {}
            self._unknown_fields: set[str] = set()
            self._stale_fields: set[str] = set()
            self._observation_overrides: dict[str, Any] = {}
            self._conflicts: dict[str, tuple[Any, ...]] = {}
            self._refresh: dict[str, Any] = {}
            self._pending_observations: list[tuple[float, str]] = []
            self._events: list[dict[str, Any]] = []
            self._safe_stop_count = 0

            qos = QoSProfile(
                depth=20,
                reliability=ReliabilityPolicy.RELIABLE,
                durability=DurabilityPolicy.TRANSIENT_LOCAL,
            )
            self._state_publisher = self.create_publisher(
                String, "/embodied_skill/state", qos
            )
            self._event_publisher = self.create_publisher(
                String, "/embodied_skill/runtime_events", qos
            )
            self._capabilities_service = self.create_service(
                Trigger,
                "/embodied_skill/get_capabilities",
                self._get_capabilities,
            )
            self._safe_stop_service = self.create_service(
                Trigger, "/embodied_skill/safe_stop", self._safe_stop
            )
            self._oracle_service = self.create_service(
                Trigger,
                "/embodied_skill/test/get_hidden_state",
                self._get_hidden_state,
            )
            callback_group = ReentrantCallbackGroup()
            self._action_server = ActionServer(
                self,
                Fibonacci,
                "/embodied_skill/execute_skill",
                execute_callback=self._execute,
                goal_callback=self._accept_goal,
                cancel_callback=self._cancel_goal,
                callback_group=callback_group,
            )
            self.declare_parameter("scenario_json", "{}")
            self.declare_parameter("command_json", "{}")
            self.declare_parameter("refresh_request_json", "{}")
            self.add_on_set_parameters_callback(self._parameters_changed)
            self._pending_timer = self.create_timer(0.01, self._publish_due_observations)
            self._publish_observation("startup")

        def destroy_node(self) -> bool:
            self._action_server.destroy()
            return super().destroy_node()

        def _emit(self, event: str, **details: Any) -> None:
            record = {"event": event, "timestamp": _utc_now(), **details}
            with self._lock:
                self._events.append(record)
            message = String()
            message.data = json.dumps(record, sort_keys=True)
            self._event_publisher.publish(message)

        def _configure(self, scenario: dict[str, Any]) -> None:
            with self._lock:
                self._scenario = dict(scenario)
                self._world = {**_default_world(), **dict(scenario.get("initial_state", {}))}
                self._behaviors = {
                    name: deque(dict(item) for item in items)
                    for name, items in dict(scenario.get("behaviors", {})).items()
                }
                observation = dict(scenario.get("observation", {}))
                self._unknown_fields = set(observation.get("unknown_fields", ()))
                self._stale_fields = set(observation.get("stale_fields", ()))
                self._observation_overrides = dict(observation.get("overrides", {}))
                self._conflicts = {
                    key: tuple(items)
                    for key, items in dict(observation.get("conflicts", {})).items()
                }
                self._refresh = dict(scenario.get("refresh", {}))
                self._active_behavior.clear()
                self._command_envelope = {}
                self._pending_observations.clear()
                self._events.clear()
                self._safe_stop_count = 0
            self._emit("scenario_configured", scenario_id=scenario.get("id"))
            self._publish_observation("scenario_configured")

        def _parameters_changed(self, parameters: list[Any]) -> Any:
            result = SetParametersResult(successful=True)
            try:
                for parameter in parameters:
                    if parameter.name == "scenario_json":
                        self._configure(json.loads(parameter.value))
                    elif parameter.name == "command_json":
                        envelope = json.loads(parameter.value)
                        with self._lock:
                            self._command_envelope = envelope
                        self._emit(
                            "command_envelope_received",
                            request_id=envelope.get("request_id"),
                            skill=envelope.get("skill"),
                            arguments=envelope.get("arguments", {}),
                        )
                    elif parameter.name == "refresh_request_json":
                        self._refresh_observation(json.loads(parameter.value))
            except Exception as exc:
                result.successful = False
                result.reason = str(exc)
            return result

        def _state_message(self, reason: str) -> dict[str, Any]:
            with self._lock:
                stamp = _utc_now()
                known_names = {item.name for item in fields(RobotState)}
                excluded = {
                    "active_resources", "facts", "observed_at", "stale_fields",
                    "conflicts", "timestamp",
                }
                ordinary = {
                    key: value for key, value in self._world.items()
                    if key in known_names and key not in excluded
                }
                dynamic = {
                    key: value for key, value in self._world.items()
                    if key not in known_names
                }
                ordinary.update({
                    key: value for key, value in self._observation_overrides.items()
                    if key in known_names
                })
                dynamic.update({
                    key: value for key, value in self._observation_overrides.items()
                    if key not in known_names
                })
                for field_name in self._unknown_fields:
                    if field_name in ordinary:
                        ordinary[field_name] = None
                    else:
                        dynamic[field_name] = None
                values = {**ordinary, "facts": dynamic}
                observed_names = {
                    key for key, value in {**ordinary, **dynamic}.items()
                    if value is not None
                }
                state = RobotState(**values).copy(
                    timestamp=stamp,
                    observed_at={key: stamp for key in observed_names},
                    stale_fields=set(self._stale_fields),
                    conflicts=dict(self._conflicts),
                )
                self._sequence += 1
                return {
                    "sequence": self._sequence,
                    "reason": reason,
                    "published_at": stamp,
                    "state": state.to_dict(),
                }

        def _publish_observation(self, reason: str) -> None:
            payload = self._state_message(reason)
            message = String()
            message.data = json.dumps(payload, sort_keys=True)
            self._state_publisher.publish(message)
            self._emit(
                "observation_published",
                sequence=payload["sequence"],
                reason=reason,
                observed_at=payload["state"]["observed_at"],
                stale_fields=payload["state"]["stale_fields"],
            )

        def _schedule_observation(self, delay_s: float, reason: str) -> None:
            if delay_s <= 0.0:
                self._publish_observation(reason)
                return
            with self._lock:
                self._pending_observations.append((time.monotonic() + delay_s, reason))
            self._emit("observation_scheduled", delay_s=delay_s, reason=reason)

        def _publish_due_observations(self) -> None:
            now = time.monotonic()
            due: list[str] = []
            with self._lock:
                pending = []
                for deadline, reason in self._pending_observations:
                    if deadline <= now:
                        due.append(reason)
                    else:
                        pending.append((deadline, reason))
                self._pending_observations = pending
            for reason in due:
                self._publish_observation(reason)

        def _refresh_observation(self, request: dict[str, Any]) -> None:
            fields = set(request.get("fields", ()))
            succeeds = bool(self._refresh.get("succeeds", False))
            with self._lock:
                if succeeds:
                    self._world.update(dict(self._refresh.get("values", {})))
                    self._unknown_fields -= fields
                    self._stale_fields -= fields
                    for field_name in fields:
                        self._observation_overrides.pop(field_name, None)
            self._emit(
                "refresh_completed",
                request_id=request.get("request_id"),
                fields=sorted(fields),
                succeeded=succeeds,
            )
            delay_s = float(self._refresh.get("delay_s", 0.0))
            self._schedule_observation(delay_s, "active_refresh")

        def _get_capabilities(self, _request: Any, response: Any) -> Any:
            supported = {
                "retract_arm", "extend_arm", "move_agv", "set_lift", "set_head",
                "reject_move", "no_motion_move", "delayed_move", "guarded_inspection",
                "primary_route", "alternate_route", "timeout_move", "cancel_move",
            }
            observable = {
                "left_arm_ready", "right_arm_ready", "left_arm_safe",
                "right_arm_safe", "agv_ready", "agv_moving", "agv_position_m",
                "lift_ready", "lift_height_mm", "head_ready", "head_yaw_deg",
                "head_pitch_deg", "emergency_stop", "fault", "last_skill_result",
                "hazard_clear", "inspection_done", "arrived", "test_position",
                "cancel_position", "delayed_position", "no_motion_position",
                "reject_position",
            }
            response.success = True
            response.message = json.dumps({
                "backend": "ProcessIsolatedRos2FakeRobot",
                "runtime": "ros2-humble-action-topic-service",
                "skills": sorted(supported),
                "observable_fields": sorted(observable),
                "refreshable_fields": sorted(observable),
                "supports_safe_stop": True,
            }, sort_keys=True)
            self._emit("capabilities_queried")
            return response

        def _safe_stop(self, _request: Any, response: Any) -> Any:
            with self._lock:
                self._world["agv_moving"] = False
                self._safe_stop_count += 1
            self._emit("safe_stop_received", count=self._safe_stop_count)
            self._publish_observation("safe_stop")
            response.success = True
            response.message = "fake robot entered safe stop"
            return response

        def _get_hidden_state(self, _request: Any, response: Any) -> Any:
            with self._lock:
                payload = {
                    "world": dict(self._world),
                    "events": list(self._events),
                    "safe_stop_count": self._safe_stop_count,
                }
            response.success = True
            response.message = json.dumps(payload, sort_keys=True)
            return response

        def _next_behavior(self, skill_name: str) -> dict[str, Any]:
            with self._lock:
                queue = self._behaviors.get(skill_name)
                return dict(queue.popleft()) if queue else {"mode": "normal"}

        def _accept_goal(self, goal_request: Any) -> Any:
            request_id = int(goal_request.order)
            with self._lock:
                envelope = dict(self._command_envelope)
            if request_id <= 0 or envelope.get("request_id") != request_id:
                self._emit("action_goal_rejected", request_id=request_id, reason="missing envelope")
                return GoalResponse.REJECT
            skill_name = str(envelope.get("skill", ""))
            behavior = self._next_behavior(skill_name)
            if behavior.get("mode") == "reject":
                self._emit(
                    "action_goal_rejected", request_id=request_id,
                    skill=skill_name, reason=behavior.get("message", "scripted rejection"),
                )
                return GoalResponse.REJECT
            with self._lock:
                self._active_behavior[request_id] = behavior
            self._emit(
                "action_goal_accepted", request_id=request_id,
                skill=skill_name, behavior=behavior,
            )
            return GoalResponse.ACCEPT

        def _cancel_goal(self, goal_handle: Any) -> Any:
            self._emit("action_cancel_requested", request_id=int(goal_handle.request.order))
            return CancelResponse.ACCEPT

        def _apply_transition(self, skill: str, arguments: dict[str, Any]) -> None:
            with self._lock:
                if skill == "retract_arm":
                    arm = str(arguments["arm"])
                    self._world[f"{arm}_arm_safe"] = True
                    self._world[f"{arm}_arm_ready"] = True
                elif skill == "extend_arm":
                    self._world[f"{arguments['arm']}_arm_safe"] = False
                elif skill == "move_agv":
                    self._world["agv_position_m"] = float(
                        self._world.get("agv_position_m", 0.0)
                    ) + float(arguments["distance_m"])
                elif skill == "set_lift":
                    self._world["lift_height_mm"] = float(arguments["height_mm"])
                elif skill == "set_head":
                    if "yaw_deg" in arguments:
                        self._world["head_yaw_deg"] = float(arguments["yaw_deg"])
                    if "pitch_deg" in arguments:
                        self._world["head_pitch_deg"] = float(arguments["pitch_deg"])
                elif skill in {"primary_route", "alternate_route"}:
                    self._world["arrived"] = True
                elif skill == "guarded_inspection":
                    self._world["inspection_done"] = True
                elif skill == "timeout_move":
                    self._world["test_position"] = 1.0
                elif skill == "cancel_move":
                    self._world["cancel_position"] = 1.0
                elif skill == "delayed_move":
                    self._world["delayed_position"] = 1.0
                elif skill == "no_motion_move":
                    self._world["no_motion_position"] = 1.0
                elif skill == "reject_move":
                    self._world["reject_position"] = 1.0
                else:
                    raise ValueError(f"fake robot has no transition for {skill}")

        def _execute(self, goal_handle: Any) -> Any:
            request_id = int(goal_handle.request.order)
            with self._lock:
                envelope = dict(self._command_envelope)
                behavior = self._active_behavior.pop(request_id, {"mode": "normal"})
            skill_name = str(envelope["skill"])
            arguments = dict(envelope.get("arguments", {}))
            mode = str(behavior.get("mode", "normal"))
            duration_s = float(behavior.get("duration_s", 0.03))
            self._emit(
                "action_execution_started", request_id=request_id,
                skill=skill_name, behavior=mode,
            )
            started = time.monotonic()
            while mode == "stall" or time.monotonic() - started < duration_s:
                if goal_handle.is_cancel_requested:
                    goal_handle.canceled()
                    self._emit(
                        "action_canceled", request_id=request_id, skill=skill_name,
                        physical_transition=False,
                    )
                    self._publish_observation("action_canceled")
                    result = Fibonacci.Result()
                    result.sequence = [request_id, -2]
                    return result
                if mode != "stall":
                    progress = min(99, int(100 * (time.monotonic() - started) / duration_s))
                    feedback = Fibonacci.Feedback()
                    feedback.partial_sequence = [request_id, progress]
                    goal_handle.publish_feedback(feedback)
                time.sleep(0.01)
                if mode == "stall" and time.monotonic() - started > 10.0:
                    goal_handle.abort()
                    self._emit("action_aborted", request_id=request_id, skill=skill_name)
                    result = Fibonacci.Result()
                    result.sequence = [request_id, -1]
                    return result

            if mode == "abort":
                goal_handle.abort()
                self._emit("action_aborted", request_id=request_id, skill=skill_name)
                self._publish_observation("action_aborted")
                result = Fibonacci.Result()
                result.sequence = [request_id, -1]
                return result
            if mode == "toctou":
                with self._lock:
                    self._world[str(behavior.get("field", "left_arm_safe"))] = behavior.get(
                        "value", False
                    )
                self._emit(
                    "exogenous_state_change_before_transition",
                    request_id=request_id,
                    field=behavior.get("field", "left_arm_safe"),
                    value=behavior.get("value", False),
                )
            transitioned = mode not in {"no_motion", "fresh_spoof"}
            if transitioned:
                self._apply_transition(skill_name, arguments)
            self._emit(
                "physical_transition",
                request_id=request_id,
                skill=skill_name,
                applied=transitioned,
            )
            delay_s = float(behavior.get("observation_delay_s", 0.0))
            self._schedule_observation(delay_s, "post_action")
            goal_handle.succeed()
            self._emit(
                "action_succeeded", request_id=request_id,
                skill=skill_name, physical_transition=transitioned,
            )
            result = Fibonacci.Result()
            result.sequence = [request_id, 1 if transitioned else 0]
            return result

    return FakeRobotNode()


def main(args: list[str] | None = None) -> None:
    import rclpy
    from rclpy.executors import MultiThreadedExecutor

    rclpy.init(args=args)
    node = build_node()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
