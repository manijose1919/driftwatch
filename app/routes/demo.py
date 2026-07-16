"""Built-in demo API for trying DriftWatch without any external dependency.

Point a monitored endpoint at http://127.0.0.1:8000/demo/products, then flip
scenarios with POST /demo/scenario/{n} and probe again to watch drift appear:

  0 — baseline: stable shape (default)
  1 — breaking: price becomes a string, `total` field removed
  2 — risky:    new enum value, discount becomes nullable
  3 — benign:   purely additive new field
"""
import random

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/demo", tags=["demo"])

_scenario = 0
_STATUSES = ["in_stock", "sold_out"]


@router.get("/products")
def products():
    rng = random.Random()  # values vary every call; shape must not alarm
    items = []
    for i in range(8):
        status = _STATUSES[i % 2] if _scenario != 2 else (
            "backordered" if i == 0 else _STATUSES[i % 2]
        )
        item = {
            "id": rng.randint(1, 10_000),
            "name": f"widget-{rng.randint(1, 99)}",
            "price": round(rng.uniform(1, 500), 2),
            "status": status,
            "discount": rng.uniform(0, 0.4),
        }
        if _scenario == 1:
            item["price"] = f"{item['price']:.2f}"  # number -> string: breaking
        if _scenario == 2 and i % 3 == 0:
            item["discount"] = None  # became nullable: risky
        if _scenario == 3:
            item["rating"] = round(rng.uniform(1, 5), 1)  # new field: benign
        items.append(item)

    payload = {"products": items, "currency": "USD"}
    if _scenario != 1:
        payload["total"] = len(items)  # removed in scenario 1: breaking
    return payload


@router.post("/scenario/{n}")
def set_scenario(n: int):
    global _scenario
    if n not in (0, 1, 2, 3):
        raise HTTPException(400, "scenario must be 0, 1, 2 or 3")
    _scenario = n
    return {"scenario": _scenario}


@router.get("/scenario")
def get_scenario():
    return {"scenario": _scenario}
