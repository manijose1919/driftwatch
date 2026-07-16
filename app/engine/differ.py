"""Shape differ + breaking-change classifier.

Compares a baseline shape against a freshly inferred one and emits a list of
classified changes:

    {"path": "$.items[].price", "kind": "type_changed",
     "severity": "breaking", "detail": "number -> string"}

Severity semantics (consumer's point of view):
- breaking: existing client code will very likely fail
- risky:    existing client code may fail depending on assumptions
- benign:   purely additive / informational
"""
from .shape import is_closed_enum

BENIGN = "benign"
RISKY = "risky"
BREAKING = "breaking"

_RANK = {BENIGN: 0, RISKY: 1, BREAKING: 2}


def overall_severity(changes: list[dict]) -> str | None:
    if not changes:
        return None
    return max(changes, key=lambda c: _RANK[c["severity"]])["severity"]


def diff_shapes(old: dict | None, new: dict | None, path: str = "$") -> list[dict]:
    """Diff two shape nodes, returning classified changes."""
    changes: list[dict] = []
    if old is None and new is None:
        return changes
    if old is None:
        # e.g. an array that was empty at baseline now has items
        changes.append(_c(path, "array_items_learned", BENIGN,
                          "item shape observed for the first time (was empty)"))
        return changes
    if new is None:
        changes.append(_c(path, "array_items_unknown", BENIGN,
                          "array observed empty this probe; item shape not comparable"))
        return changes

    _diff_nullability(old, new, path, changes)

    old_types = _type_set(old)
    new_types = _type_set(new)

    if old_types == {"null"} and new_types != {"null"}:
        changes.append(_c(path, "null_gained_type", RISKY,
                          f"was always null, now {_fmt(new_types)}"))
        return changes
    if new_types == {"null"} and old_types != {"null"}:
        changes.append(_c(path, "now_always_null", BREAKING,
                          f"was {_fmt(old_types)}, now always null"))
        return changes

    if old_types != new_types:
        changes.append(_classify_type_change(old_types, new_types, path))
        return changes  # structures no longer comparable below this node

    # Same type(s) from here on.
    t = old["type"]
    if t == "object":
        _diff_objects(old, new, path, changes)
    elif t == "array":
        changes.extend(diff_shapes(old.get("items"), new.get("items"), path + "[]"))
    elif t == "string":
        _diff_string_enum(old, new, path, changes)
    return changes


def _diff_objects(old: dict, new: dict, path: str, changes: list[dict]) -> None:
    old_fields = old.get("fields", {})
    new_fields = new.get("fields", {})

    for name, old_f in old_fields.items():
        fpath = f"{path}.{name}"
        if name not in new_fields:
            changes.append(_c(fpath, "field_removed", BREAKING, "field disappeared"))
            continue
        new_f = new_fields[name]
        if not old_f.get("optional") and new_f.get("optional"):
            changes.append(_c(fpath, "became_optional", RISKY,
                              "field no longer present on every item"))
        elif old_f.get("optional") and not new_f.get("optional"):
            changes.append(_c(fpath, "became_required", BENIGN,
                              "field now present on every item"))
        changes.extend(diff_shapes(old_f, new_f, fpath))

    for name in new_fields:
        if name not in old_fields:
            changes.append(_c(f"{path}.{name}", "field_added", BENIGN, "new field"))


def _diff_string_enum(old: dict, new: dict, path: str, changes: list[dict]) -> None:
    if not is_closed_enum(old):
        return
    old_values = set(old.get("values") or [])
    new_values = new.get("values")
    if new_values is None:
        changes.append(_c(path, "enum_opened", RISKY,
                          f"looked like a closed enum {sorted(old_values)}, "
                          "now shows many distinct values"))
        return
    added = sorted(set(new_values) - old_values)
    if added:
        changes.append(_c(path, "enum_value_added", RISKY,
                          f"new value(s) {added} in enum-like field "
                          f"(known: {sorted(old_values)})"))


def _diff_nullability(old: dict, new: dict, path: str, changes: list[dict]) -> None:
    old_nullable = bool(old.get("nullable")) or old["type"] == "null"
    new_nullable = bool(new.get("nullable")) or new["type"] == "null"
    if old["type"] == "null" or new["type"] == "null":
        return  # handled by the always-null cases in diff_shapes
    if not old_nullable and new_nullable:
        changes.append(_c(path, "became_nullable", RISKY, "null observed where never seen before"))
    elif old_nullable and not new_nullable:
        changes.append(_c(path, "non_nullable", BENIGN, "no null observed this probe"))


def _classify_type_change(old_types: set[str], new_types: set[str], path: str) -> dict:
    detail = f"{_fmt(old_types)} -> {_fmt(new_types)}"
    if old_types == {"integer"} and new_types == {"number"}:
        return _c(path, "type_widened", RISKY, "integer -> number (fractional values appeared)")
    if old_types == {"number"} and new_types == {"integer"}:
        return _c(path, "type_narrowed", BENIGN, "number -> integer (still numeric)")
    if new_types > old_types:
        return _c(path, "type_variant_added", RISKY, f"gained type variant(s): {detail}")
    if new_types < old_types:
        return _c(path, "type_narrowed", BENIGN, f"type set narrowed: {detail}")
    return _c(path, "type_changed", BREAKING, detail)


def _type_set(shape: dict) -> set[str]:
    if shape["type"] == "mixed":
        return set(shape.get("types", []))
    return {shape["type"]}


def _fmt(types: set[str]) -> str:
    return "|".join(sorted(types))


def _c(path: str, kind: str, severity: str, detail: str) -> dict:
    return {"path": path, "kind": kind, "severity": severity, "detail": detail}
