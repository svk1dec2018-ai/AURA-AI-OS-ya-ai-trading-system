from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aura.persistence.broker_evidence_archive import (
    BrokerEvidenceArchive,
    BrokerEvidenceArchiveError,
)


def export_archive_checkpoint(
    archive_path: Path,
    checkpoint_path: Path,
) -> str:
    """Export a credential-free sealed prefix anchor without broker access."""

    sealed = BrokerEvidenceArchive(archive_path).export_checkpoint(checkpoint_path)
    return sealed.sha256


def verify_archive_checkpoint(
    archive_path: Path,
    checkpoint_path: Path,
) -> str:
    """Verify a previously exported anchor against the current archive prefix."""

    archive = BrokerEvidenceArchive(archive_path)
    sealed = archive.load_checkpoint(checkpoint_path)
    archive.verify_checkpoint(sealed)
    return sealed.sha256


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export or verify a credential-free Phase 11 evidence archive anchor"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("export", "verify"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("--archive", required=True, type=Path)
        command_parser.add_argument("--checkpoint", required=True, type=Path)
    args = parser.parse_args()

    try:
        if args.command == "export":
            digest = export_archive_checkpoint(args.archive, args.checkpoint)
            action = "exported"
        else:
            digest = verify_archive_checkpoint(args.archive, args.checkpoint)
            action = "verified"
    except (BrokerEvidenceArchiveError, OSError, ValueError) as exc:
        print(f"Broker evidence checkpoint failed: {exc}", file=sys.stderr)
        return 2

    print(
        f"Broker evidence checkpoint {action}: {digest}; "
        "execution authority remains disabled"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
