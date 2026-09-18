from __future__ import annotations

import json

from .opensource_registry import PROJECTS


def main() -> None:
    payload = {
        "product": "AURA 2 Open-Source Fusion",
        "authority": {
            "external_research_can_trade": False,
            "external_research_can_change_risk": False,
            "risk_engine_bypass": False,
        },
        "sources": [
            {
                "key": project.key,
                "name": project.name,
                "repository": project.repository,
                "license": project.license_family,
                "integration_mode": project.preferred_mode,
                "direct_copy_allowed": project.direct_copy_allowed,
                "capabilities": list(project.capabilities),
            }
            for project in PROJECTS.values()
        ],
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
