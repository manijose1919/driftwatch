"""Unit tests for the shape differ / breaking-change classifier."""
from app.engine.differ import diff_shapes, overall_severity
from app.engine.shape import infer_shape


def diff_payloads(old_payload, new_payload):
    return diff_shapes(infer_shape(old_payload), infer_shape(new_payload))


def kinds(changes):
    return {c["kind"] for c in changes}


def test_identical_payload_shapes_no_drift():
    payload = {"id": 1, "items": [{"sku": "a", "qty": 2}]}
    assert diff_payloads(payload, {"id": 9, "items": [{"sku": "zz", "qty": 7}]}) == []


def test_field_removed_is_breaking():
    changes = diff_payloads({"id": 1, "name": "x"}, {"id": 1})
    assert len(changes) == 1
    assert changes[0]["kind"] == "field_removed"
    assert changes[0]["path"] == "$.name"
    assert overall_severity(changes) == "breaking"


def test_field_added_is_benign():
    changes = diff_payloads({"id": 1}, {"id": 1, "extra": "x"})
    assert changes == [
        {"path": "$.extra", "kind": "field_added", "severity": "benign", "detail": "new field"}
    ]


def test_type_change_is_breaking():
    changes = diff_payloads({"price": 12.5}, {"price": "12.50"})
    assert changes[0]["kind"] == "type_changed"
    assert changes[0]["severity"] == "breaking"
    assert "number -> string" in changes[0]["detail"]


def test_int_to_float_is_risky_widening():
    changes = diff_payloads({"qty": 2}, {"qty": 2.5})
    assert changes[0]["kind"] == "type_widened"
    assert changes[0]["severity"] == "risky"


def test_float_to_int_is_benign():
    changes = diff_payloads({"qty": 2.5}, {"qty": 2})
    assert changes[0]["kind"] == "type_narrowed"
    assert changes[0]["severity"] == "benign"


def test_became_nullable_is_risky():
    changes = diff_payloads({"tags": ["a", "b"]}, {"tags": ["a", None]})
    assert any(c["kind"] == "became_nullable" and c["severity"] == "risky" for c in changes)


def test_field_became_optional_in_array_items_is_risky():
    old = {"rows": [{"a": 1, "b": 2}, {"a": 1, "b": 2}]}
    new = {"rows": [{"a": 1, "b": 2}, {"a": 1}]}
    changes = diff_payloads(old, new)
    assert any(
        c["kind"] == "became_optional" and c["path"] == "$.rows[].b" for c in changes
    )


def test_removed_field_inside_array_items_is_breaking():
    old = {"rows": [{"a": 1, "b": 2}]}
    new = {"rows": [{"a": 1}]}
    changes = diff_payloads(old, new)
    assert changes[0]["path"] == "$.rows[].b"
    assert changes[0]["severity"] == "breaking"


def test_new_enum_value_is_risky():
    old = {"orders": [{"status": s} for s in ["open", "closed", "open", "closed", "open"]]}
    new = {"orders": [{"status": s} for s in ["open", "closed", "refunded", "open", "open"]]}
    changes = diff_payloads(old, new)
    assert len(changes) == 1
    assert changes[0]["kind"] == "enum_value_added"
    assert "refunded" in changes[0]["detail"]
    assert changes[0]["severity"] == "risky"


def test_freeform_string_change_is_not_drift():
    old = {"users": [{"name": n} for n in ["ada", "bob", "cy", "dee", "eli"]]}
    new = {"users": [{"name": n} for n in ["xerxes", "yara", "zoe", "quinn", "rex"]]}
    assert diff_payloads(old, new) == []


def test_always_null_gaining_type_is_risky():
    changes = diff_payloads({"meta": None}, {"meta": {"v": 1}})
    assert changes[0]["kind"] == "null_gained_type"
    assert changes[0]["severity"] == "risky"


def test_becoming_always_null_is_breaking():
    changes = diff_payloads({"meta": {"v": 1}}, {"meta": None})
    assert changes[0]["kind"] == "now_always_null"
    assert changes[0]["severity"] == "breaking"


def test_empty_array_learning_items_is_benign():
    changes = diff_payloads({"rows": []}, {"rows": [{"a": 1}]})
    assert changes[0]["kind"] == "array_items_learned"
    assert changes[0]["severity"] == "benign"


def test_no_recursion_below_type_change():
    old = {"data": {"deep": {"x": 1}}}
    new = {"data": [1, 2, 3]}
    changes = diff_payloads(old, new)
    assert len(changes) == 1  # one root-cause change, no noise about $.data.deep


def test_overall_severity_picks_strongest():
    changes = diff_payloads(
        {"a": 1, "b": "x"},
        {"b": "x", "c": 2},  # a removed (breaking), c added (benign)
    )
    assert overall_severity(changes) == "breaking"
    assert overall_severity([]) is None


def test_root_type_change():
    changes = diff_payloads({"a": 1}, [1, 2])
    assert changes[0]["path"] == "$"
    assert changes[0]["severity"] == "breaking"
