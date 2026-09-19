import asyncio

import pytest

from aura.interface.voice_alerts import LocalVoiceAnnouncer, VoiceStatusMonitor


@pytest.mark.asyncio
async def test_windows_voice_uses_environment_not_shell_interpolation() -> None:
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))

    announcer = LocalVoiceAnnouncer(
        enabled=True,
        platform_name="win32",
        which=lambda name: "C:/Windows/powershell.exe" if name == "powershell.exe" else None,
        runner=runner,
    )

    assert announcer.available is True
    assert await announcer.speak("BTC $() ` test") is True
    command, kwargs = calls[0]
    assert command[0] == "C:/Windows/powershell.exe"
    assert kwargs["env"]["AURA_VOICE_TEXT"] == "BTC $() ` test"
    assert "shell" not in kwargs


@pytest.mark.asyncio
async def test_voice_monitor_announces_each_actionable_decision_once(tmp_path) -> None:
    spoken: list[str] = []

    class _Announcer:
        available = True

        async def speak(self, text: str) -> bool:
            spoken.append(text)
            return True

    status = tmp_path / "status.json"
    status.write_text(
        """{"latest":{"correlation_id":"one","actionable":true,"intent":"LONG","symbol":"BTC-USD","confidence":0.8},"counters":{"research_triggers":1}}""",
        encoding="utf-8",
    )
    monitor = VoiceStatusMonitor(status, _Announcer(), poll_seconds=0.01)
    stop = asyncio.Event()
    task = asyncio.create_task(monitor.run(stop))
    await asyncio.sleep(0.04)
    stop.set()
    await task

    assert sum("shadow signal" in item for item in spoken) == 1
    assert sum("threshold breach" in item for item in spoken) == 1
