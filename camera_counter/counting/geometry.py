"""Cruce de un segmento finito, con distancia firmada en píxeles."""

from dataclasses import dataclass
from math import hypot

from camera_counter.types import Point


@dataclass(frozen=True)
class CountingLine:
    a: Point
    b: Point
    margin: float

    def distance(self, point: Point) -> float:
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        return (dx * (point[1] - self.a[1]) - dy * (point[0] - self.a[0])) / hypot(dx, dy)

    def side(self, point: Point) -> int:
        distance = self.distance(point)
        return 1 if distance > self.margin else -1 if distance < -self.margin else 0

    def intersects(self, previous: Point, current: Point) -> bool:
        before, after = self.distance(previous), self.distance(current)
        if before * after > 0 or abs(before - after) < 1e-9:
            return False
        fraction = before / (before - after)
        x = previous[0] + fraction * (current[0] - previous[0])
        y = previous[1] + fraction * (current[1] - previous[1])
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        projection = ((x - self.a[0]) * dx + (y - self.a[1]) * dy) / (dx * dx + dy * dy)
        return 0 <= fraction <= 1 and 0 <= projection <= 1

    @property
    def normal(self) -> Point:
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        length = hypot(dx, dy)
        return -dy / length, dx / length
