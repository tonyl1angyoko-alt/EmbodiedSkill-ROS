from __future__ import annotations

from ..backends.base_backend import RobotBackend
from ..models.robot_state import RobotState


class StateManager:
    def __init__(self, backend: RobotBackend):
        self.backend = backend
        self._state = backend.observe()
        self._last_skill_result: str | None = self._state.last_skill_result

    @property
    def state(self) -> RobotState:
        return self._state.copy()

    def refresh(self) -> RobotState:
        self._state = self.backend.observe()
        if self._state.last_skill_result is None and self._last_skill_result is not None:
            self._state = self._state.copy(last_skill_result=self._last_skill_result)
        return self.state

    def acquire(self, fields: set[str]) -> RobotState:
        self._state = self.backend.acquire(fields)
        if self._state.last_skill_result is None and self._last_skill_result is not None:
            self._state = self._state.copy(last_skill_result=self._last_skill_result)
        return self.state

    def mark_result(self, result: str) -> RobotState:
        self._last_skill_result = result
        self._state = self._state.copy(last_skill_result=result)
        return self.state
