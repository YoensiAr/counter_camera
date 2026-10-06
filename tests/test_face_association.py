import numpy as np

from camera_counter.types import TrackedPerson
from camera_counter.visitors.recognizer import assign_faces


def face(x=60, y=20, width=60, height=60):
    return np.array([x, y, width, height, 75, 40, 105, 40, 90, 55, 78, 68, 102, 68, 0.99], np.float32)


def person(track=1, box=(20, 10, 180, 280), observed=True):
    return TrackedPerson(track, box, 0.9, observed)


def test_face_inside_one_head_region_is_assigned():
    assert set(assign_faces([face()], [person()], 48)) == {1}


def test_overlapping_people_do_not_share_face():
    assert assign_faces([face()], [person(1), person(2)], 48) == {}


def test_two_faces_in_one_body_box_are_ambiguous():
    assert assign_faces([face(), face(x=115)], [person()], 48) == {}


def test_small_or_lower_body_face_is_rejected():
    assert assign_faces([face(width=20)], [person()], 48) == {}
    assert assign_faces([face(y=180)], [person()], 48) == {}


def test_predicted_person_cannot_own_face():
    assert assign_faces([face()], [person(observed=False)], 48) == {}


def test_face_cannot_be_assigned_to_only_one_of_two_overlapping_visible_bodies():
    # La elegibilidad para extraer una muestra no debe quitar al otro cuerpo de la asociación.
    assert assign_faces([face()], [person(), person(2, (30, 0, 190, 290))], 48) == {}
