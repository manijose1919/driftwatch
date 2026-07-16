"""Shape differ + breaking-change classifier.

Compares a baseline shape against a freshly inferred one and emits a list of
classified changes:

    {"path": "$.items[].price", "kind": "type_changed",
     "severity": "breaking", "detail": "number -> string"}

Severity semantics (consumer's point of view):
- breaking: existing client code will very likely fail
- risky:    existing client code may fail depending on assumptions
- benign:   purely additive / informational

Core principle: a single observation that is CONSISTENT with the baseline
contract is not drift. An optional field being absent, only one variant of a
union type appearing, an array being empty, or a nullable field holding a
value are all expected outcomes of sampling — reporting them would drown
users in noise (especially with multi-probe learned baselines). Only
violations (removals, type changes) and expansions (new types, new enum
values, new nullability, new fields) are reported.
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
        # Array empty this probe: consistent with the baseline, not drift.
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
        change = _classify_type_change(old_types, new_types, path)
        if change is not None:
            changes.append(change)
        # Either way, stop here: a type change makes deeper structure
        # incomparable, and a silent subset (baseline was a union) means the
        # baseline node carries no structure to recurse into.
        return changes

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
            if old_f.get("optional"):
                continue  # absence of an optional field is within contract
            changes.append(_c(fpath, "field_removed", BREAKING, "field disappeared"))
            continue
        new_f = new_fields[name]
        if not old_f.get("optional") and new_f.get("optional"):
            changes.append(_c(fpath, "became_optional", RISKY,
                              "field no longer present on every item"))
        # optional -> present-everywhere is consistent with contract: silent
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
    # nullable baseline + no null this probe is consistent with contract: silent


def _classify_type_change(old_types: set[str], new_types: set[str], path: str) -> dict | None:
    """Classify a type-set difference; None means consistent (not drift)."""
    detail = f"{_fmt(old_types)} -> {_fmt(new_types)}"
    if old_types == {"integer"} and new_types == {"number"}:
        return _c(path, "type_widened", RISKY, "integer -> number (fractional values appeared)")
    if _is_consistent_subset(new_types, old_types):
        return None  # only saw some of the baseline's variants this probe
    if new_types > old_types:
        return _c(path, "type_variant_added", RISKY, f"gained type variant(s): {detail}")
    return _c(path, "type_changed", BREAKING, detail)


def _is_consistent_subset(new_types: set[str], old_types: set[str]) -> bool:
    """Is every observed type allowed by the baseline union?

    JSON integers are valid numbers, so an observed "integer" is satisfied
    by a baseline "number".
    """
    for t in new_types:
        if t in old_types:
            continue
        if t == "integer" and "number" in old_types:
            continue
        return False
    return True


def _type_set(shape: dict) -> set[str]:
    if shape["type"] == "mixed":
        return set(shape.get("types", []))
    return {shape["type"]}


def _fmt(types: set[str]) -> str:
    return "|".join(sorted(types))


def _c(path: str, kind: str, severity: str, detail: str) -> dict:
    return {"path": path, "kind": kind, "severity": severity, "detail": detail}
