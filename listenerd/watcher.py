"""Watch for mic activity on macOS and run a session state machine."""
from __future__ import annotations

import enum
import time
from dataclasses import dataclass
from typing import Optional


class SessionState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    COOLDOWN = "cooldown"


@dataclass
class SessionStateMachine:
    """Pure state machine driven by tick(now, mic_on).

    Emits "start" when session starts, "stop" when cooldown expires.
    """

    cooldown_seconds: int
    state: SessionState = SessionState.IDLE
    _session_start: Optional[float] = None
    _session_end: Optional[float] = None
    _cooldown_start: Optional[float] = None
    last_session_duration_seconds: Optional[int] = None

    def tick(self, *, now: float, mic_on: bool) -> Optional[str]:
        if self.state == SessionState.IDLE:
            if mic_on:
                self.state = SessionState.RECORDING
                self._session_start = now
                return "start"
            return None

        if self.state == SessionState.RECORDING:
            if not mic_on:
                self.state = SessionState.COOLDOWN
                self._cooldown_start = now
                self._session_end = now
            return None

        # COOLDOWN
        if mic_on:
            self.state = SessionState.RECORDING
            self._cooldown_start = None
            self._session_end = None
            return None
        if now - (self._cooldown_start or now) >= self.cooldown_seconds:
            self.state = SessionState.IDLE
            duration = (self._session_end or now) - (self._session_start or now)
            self.last_session_duration_seconds = int(duration)
            self._session_start = self._session_end = self._cooldown_start = None
            return "stop"
        return None


def mic_is_active() -> bool:
    """Check whether macOS default input device is currently in use.

    Uses CoreAudio kAudioDevicePropertyDeviceIsRunningSomewhere.

    If the pyobjc-CoreAudio symbol surface differs from what is imported below,
    fall back to a working approach (e.g., shelling out to `lsof`). It is
    acceptable for this function to use a different mechanism as long as it
    correctly reports whether the default input device is currently in use.
    """
    # Try pyobjc CoreAudio first; if that fails, fall back to lsof.
    try:
        import objc
        from CoreAudio import (  # type: ignore
            AudioObjectGetPropertyData,
            AudioObjectPropertyAddress,
            kAudioHardwarePropertyDefaultInputDevice,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMaster,
            kAudioObjectSystemObject,
            kAudioDevicePropertyDeviceIsRunningSomewhere,
        )
        import ctypes

        addr = AudioObjectPropertyAddress(
            kAudioHardwarePropertyDefaultInputDevice,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMaster,
        )
        device_id = ctypes.c_uint32(0)
        size = ctypes.c_uint32(ctypes.sizeof(device_id))
        AudioObjectGetPropertyData(
            kAudioObjectSystemObject, addr, 0, None,
            ctypes.byref(size), ctypes.byref(device_id),
        )

        addr2 = AudioObjectPropertyAddress(
            kAudioDevicePropertyDeviceIsRunningSomewhere,
            kAudioObjectPropertyScopeGlobal,
            kAudioObjectPropertyElementMaster,
        )
        running = ctypes.c_uint32(0)
        size2 = ctypes.c_uint32(ctypes.sizeof(running))
        AudioObjectGetPropertyData(
            device_id.value, addr2, 0, None,
            ctypes.byref(size2), ctypes.byref(running),
        )
        return running.value == 1
    except Exception:
        # Fallback: check for non-coreaudiod processes holding audio devices.
        import subprocess
        try:
            result = subprocess.run(
                ["lsof", "+c", "0"],
                capture_output=True, text=True, timeout=2.0,
            )
            for line in result.stdout.splitlines():
                if "CoreAudio" in line and "coreaudiod" not in line:
                    return True
            return False
        except (subprocess.SubprocessError, FileNotFoundError):
            return False
