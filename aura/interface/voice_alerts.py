from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


class LocalVoiceAnnouncer:
    """Optional OS-native text-to-speech with no cloud API or credential."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        platform_name: str | None = None,
        which: Callable[[str], str | None] = shutil.which,
        runner: Callable[..., Any] = subprocess.run,
    ) -> None:
        self.enabled = enabled
        self.platform_name = platform_name or sys.platform
        self.which = which
        self.runner = runner
        self.command = self._detect_command() if enabled else None

    @property
    def available(self) -> bool:
        return self.command is not None

    async def speak(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()[:280]
        if not normalized or self.command is None:
            return False
        await asyncio.to_thread(self._speak_sync, normalized)
        return True

    def _detect_command(self) -> tuple[str, ...] | None:
        if self.platform_name.startswith("win"):
            executable = self.which("powershell.exe") or self.which("powershell")
            if executable:
                script = (
                    "$voice=New-Object -ComObject SAPI.SpVoice;"
                    "$null=$voice.Speak($env:AURA_VOICE_TEXT)"
                )
                return (executable, "-NoProfile", "-NonInteractive", "-Command", script)
        elif self.platform_name == "darwin":
            executable = self.which("say")
            if executable:
                return (executable,)
        else:
            executable = self.which("spd-say")
            if executable:
                return (executable, "--wait")
        return None

    def _speak_sync(self, text: str) -> None:
        if self.command is None:
            return
        environment = dict(os.environ)
        environment["AURA_VOICE_TEXT"] = text
        command = self.command
        if not self.platform_name.startswith("win"):
            command = (*command, text)
        self.runner(
            command,
            env=environment,
            check=False,
            capture_output=True,
            timeout=30,
        )


class VoiceStatusMonitor:
    """Speak new shadow signals and research triggers from the audit status file."""

    def __init__(
        self,
        status_path: Path,
        announcer: LocalVoiceAnnouncer,
        *,
        poll_seconds: float = 3.0,
    ) -> None:
        if poll_seconds <= 0:
            raise ValueError("voice status poll_seconds must be positive")
        self.status_path = status_path
        self.announcer = announcer
        self.poll_seconds = poll_seconds
        self._last_decision_id: str | None = None
        self._last_trigger_count = 0

    async def run(self, stop: asyncio.Event) -> None:
        if not self.announcer.available:
            return
        await self.announcer.speak(
            "AURA autonomous research started. Real money and broker orders are disabled."
        )
        while not stop.is_set():
            payload = await asyncio.to_thread(self._read_status)
            if payload is not None:
                await self._announce_changes(payload)
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                continue

    def _read_status(self) -> dict[str, Any] | None:
        if not self.status_path.exists():
            return None
        try:
            payload = json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    async def _announce_changes(self, payload: dict[str, Any]) -> None:
        latest = payload.get("latest")
        if isinstance(latest, dict) and latest.get("actionable") is True:
            decision_id = str(latest.get("correlation_id") or "")
            if decision_id and decision_id != self._last_decision_id:
                self._last_decision_id = decision_id
                confidence = round(float(latest.get("confidence") or 0) * 100)
                await self.announcer.speak(
                    f"AURA shadow signal {latest.get('intent', 'flat')} for "
                    f"{latest.get('symbol', 'unknown')}, confidence {confidence} percent. "
                    "No order was sent."
                )
        counters = payload.get("counters")
        trigger_count = (
            int(counters.get("research_triggers") or 0)
            if isinstance(counters, dict)
            else 0
        )
        if trigger_count > self._last_trigger_count:
            self._last_trigger_count = trigger_count
            await self.announcer.speak(
                "AURA detected a learning threshold breach and queued research review."
            )
