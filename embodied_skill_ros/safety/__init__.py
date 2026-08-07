"""Lightweight safety-case traceability artifacts; not runtime authorization."""

from .hazard_catalog import (
    CORE_SAFETY_MECHANISM_REFS,
    REQUIRED_HAZARD_IDS,
    SYSTEM_LEVEL_TOKEN,
    HazardCatalog,
    SafetyHazard,
    load_hazard_catalog,
    validate_hazard_catalog,
)

__all__ = [
    "SafetyHazard",
    "HazardCatalog",
    "load_hazard_catalog",
    "validate_hazard_catalog",
    "REQUIRED_HAZARD_IDS",
    "CORE_SAFETY_MECHANISM_REFS",
    "SYSTEM_LEVEL_TOKEN",
]
