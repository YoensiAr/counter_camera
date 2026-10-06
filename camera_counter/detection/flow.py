"""Flujo óptico para la vista intermedia; sus estimaciones nunca generan conteos."""

import cv2
import numpy as np

from camera_counter.types import TrackedPerson


class FlowPreview:
    def __init__(self):
        self.gray = None
        self.people: list[TrackedPerson] = []
        self.last_observed = 0.0

    def seed(self, image, people, now):
        self.gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        self.people = people
        self.last_observed = now

    def advance(self, image, now, max_age):
        current = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        if self.gray is None or self.gray.shape != current.shape or now - self.last_observed > max_age:
            self.gray, self.people = current, []
            return []
        result = []
        height, width = current.shape
        for person in self.people:
            x1, y1, x2, y2 = person.box
            mask = np.zeros_like(current)
            mask[max(0, int(y1)) : min(height, int(y2)), max(0, int(x1)) : min(width, int(x2))] = 255
            points = cv2.goodFeaturesToTrack(self.gray, 16, 0.02, 5, mask=mask)
            if points is None or len(points) < 3:
                continue
            moved, status, _ = cv2.calcOpticalFlowPyrLK(self.gray, current, points, None)
            if moved is None or status is None:
                continue
            valid = status.reshape(-1) == 1
            if valid.sum() < 3:
                continue
            dx, dy = np.median((moved - points).reshape(-1, 2)[valid], axis=0)
            if not np.isfinite([dx, dy]).all() or abs(dx) > width / 4 or abs(dy) > height / 4:
                continue
            result.append(
                TrackedPerson(
                    person.track_id,
                    (max(0, x1 + dx), max(0, y1 + dy), min(width, x2 + dx), min(height, y2 + dy)),
                    person.confidence,
                    observed=False,
                )
            )
        self.gray, self.people = current, result
        return result
