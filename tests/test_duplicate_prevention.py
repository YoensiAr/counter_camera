from conftest import NOW, feed, person


def test_each_confirmed_physical_trip_is_recorded(counter):
    events = feed(counter, [60] * 5 + [130] * 5 + [60] * 5 + [130] * 5 + [60] * 5)
    assert [e.event_type for e in events] == ["entry", "exit", "entry", "exit"]
    assert [e.crossing_index for e in events] == [1, 2, 3, 4]


def test_brief_occlusion_does_not_duplicate(counter):
    events = feed(counter, [60] * 5 + [130] * 5)
    counter.update([], 1.2, NOW)
    events += feed(counter, [130] * 8, start=1.5)
    assert len(events) == 1


def test_crossing_during_brief_occlusion(counter):
    feed(counter, [60] * 5)
    counter.update([], 0.5, NOW)
    events = feed(counter, [130] * 5, start=0.8)
    assert len(events) == 1


def test_missing_observation_breaks_consecutive_confirmation(counter):
    feed(counter, [60] * 5 + [130, 130])
    counter.update([], 0.7, NOW)
    assert feed(counter, [130, 130], start=0.8) == []
    assert len(feed(counter, [130], start=1.0)) == 1


def test_simultaneous_people(counter):
    events = []
    for i, y in enumerate([60] * 5 + [130] * 5):
        events += counter.update([person(1, 70, y), person(2, 130, y)], i * 0.1, NOW)
    assert {e.track_id for e in events} == {1, 2}


def test_opposite_crossing_is_immediate_and_staying_outside_adds_nothing(counter):
    counter.config.cooldown_seconds = 10
    events = feed(counter, [60] * 5 + [130] * 5 + [60] * 5)
    events += feed(counter, [60] * 10, start=12)
    assert [e.event_type for e in events] == ["entry", "exit"]
