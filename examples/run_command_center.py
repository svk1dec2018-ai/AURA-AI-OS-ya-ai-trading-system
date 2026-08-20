from __future__ import annotations

import os
from pathlib import Path

from aura.interface.web_command_center import CommandCenterConfig, CommandCenterService


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
    print(f"AURA Command Center listening on http://{config.host}:{config.port}")
    print("Safety mode: observation + governed research; paper/live HTTP controls disabled")
    CommandCenterService(config).run_forever()


if __name__ == "__main__":
    main()
