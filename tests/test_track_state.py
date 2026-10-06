from dataclasses import replace

from camera_counter.counting.track_state import PersonState
from conftest import NOW, feed, person


def test_state_progression(counter):
    feed(counter, [60] * 3)
    assert counter.tracks[1].state == PersonState.OUTSIDE
    feed(counter, [100], start=0.3)
    assert counter.tracks[1].state == PersonState.CROSSING
    feed(counter, [130] * 3, start=0.4)
    assert counter.tracks[1].state == PersonState.COUNTED_ENTRY
    assert counter.tracks[1].already_counted
    assert counter.tracks[1].previous_position == (100, 130)


def test_history_is_bounded(counter):
    feed(counter, [60] * 200)
    assert len(counter.tracks[1].history) == counter.config.history_size


def test_tracks_expire(counter):
    feed(counter, [60] * 3)
    counter.update([], 5, NOW)
    assert counter.tracks == {}


def test_return_after_expiration_is_new_visit(counter):
    assert len(feed(counter, [60] * 5 + [130] * 5, track_id=1)) == 1
    counter.update([], 4, NOW)
    assert len(feed(counter, [60] * 5 + [130] * 5, track_id=2, start=4.1)) == 1


def test_moving_line_does_not_create_crossing(counter):
    feed(counter, [60] * 4)
    counter.reconfigure(replace(counter.config, p1=[0.1, 0.2], p2=[0.9, 0.2]), 200, 200)
    assert feed(counter, [60] * 4, start=0.5) == []


def test_reconfigure_preserves_sequence_and_requires_a_new_physical_crossing(counter):
    feed(counter, [60] * 4 + [130] * 4)
    counter.reconfigure(counter.config, 200, 200)
    assert feed(counter, [60] * 4, start=1) == []
    events = feed(counter, [130] * 4, start=1.4)
    assert len(events) == 1
    assert events[0].crossing_index == 2


def test_active_track_cap(counter):
    counter.max_tracks = 2
    counter.update([person(1), person(2), person(3)], 0, NOW)
    assert len(counter.tracks) == 2
