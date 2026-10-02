"""Hardware-free position provider. Never imported by a real ranging provider."""

import math

from .models import Position


class DummyPositionProvider:
    def __init__(self):
        self.position = Position()

    def advance(self, target: Position, elapsed: float):
        distance = math.dist(
            tuple(self.position.as_dict().values()), tuple(target.as_dict().values())
        )
        fraction = min(1, max(0, elapsed) * 0.5 / distance) if distance else 1
        self.position = Position(
            **{
                axis: getattr(self.position, axis)
                + (getattr(target, axis) - getattr(self.position, axis)) * fraction
                for axis in "xyz"
            }
        )
        return distance <= 0.01
