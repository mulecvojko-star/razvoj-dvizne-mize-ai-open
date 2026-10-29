"""Shared response contract and deterministic validation; no SDK dependency."""

import hashlib
import json
import math


ORDER = ("konstruktor", "hidravlik", "ekonomist", "recenzent")
REQUIRED_INPUTS = ("payload_kg", "platform_length_mm", "platform_width_mm",
                   "min_height_mm", "max_height_mm")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def validate_inputs(handoff):
    """Requirements for managed cycles and real models; legacy primitive stays usable."""
    if handoff.inputs.get("data_origin") not in ("synthetic", "public"):
        raise ValueError("data_origin mora biti synthetic ali public.")
    for key in REQUIRED_INPUTS:
        value = handoff.inputs.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError(f"Manjkajoč ali neveljaven pozitiven vhod: {key}.")
    if handoff.inputs["min_height_mm"] >= handoff.inputs["max_height_mm"]:
        raise ValueError("max_height_mm mora presegati min_height_mm.")
    if set(handoff.input_sources) != set(handoff.inputs):
        raise ValueError("Vsak vhod potrebuje vir v input_sources.")


def obj(properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


STRING = {"type": "string"}
STRINGS = {"type": "array", "items": STRING}
FINDING = obj({
    "id": STRING, "target_agent": {"type": "string", "enum": list(ORDER)},
    "severity": {"type": "string", "enum": ["info", "minor", "major", "critical"]},
    "status": {"type": "string", "enum": ["open", "resolved"]},
    "description": STRING,
    "required_correction": STRING,
})
CALCULATION = obj({"quantity": STRING, "value": {"type": "number"}, "unit": STRING})
COST_ITEM = obj({"category": STRING,
                 "price_kind": {"type": "string", "enum": ["verified", "synthetic", "unknown"]},
                 "amount_EUR": {"anyOf": [{"type": "number"}, {"type": "null"}]}, "source": STRING})
RESPONSE_SCHEMA = obj({
    "variant": STRING, "revision": STRING, "agent": {"type": "string", "enum": list(ORDER)},
    "summary": STRING, "assumptions": STRINGS, "open_questions": STRINGS,
    "calculations": {"type": "array", "items": CALCULATION},
    "cost_items": {"type": "array", "items": COST_ITEM},
    "outputs": {"type": "array", "items": obj({
        "name": STRING, "value": STRING, "unit": STRING, "basis": STRING})},
    "decision": {"type": "string", "enum": ["not_applicable", "accepted", "changes_required", "blocked"]},
    "findings": {"type": "array", "items": FINDING},
})


def validate_schema(value, schema):
    """Validate the small JSON Schema subset used by this application locally too."""
    if "anyOf" in schema:
        for option in schema["anyOf"]:
            try:
                validate_schema(value, option)
                return
            except ValueError:
                pass
        raise ValueError("Vrednost ne ustreza nobeni dovoljeni vrsti.")
    kind = schema["type"]
    if kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)):
        raise ValueError("Pričakovano je končno število z enoto.")
    if kind == "null" and value is not None:
        raise ValueError("Pričakovana je nedoločena vrednost null.")
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["properties"]):
            raise ValueError("Odgovor nima zahtevanih polj ali vsebuje dodatna polja.")
        for key, subschema in schema["properties"].items():
            validate_schema(value[key], subschema)
    elif kind == "array":
        if not isinstance(value, list):
            raise ValueError("Pričakovan je seznam.")
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", math.inf):
            raise ValueError("Seznam nima zahtevanega števila postavk.")
        for item in value:
            validate_schema(item, schema["items"])
    elif kind == "string":
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Pričakovan je neprazen niz.")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError("Neveljavna vrednost v strukturiranem odgovoru.")


def validate_review(result):
    decision = result.get("decision")
    findings = result.get("findings")
    if decision not in ("accepted", "changes_required", "blocked") or not isinstance(findings, list):
        raise ValueError("Recenzent mora vrniti strukturirano odločitev in ugotovitve.")
    ids = set()
    for finding in findings:
        validate_schema(finding, FINDING)
        if finding["id"] in ids:
            raise ValueError("Oznake ugotovitev morajo biti enolične.")
        ids.add(finding["id"])
    unresolved = any(f["status"] == "open" for f in findings)
    if decision == "accepted" and unresolved:
        raise ValueError("Odprtih ugotovitev ni mogoče označiti kot sprejete.")
    if decision in ("changes_required", "blocked") and not unresolved:
        raise ValueError("Zahteva za popravke potrebuje odprto ugotovitev.")
