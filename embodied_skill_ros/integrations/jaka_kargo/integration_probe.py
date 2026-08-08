from __future__ import annotations

import argparse
import json

from .integration_config import JakaKargoIntegrationConfig
from .ros2_transport import JakaKargoRos2Transport
from .skill_adapter import JakaKargoBackend


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only probe of the external JAKA/Kargo ROS2 boundary."
    )
    parser.add_argument("--timeout", type=float, default=1.0)
    args = parser.parse_args(argv)
    config = JakaKargoIntegrationConfig(
        motion_enabled=False,
        whole_robot_estop_observable=False,
        service_timeout_s=args.timeout,
    )
    transport = JakaKargoRos2Transport(config.endpoints, discovery_timeout_s=args.timeout)
    backend = JakaKargoBackend(transport, config)
    try:
        payload = {
            "motion_enabled": False,
            "core_capabilities": {
                "backend": backend.capabilities().backend_name,
                "supported_skills": sorted(backend.capabilities().supported_skills or ()),
                "observable_fields": sorted(backend.capabilities().observable_fields or ()),
                "supports_safe_stop": backend.capabilities().supports_safe_stop,
            },
            "integration_capabilities": backend.integration_capabilities().to_dict(),
            "observation": backend.observe().to_dict(),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        backend.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
