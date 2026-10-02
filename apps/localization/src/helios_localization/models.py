"""Typed boundaries between transport, command coordination, and position generation."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Position:
    x: float = 0
    y: float = 0
    z: float = 0

    def as_dict(self):
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(frozen=True)
class Target:
    command_id: str
    position: Position
    expires_at: datetime
