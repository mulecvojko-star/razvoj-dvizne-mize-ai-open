"""Trusted synthetic cost catalogue and field-level diagnostics. No price discovery."""

import hashlib
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
from src.models.contracts import obj


FIELDS = ("category", "price_kind", "amount_EUR", "source")


def allowed_cost_items(arm_length_mm):
    arms = (Decimal(4) * Decimal(str(arm_length_mm)) / Decimal(1000) * Decimal(50)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return [
        {"category": "arms", "price_kind": "synthetic", "amount_EUR": float(arms),
         "source": "Sintetično 50 EUR/m za štiri roke; ne določa materiala ali nosilnosti."},
        {"category": "base_and_deck", "price_kind": "synthetic", "amount_EUR": 300.0, "source": "Sintetičen učni pavšal."},
        {"category": "cylinder", "price_kind": "synthetic", "amount_EUR": 350.0, "source": "Sintetičen učni pavšal; potreben hod in sila še ne določata dobavnega artikla."},
        {"category": "hydraulic_unit", "price_kind": "unknown", "amount_EUR": None, "source": "Manjkajo dejanski pretok, pogon in ponudba."},
        {"category": "assembly", "price_kind": "synthetic", "amount_EUR": 250.0, "source": "Sintetičen učni pavšal."},
        {"category": "safety_and_verification", "price_kind": "unknown", "amount_EUR": None, "source": "Manjkajo analiza tveganja, dokumentacija in obseg preverjanj."}]


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def money_matches(value, expected):
    if expected is None:
        return value is None
    if not finite_number(value):
        return False
    actual = Decimal(str(value))
    try:
        cents = actual.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        target = Decimal(str(expected)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return False
    # Only binary float noise is tolerated, never a different cent or a new
    # fractional-cent price. In particular 220.001 and 220.01 both fail.
    return abs(actual - cents) <= Decimal("0.000000001") and cents == target


def cost_issues(actual, expected):
    """Compare by unique category, never by list order; source text remains exact.

    Diagnostics identify known fields/categories but never echo arbitrary model text.
    """
    issues = []
    catalogue = {row["category"]: row for row in expected}
    seen = set()

    def issue(index, category, field, reason, **safe):
        path = "cost_items" if index is None else f"cost_items[{index}]"
        if field != "cost_items":
            path += f".{field}"
        issues.append({"path": path, "index": index, "category": category,
                       "field": field, "reason": reason, **safe})

    if not isinstance(actual, list):
        issue(None, None, "cost_items", "expected_array")
        return issues
    for index, row in enumerate(actual):
        if not isinstance(row, dict):
            issue(index, None, "cost_items", "expected_object")
            continue
        category = row.get("category")
        known = isinstance(category, str) and category in catalogue
        if not known:
            issue(index, None, "category", "missing_field" if "category" not in row else "unknown_category")
            continue
        if category in seen:
            issue(index, category, "category", "duplicate_category")
        seen.add(category)
        target = catalogue[category]
        for field in FIELDS:
            if field not in row:
                issue(index, category, field, "missing_field")
                continue
            value = row[field]
            if field == "amount_EUR":
                valid = money_matches(value, target[field])
            else:
                valid = type(value) is str and value == target[field]
            if not valid:
                reason = {"price_kind": "price_kind_mismatch", "amount_EUR": "amount_mismatch",
                          "source": "source_mismatch", "category": "category_mismatch"}[field]
                safe = {"expected": target[field]}
                if field == "amount_EUR" and (value is None or finite_number(value)):
                    safe["received"] = value
                elif field == "price_kind" and isinstance(value, str) and value in ("verified", "synthetic", "unknown"):
                    safe["received"] = value
                elif field == "source" and isinstance(value, str):
                    safe.update(received_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(), received_length=len(value))
                issue(index, category, field, reason, **safe)
        if set(row) - set(FIELDS):
            issue(index, category, "__extra_fields__", "unexpected_fields", count=len(set(row) - set(FIELDS)))
    for category in catalogue:
        if category not in seen:
            issue(None, category, "category", "missing_category")
    return issues


def exact_cost_schema(items):
    """Structured Outputs can select only the permitted category/kind/value/source tuples."""
    choices = []
    for row in items:
        properties = {}
        for field in FIELDS:
            value = row[field]
            properties[field] = ({"type": "null"} if value is None else
                                 {"type": "number" if field == "amount_EUR" else "string", "enum": [value]})
        choices.append(obj(properties))
    return {"type": "array", "minItems": len(items), "maxItems": len(items), "items": {"anyOf": choices}}
