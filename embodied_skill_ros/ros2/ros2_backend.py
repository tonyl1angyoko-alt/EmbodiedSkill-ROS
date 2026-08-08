from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import threading
import time
from typing import Any

from ..backends.base_backend import BackendCapabilities, RobotBackend, SkillSemantics
from ..models.robot_state import RobotState
from ..models.skill_result import CommandReceipt
from .state_codec import robot_state_from_dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Ros2EndpointNames:
    fake_robot_node: str = "/embodied_skill_fake_robot"
    state_topic: str = "/embodied_skill/state"
    event_topic: str = "/embodied_skill/runtime_events"
    action: str = "/embodied_skill/execute_skill"
    capabilities_service: str = "/embodied_skill/get_capabilities"
    safe_stop_service: str = "/embodied_skill/safe_stop"
    oracle_service: str = "/embodied_skill/test/get_hidden_state"

    @property
    def parameter_service(self) -> str:
        return f"{self.fake_robot_node}/set_parameters"


class Ros2RobotBackend(RobotBackend):
    """Synchronous core adapter over asynchronous, process-separated ROS I/O.

    The adapter never reads the fake robot's hidden state during execution.
    ``test_snapshot`` is an explicitly test-only oracle endpoint used by the
    scenario scorer after a run, analogous to the Mock benchmark oracle.
    """

    def __init__(
        self,
        *,
        action_timeout_s: float = 2.0,
        observation_timeout_s: float = 1.0,
        service_timeout_s: float = 2.0,
        refreshable_fields: frozenset[str] | None = None,
        supported_skills: frozenset[str] | None = None,
        skill_semantics: tuple[SkillSemantics, ...] = (),
        endpoints: Ros2EndpointNames = Ros2EndpointNames(),
    ) -> None:
        import rclpy
        from action_tutorials_interfaces.action import Fibonacci
        from rcl_interfaces.srv import SetParameters
        from rclpy.action import ActionClient
        from rclpy.context import Context
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String
        from std_srvs.srv import Trigger

        if action_timeout_s <= 0 or observation_timeout_s <= 0 or service_timeout_s <= 0:
            raise ValueError("ROS timeout values must be positive")
        self.action_timeout_s = action_timeout_s
        self.observation_timeout_s = observation_timeout_s
        self.service_timeout_s = service_timeout_s
        self.endpoints = endpoints
        self._rclpy = rclpy
        self._Fibonacci = Fibonacci
        self._String = String
        self._SetParameters = SetParameters
        self._Trigger = Trigger
        self._context = Context()
        rclpy.init(args=None, context=self._context)
        self._node = Node(
            f"embodied_skill_backend_{id(self) & 0xffff:x}", context=self._context
        )
        self._executor = MultiThreadedExecutor(num_threads=3, context=self._context)
        self._executor.add_node(self._node)
        self._spin_thread = threading.Thread(
            target=self._executor.spin,
            name="embodied-skill-ros2-backend",
            daemon=True,
        )
        self._spin_thread.start()

        qos = QoSProfile(
            depth=100,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._state_condition = threading.Condition()
        self._latest_state: RobotState | None = None
        self._sequence = 0
        self._observation_history: list[dict[str, Any]] = []
        self._events_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._request_id = 0
        self._required_observation_sequence: int | None = None
        self._goal_lock = threading.Lock()
        self._current_goal: Any = None
        self.current_goal_event = threading.Event()
        self._closed = False

        self._state_subscription = self._node.create_subscription(
            String, endpoints.state_topic, self._receive_state, qos
        )
        self._event_subscription = self._node.create_subscription(
            String, endpoints.event_topic, self._receive_event, qos
        )
        self._action_client = ActionClient(self._node, Fibonacci, endpoints.action)
        self._parameter_client = self._node.create_client(
            SetParameters, endpoints.parameter_service
        )
        self._capabilities_client = self._node.create_client(
            Trigger, endpoints.capabilities_service
        )
        self._safe_stop_client = self._node.create_client(
            Trigger, endpoints.safe_stop_service
        )
        self._oracle_client = self._node.create_client(
            Trigger, endpoints.oracle_service
        )
        try:
            self._wait_for_endpoints()
            remote = self._query_capabilities()
            remote_supported = frozenset(remote.get("skills", ()))
            remote_observable = frozenset(remote.get("observable_fields", ()))
            remote_refreshable = frozenset(remote.get("refreshable_fields", ()))
            self._capabilities = BackendCapabilities(
                backend_name=str(remote.get("backend", "Ros2RobotBackend")),
                supported_skills=(
                    supported_skills if supported_skills is not None else remote_supported
                ),
                observable_fields=remote_observable,
                supports_safe_stop=bool(remote.get("supports_safe_stop", True)),
                runtime=str(remote.get("runtime", "ros2-humble")),
                refreshable_fields=(
                    refreshable_fields
                    if refreshable_fields is not None
                    else remote_refreshable
                ),
                skill_semantics=skill_semantics,
            )
            self._wait_for_observation(0, self.observation_timeout_s * 3.0)
        except Exception:
            self.close()
            raise

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._events_lock:
            return [dict(item) for item in self._events]

    @property
    def observation_history(self) -> list[dict[str, Any]]:
        with self._state_condition:
            return [dict(item) for item in self._observation_history]

    def _record(self, event: str, **details: Any) -> None:
        with self._events_lock:
            self._events.append({
                "source": "ros2_backend_client",
                "event": event,
                "timestamp": _utc_now(),
                **details,
            })

    def _receive_state(self, message: Any) -> None:
        try:
            payload = json.loads(message.data)
            state = robot_state_from_dict(payload["state"])
            sequence = int(payload["sequence"])
        except Exception as exc:
            self._record("invalid_observation", error=str(exc))
            return
        received = {
            "sequence": sequence,
            "reason": payload.get("reason"),
            "published_at": payload.get("published_at"),
            "received_at": _utc_now(),
            "state": state.to_dict(),
        }
        with self._state_condition:
            if sequence >= self._sequence:
                self._sequence = sequence
                self._latest_state = state
            self._observation_history.append(received)
            self._state_condition.notify_all()
        self._record(
            "observation_received",
            sequence=sequence,
            reason=payload.get("reason"),
            observed_at=state.observed_at,
            stale_fields=sorted(state.stale_fields),
        )

    def _receive_event(self, message: Any) -> None:
        try:
            record = json.loads(message.data)
        except Exception as exc:
            self._record("invalid_runtime_event", error=str(exc))
            return
        with self._events_lock:
            self._events.append({"source": "fake_robot", **record})

    @staticmethod
    def _await_future(future: Any, timeout_s: float, operation: str) -> Any:
        completed = threading.Event()
        future.add_done_callback(lambda _future: completed.set())
        if not completed.wait(timeout_s):
            raise TimeoutError(f"ROS {operation} timed out after {timeout_s:.3f}s")
        exception = future.exception()
        if exception is not None:
            raise RuntimeError(f"ROS {operation} failed: {exception}")
        return future.result()

    def _wait_for_endpoints(self) -> None:
        deadline = time.monotonic() + self.service_timeout_s * 5.0
        clients = (
            (self._parameter_client, "parameter service"),
            (self._capabilities_client, "capabilities service"),
            (self._safe_stop_client, "safe-stop service"),
            (self._oracle_client, "test oracle service"),
        )
        for client, name in clients:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not client.wait_for_service(timeout_sec=remaining):
                raise TimeoutError(f"ROS {name} unavailable")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not self._action_client.wait_for_server(timeout_sec=remaining):
            raise TimeoutError("ROS execute action unavailable")
        self._record("endpoints_ready")

    def _call_trigger(self, client: Any, operation: str) -> Any:
        future = client.call_async(self._Trigger.Request())
        return self._await_future(future, self.service_timeout_s, operation)

    def _query_capabilities(self) -> dict[str, Any]:
        response = self._call_trigger(self._capabilities_client, "capability query")
        if not response.success:
            raise RuntimeError(f"capability query rejected: {response.message}")
        payload = json.loads(response.message)
        self._record("capability_response", capabilities=payload)
        return payload

    def _set_json_parameter(self, name: str, payload: dict[str, Any]) -> None:
        from rclpy.parameter import Parameter

        request = self._SetParameters.Request()
        request.parameters = [
            Parameter(name, Parameter.Type.STRING, json.dumps(payload)).to_parameter_msg()
        ]
        response = self._await_future(
            self._parameter_client.call_async(request),
            self.service_timeout_s,
            f"set {name}",
        )
        if not response.results or not response.results[0].successful:
            reason = response.results[0].reason if response.results else "missing response"
            raise RuntimeError(f"ROS parameter {name} rejected: {reason}")
        self._record("parameter_set", name=name, payload=payload)

    def _wait_for_observation(self, after_sequence: int, timeout_s: float) -> RobotState:
        deadline = time.monotonic() + timeout_s
        with self._state_condition:
            while self._latest_state is None or self._sequence <= after_sequence:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"no ROS observation newer than sequence {after_sequence}"
                    )
                self._state_condition.wait(remaining)
            return self._latest_state.copy()

    def configure_scenario(self, scenario: dict[str, Any]) -> RobotState:
        before = self._sequence
        self._set_json_parameter("scenario_json", scenario)
        state = self._wait_for_observation(before, self.observation_timeout_s * 2.0)
        self._record(
            "scenario_ready", scenario_id=scenario.get("id"), sequence=self._sequence
        )
        return state

    def capabilities(self) -> BackendCapabilities:
        return self._capabilities

    def observe(self) -> RobotState:
        required = self._required_observation_sequence
        if required is not None:
            try:
                state = self._wait_for_observation(required, self.observation_timeout_s)
                self._record(
                    "post_command_observation", required_after=required,
                    received_sequence=self._sequence,
                )
            except TimeoutError as exc:
                self._record("observation_wait_timeout", error=str(exc))
                with self._state_condition:
                    if self._latest_state is None:
                        raise
                    state = self._latest_state.copy()
            finally:
                self._required_observation_sequence = None
            return state
        with self._state_condition:
            if self._latest_state is None:
                return self._wait_for_observation(0, self.observation_timeout_s)
            return self._latest_state.copy()

    def acquire(self, fields: set[str]) -> RobotState:
        before = self._sequence
        self._request_id += 1
        request_id = self._request_id
        self._record(
            "refresh_requested", request_id=request_id, fields=sorted(fields)
        )
        self._set_json_parameter(
            "refresh_request_json",
            {"request_id": request_id, "fields": sorted(fields)},
        )
        try:
            return self._wait_for_observation(before, self.observation_timeout_s)
        except TimeoutError as exc:
            self._record("refresh_observation_timeout", error=str(exc))
            return self.observe()

    def _feedback(self, message: Any) -> None:
        sequence = list(message.feedback.partial_sequence)
        self._record("action_feedback", sequence=sequence)

    def command(self, skill_name: str, arguments: dict[str, Any]) -> CommandReceipt:
        from action_msgs.msg import GoalStatus

        self._request_id += 1
        request_id = self._request_id
        before_sequence = self._sequence
        envelope = {
            "request_id": request_id,
            "skill": skill_name,
            "arguments": dict(arguments),
            "sent_at": _utc_now(),
        }
        try:
            self._set_json_parameter("command_json", envelope)
            goal = self._Fibonacci.Goal()
            goal.order = request_id
            self._record(
                "action_goal_sent", request_id=request_id,
                skill=skill_name, arguments=dict(arguments),
            )
            goal_handle = self._await_future(
                self._action_client.send_goal_async(goal, feedback_callback=self._feedback),
                self.service_timeout_s,
                "action goal response",
            )
            if not goal_handle.accepted:
                self._record(
                    "action_goal_response", request_id=request_id,
                    skill=skill_name, accepted=False,
                )
                return CommandReceipt(False, "ROS action goal rejected")
            with self._goal_lock:
                self._current_goal = goal_handle
                self.current_goal_event.set()
            self._record(
                "action_goal_response", request_id=request_id,
                skill=skill_name, accepted=True,
            )
            result_future = goal_handle.get_result_async()
            try:
                result = self._await_future(
                    result_future, self.action_timeout_s, "action result"
                )
                timed_out = False
            except TimeoutError:
                self._record(
                    "action_timeout", request_id=request_id,
                    skill=skill_name, timeout_s=self.action_timeout_s,
                )
                cancel_response = self._await_future(
                    goal_handle.cancel_goal_async(),
                    self.service_timeout_s,
                    "action timeout cancellation",
                )
                self._record(
                    "action_cancel_response", request_id=request_id,
                    goals_canceling=len(cancel_response.goals_canceling),
                    reason="timeout",
                )
                result = self._await_future(
                    result_future, self.service_timeout_s, "canceled action result"
                )
                timed_out = True
            finally:
                with self._goal_lock:
                    self._current_goal = None
                    self.current_goal_event.clear()
            status_names = {
                GoalStatus.STATUS_SUCCEEDED: "SUCCEEDED",
                GoalStatus.STATUS_ABORTED: "ABORTED",
                GoalStatus.STATUS_CANCELED: "CANCELED",
            }
            status_name = status_names.get(result.status, f"STATUS_{result.status}")
            self._required_observation_sequence = before_sequence
            self._record(
                "action_result", request_id=request_id, skill=skill_name,
                goal_accepted=True, status=status_name,
                result_sequence=list(result.result.sequence),
                timed_out=timed_out,
            )
            message = f"ROS action goal accepted; terminal status {status_name}"
            return CommandReceipt(
                True,
                message,
                call_result={
                    "request_id": request_id,
                    "status": status_name,
                    "sequence": list(result.result.sequence),
                },
                timed_out=timed_out,
            )
        except Exception as exc:
            self._record(
                "action_transport_error", request_id=request_id,
                skill=skill_name, error=str(exc),
            )
            return CommandReceipt(False, f"ROS action transport error: {exc}")

    def cancel_current_goal(self) -> bool:
        with self._goal_lock:
            goal_handle = self._current_goal
        if goal_handle is None:
            self._record("external_cancel_skipped", reason="no active goal")
            return False
        response = self._await_future(
            goal_handle.cancel_goal_async(),
            self.service_timeout_s,
            "external action cancellation",
        )
        accepted = bool(response.goals_canceling)
        self._record("external_cancel_response", accepted=accepted)
        return accepted

    def stop(self) -> CommandReceipt:
        try:
            response = self._call_trigger(self._safe_stop_client, "safe stop")
            self._record(
                "safe_stop_response", accepted=bool(response.success),
                message=response.message,
            )
            return CommandReceipt(bool(response.success), response.message)
        except Exception as exc:
            self._record("safe_stop_transport_error", error=str(exc))
            return CommandReceipt(False, f"safe-stop transport error: {exc}")

    def test_snapshot(self) -> dict[str, Any]:
        response = self._call_trigger(self._oracle_client, "test oracle query")
        if not response.success:
            raise RuntimeError(f"test oracle rejected: {response.message}")
        snapshot = json.loads(response.message)
        self._record("test_oracle_queried_after_execution")
        return snapshot

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._executor.remove_node(self._node)
            self._executor.shutdown(timeout_sec=1.0)
        except Exception:
            pass
        try:
            self._node.destroy_node()
        except Exception:
            pass
        try:
            self._context.shutdown()
        except Exception:
            pass
        if self._spin_thread.is_alive():
            self._spin_thread.join(timeout=1.0)

    def __enter__(self) -> "Ros2RobotBackend":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()
