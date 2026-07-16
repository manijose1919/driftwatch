"""JSON -> type-shape inference.

A *shape* describes the structure of a JSON document while deliberately
discarding concrete values, so that changing data never registers as drift —
only changing structure does.

Shape node format (plain dicts, JSON-serializable):

    {"type": "null"}
    {"type": "boolean" | "integer" | "number", "nullable": bool?}
    {"type": "string", "nullable": bool?, "values": [..] | None, "observed": int}
    {"type": "mixed", "types": ["integer", "string", ...], "nullable": bool?}
    {"type": "array", "items": <shape> | None, "nullable": bool?}
    {"type": "object", "fields": {name: <shape>}, "nullable": bool?}

Extra keys:
- "nullable": present (True) only when null was observed alongside the type.
- "optional": present (True) on object *fields* seen in only some sibling
  objects when merging array items.
- For strings, "values" holds a sorted sample of observed values (capped at
  ENUM_SAMPLE_CAP; None once the cap is exceeded, meaning "open set") and
  "observed" counts total string observations. The differ uses these to
  detect new values appearing in closed enum-like fields.
"""

ENUM_SAMPLE_CAP = 12

SCALAR_TYPES = {"boolean", "integer", "number", "string"}


def infer_shape(value) -> dict:
    """Infer the shape of a single parsed-JSON value."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):  # must precede int: bool subclasses int
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string", "values": [value], "observed": 1}
    if isinstance(value, list):
        item_shapes = [infer_shape(v) for v in value]
        return {"type": "array", "items": merge_shapes(item_shapes)}
    if isinstance(value, dict):
        return {"type": "object", "fields": {k: infer_shape(v) for k, v in value.items()}}
    # Non-JSON type (shouldn't happen with json.loads output)
    return {"type": "mixed", "types": [type(value).__name__]}


def merge_shapes(shapes: list[dict]) -> dict | None:
    """Merge shapes of sibling values (e.g. items of one array) into one shape.

    Returns None for an empty list (an empty array tells us nothing about
    its item shape).
    """
    shapes = [s for s in shapes if s is not None]
    if not shapes:
        return None

    nullable = any(s["type"] == "null" or s.get("nullable") for s in shapes)
    non_null = [s for s in shapes if s["type"] != "null"]
    if not non_null:
        return {"type": "null"}

    types = sorted({s["type"] for s in non_null})

    if types == ["integer", "number"]:
        # ints and floats in the same position: treat as number
        merged = {"type": "number"}
    elif len(types) > 1 or "mixed" in types:
        all_types: set[str] = set()
        for s in non_null:
            if s["type"] == "mixed":
                all_types.update(s.get("types", []))
            else:
                all_types.add(s["type"])
        merged = {"type": "mixed", "types": sorted(all_types)}
    else:
        t = types[0]
        if t == "object":
            merged = {"type": "object", "fields": _merge_object_fields(non_null)}
        elif t == "array":
            item_shapes = [s["items"] for s in non_null if s.get("items") is not None]
            merged = {"type": "array", "items": merge_shapes(item_shapes)}
        elif t == "string":
            merged = _merge_strings(non_null)
        else:
            merged = {"type": t}

    if nullable:
        merged["nullable"] = True
    return merged


def _merge_object_fields(object_shapes: list[dict]) -> dict:
    total = len(object_shapes)
    field_names: dict[str, None] = {}
    for s in object_shapes:
        for name in s.get("fields", {}):
            field_names.setdefault(name)

    merged_fields: dict[str, dict] = {}
    for name in field_names:
        present = [s["fields"][name] for s in object_shapes if name in s.get("fields", {})]
        merged = merge_shapes(present)
        # a field can carry "optional" from deeper merges; presence here wins
        was_optional = any(p.get("optional") for p in present)
        if len(present) < total or was_optional:
            merged["optional"] = True
        merged_fields[name] = merged
    return merged_fields


def _merge_strings(string_shapes: list[dict]) -> dict:
    observed = sum(s.get("observed", 1) for s in string_shapes)
    values: set[str] | None = set()
    for s in string_shapes:
        sample = s.get("values")
        if sample is None:
            values = None
            break
        values.update(sample)
        if len(values) > ENUM_SAMPLE_CAP:
            values = None
            break
    return {
        "type": "string",
        "values": sorted(values) if values is not None else None,
        "observed": observed,
    }


def is_closed_enum(shape: dict) -> bool:
    """Heuristic: does this string shape look like a closed enum?

    Requires enough observations of few-enough distinct short values that a
    brand-new value is meaningful rather than free-form text (names, ids...).
    """
    if shape.get("type") != "string":
        return False
    values = shape.get("values")
    if values is None or not (2 <= len(values) <= 6):
        return False
    observed = shape.get("observed", 0)
    if observed < 5:
        return False
    # Enums repeat; free-form fields (names, ids) are mostly distinct.
    if len(values) / observed > 0.6:
        return False
    return all(len(v) <= 32 for v in values)
