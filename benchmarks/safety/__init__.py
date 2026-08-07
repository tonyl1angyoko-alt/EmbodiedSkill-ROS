"""Hazard-driven, oracle-defined safety benchmark support."""

from .model import (
    ActionOracle,
    FaultClass,
    RecoveryAction,
    SafetyBenchmarkCatalog,
    SafetyOracle,
    SafetyPlanStep,
    SafetyScenario,
    load_safety_scenarios,
    validate_safety_scenarios,
)

__all__ = [
    "ActionOracle",
    "FaultClass",
    "RecoveryAction",
    "SafetyBenchmarkCatalog",
    "SafetyOracle",
    "SafetyPlanStep",
    "SafetyScenario",
    "load_safety_scenarios",
    "validate_safety_scenarios",
]
