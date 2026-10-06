from conftest import NOW, feed, person


def test_visible_one_hundred_frames_counts_once(counter):
    events = feed(counter, [60] * 10 + list(range(60, 141, 4)) + [140] * 69)
    assert len(events) == 1
    assert events[0].event_type == "entry"


def test_without_crossing(counter):
    assert feed(counter, [60] * 100) == []


def test_person_staying_on_line(counter):
    assert feed(counter, [60] * 5 + [98, 100, 102, 101, 99] * 20) == []


def test_jitter_after_entry(counter):
    events = feed(counter, [60] * 5 + [110] * 5 + [99, 101, 97, 103] * 20 + [130] * 10)
    assert [e.event_type for e in events] == ["entry"]


def test_parallel_motion(counter):
    events = []
    for i in range(100):
        events.extend(counter.update([person(x=i * 2, y=60)], i * 0.1, NOW))
    assert events == []


def test_outside_segment_does_not_count(counter):
    assert feed(counter, [60] * 5 + [100] * 2 + [140] * 5, x=199) == []


def test_going_around_endpoint_does_not_count(counter):
    positions = [(100, 60)] * 4 + [(199, 60), (199, 100), (199, 140)] + [(100, 140)] * 4
    events = []
    for i, (x, y) in enumerate(positions):
        events += counter.update([person(x=x, y=y)], i * 0.1, NOW)
    assert events == []


def test_requires_confirmation_on_both_sides(counter):
    assert feed(counter, [60, 60, 130, 130, 130, 130]) == []


def test_single_opposite_frame_is_not_counted(counter):
    assert feed(counter, [60] * 5 + [130] + [60] * 5) == []


def test_spawn_on_line_does_not_count(counter):
    assert feed(counter, [100] * 5 + [130] * 5) == []


def test_predictions_do_not_generate_events(counter):
    feed(counter, [60] * 5)
    events = []
    for i in range(10):
        events += counter.update([person(y=140, observed=False)], 0.5 + i * 0.1, NOW)
    assert events == []
