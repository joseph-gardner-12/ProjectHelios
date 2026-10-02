import math

from .protocol import target
from .simulation import DummyPositionProvider


class CommandCoordinator:
    def __init__(self, provider=None):
        self.provider = provider or DummyPositionProvider()
        self.reset()

    def reset(self):
        self.active = None
        self.started = None
        self.last_tick = None
        self.within_since = None
        self.completed_id = None
        self.acknowledgments = {}

    def prepare(self, data, now):
        command_id = data["command_id"]
        if command_id in self.acknowledgments:
            return self.acknowledgments[command_id], None
        try:
            candidate = target(data)
            if candidate.expires_at <= now:
                raise ValueError("Target expired")
            if self.active:
                raise ValueError("Device busy")
            acknowledgment = {"type": "ack", "command_id": command_id, "accepted": True}
        except (ValueError, KeyError, TypeError) as exc:
            candidate = None
            acknowledgment = {
                "type": "ack",
                "command_id": command_id,
                "accepted": False,
                "reason": str(exc),
            }
        self.acknowledgments[command_id] = acknowledgment
        return acknowledgment, candidate

    def start(self, candidate, monotonic_now):
        # Transport calls this only after acknowledgment has been sent successfully.
        if candidate:
            self.active = candidate
            self.started = self.last_tick = monotonic_now
            self.within_since = None
            self.completed_id = None

    def tick(self, monotonic_now):
        if not self.active:
            return
        if monotonic_now - self.started >= 30:
            raise TimeoutError("Dummy execution timed out")
        self.provider.advance(self.active.position, monotonic_now - self.last_tick)
        self.last_tick = monotonic_now
        distance = math.dist(
            tuple(self.provider.position.as_dict().values()),
            tuple(self.active.position.as_dict().values()),
        )
        if distance <= 0.01:
            if self.within_since is None:
                self.within_since = monotonic_now
            if monotonic_now - self.within_since >= 0.5:
                self.completed_id = self.active.command_id
                self.active = None
        else:
            self.within_since = None

    def telemetry(self):
        return {
            "type": "position",
            "position": self.provider.position.as_dict(),
            "source": "dummy",
            "state": "moving" if self.active else "idle",
            "command_id": self.active.command_id if self.active else None,
            "completed_command_id": self.completed_id,
        }
