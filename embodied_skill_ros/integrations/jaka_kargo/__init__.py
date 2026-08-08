"""JAKA/Kargo integration boundary.

The laboratory-provided workspace and vendor SDK are external dependencies.  This
package contains only the EmbodiedSkill-owned adapter, state, capability, and test
harness code.
"""

from .capability_mapper import IntegrationCapabilityReport, JakaKargoCapabilityMapper
from .integration_config import (
    ArmCommandScope,
    JakaKargoEndpoints,
    JakaKargoIntegrationConfig,
)
from .interface_contracts import (
    AgvObservation,
    ArmObservation,
    AxisObservation,
    CancellationSupport,
    StopScope,
    TimeoutSemantics,
    TransportResult,
)
from .skill_adapter import JakaKargoBackend
from .state_provider import JakaKargoStateProvider

__all__ = [
    "AgvObservation",
    "ArmCommandScope",
    "ArmObservation",
    "AxisObservation",
    "CancellationSupport",
    "IntegrationCapabilityReport",
    "JakaKargoBackend",
    "JakaKargoCapabilityMapper",
    "JakaKargoEndpoints",
    "JakaKargoIntegrationConfig",
    "JakaKargoStateProvider",
    "StopScope",
    "TimeoutSemantics",
    "TransportResult",
]
