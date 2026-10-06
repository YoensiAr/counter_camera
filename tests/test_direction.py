from camera_counter.config import LineConfig
from camera_counter.counting.line_counter import LineCounter
from conftest import NOW, feed, person


def test_entry(counter):
    assert [e.event_type for e in feed(counter, [60] * 5 + [140] * 5)] == ["entry"]


def test_exit(counter):
    assert [e.event_type for e in feed(counter, [140] * 5 + [60] * 5)] == ["exit"]


def test_inverted_direction(counter):
    counter.config.entry_to = "negative"
    assert [e.event_type for e in feed(counter, [60] * 5 + [140] * 5)] == ["exit"]


def test_vertical_line_positive_is_left():
    c = LineCounter(LineConfig(p1=[0.5, 0.1], p2=[0.5, 0.9], margin_px=5), 200, 200)
    events = []
    for i, x in enumerate([140] * 5 + [60] * 5):
        events += c.update([person(x=x, y=100)], i * 0.1, NOW)
    assert [e.event_type for e in events] == ["entry"]
