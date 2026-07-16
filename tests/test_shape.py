"""Unit tests for JSON type-shape inference."""
from app.engine.shape import ENUM_SAMPLE_CAP, infer_shape, is_closed_enum, merge_shapes


def test_scalars():
    assert infer_shape(None) == {"type": "null"}
    assert infer_shape(True) == {"type": "boolean"}
    assert infer_shape(3) == {"type": "integer"}
    assert infer_shape(3.5) == {"type": "number"}
    s = infer_shape("hi")
    assert s["type"] == "string" and s["values"] == ["hi"] and s["observed"] == 1


def test_bool_is_not_integer():
    assert infer_shape(True)["type"] == "boolean"
    assert infer_shape(1)["type"] == "integer"


def test_nested_object():
    shape = infer_shape({"user": {"id": 1, "name": "ada"}})
    assert shape["type"] == "object"
    user = shape["fields"]["user"]
    assert user["fields"]["id"]["type"] == "integer"
    assert user["fields"]["name"]["type"] == "string"


def test_empty_array_has_unknown_items():
    assert infer_shape([])["items"] is None


def test_array_merges_item_objects_with_optionality():
    shape = infer_shape([{"a": 1, "b": "x"}, {"a": 2}])
    fields = shape["items"]["fields"]
    assert "optional" not in fields["a"]
    assert fields["b"]["optional"] is True


def test_array_int_float_promotes_to_number():
    shape = infer_shape([1, 2.5])
    assert shape["items"]["type"] == "number"


def test_array_mixed_types():
    shape = infer_shape([1, "x"])
    assert shape["items"]["type"] == "mixed"
    assert shape["items"]["types"] == ["integer", "string"]


def test_nullable_marking():
    shape = infer_shape([1, None])
    assert shape["items"]["type"] == "integer"
    assert shape["items"]["nullable"] is True


def test_all_null_array():
    assert infer_shape([None, None])["items"] == {"type": "null"}


def test_string_values_cap_becomes_open_set():
    shape = infer_shape([f"v{i}" for i in range(ENUM_SAMPLE_CAP + 5)])
    assert shape["items"]["values"] is None
    assert shape["items"]["observed"] == ENUM_SAMPLE_CAP + 5


def test_closed_enum_heuristic():
    closed = infer_shape(["a", "b", "a", "b", "a", "c"])["items"]
    assert is_closed_enum(closed)
    too_few_observations = infer_shape(["a", "b"])["items"]
    assert not is_closed_enum(too_few_observations)
    single_value = infer_shape(["a"] * 10)["items"]
    assert not is_closed_enum(single_value)  # 1 distinct value: can't call it an enum
    open_set = infer_shape([f"v{i}" for i in range(20)])["items"]
    assert not is_closed_enum(open_set)
    all_distinct = infer_shape(["ada", "bob", "cy", "dee", "eli"])["items"]
    assert not is_closed_enum(all_distinct)  # no repetition => free-form, not enum


def test_merge_none_shapes():
    assert merge_shapes([]) is None
    assert merge_shapes([None, None]) is None


def test_shapes_ignore_values():
    """Same structure, different data => identical shapes (except string samples)."""
    a = infer_shape({"id": 1, "price": 9.99, "ok": True})
    b = infer_shape({"id": 42, "price": 0.5, "ok": False})
    assert a == b
