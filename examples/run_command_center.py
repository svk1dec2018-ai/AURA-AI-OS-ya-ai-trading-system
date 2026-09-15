from __future__ import annotations

import os
from pathlib import Path

from aura.interface.web_command_center import CommandCenterConfig
from aura.interface.web_command_center_v2 import CommandCenterV2Service


def main() -> None:
    config = CommandCenterConfig(
        host=os.getenv("AURA_COMMAND_CENTER_HOST", "127.0.0.1"),
        port=int(os.getenv("AURA_COMMAND_CENTER_PORT", "8765")),
        queue_path=Path(
            os.getenv(
                "AURA_COMMAND_CENTER_QUEUE",
                "artifacts/operator/research_requests.jsonl",
            )
        ),
        api_token=os.getenv("AURA_COMMAND_CENTER_TOKEN") or None,
        owner_id=os.getenv("AURA_COMMAND_CENTER_OWNER_ID", "owner"),
    )
    print(f"AURA Command Center v2 listening on http://{config.host}:{config.port}")
    print("Safety mode: freshness-gated observation + governed research")
    print("Paper/live HTTP controls and broker order submission remain disabled")
    CommandCenterV2Service(config).run_forever()


if __name__ == "__main__":
    main()
