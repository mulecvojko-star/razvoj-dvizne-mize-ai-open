"""Build local stage data and validate numerical claims separately from model prose."""

import math
from src.models.contracts import digest
from .calculations import EngineeringError, construction, economics, enabled, hydraulics
from .review import review

UNITS = {"length": "mm", "force": "N", "pressure": "bar", "flow": "L/min", "power": "kW", "currency": "EUR"}


def reference(handoff, name):
    if not enabled(handoff):
        return None
    try:
        if name == "konstruktor":
            data = construction(handoff.inputs)
        elif name == "hidravlik":
            data = hydraulics(handoff.inputs, handoff.results["konstruktor"]["engineering"])
        elif name == "ekonomist":
            data = economics(handoff.results["konstruktor"]["engineering"], handoff.results["hidravlik"]["engineering"])
        else:
            data = review(handoff.inputs, *(handoff.results[n]["engineering"] for n in ("konstruktor", "hidravlik", "ekonomist")))
    except (KeyError, TypeError, IndexError):
        raise EngineeringError("Manjka ali ni veljavna inženirska predaja predhodnega agenta.") from None
    return {**data, "units": UNITS.copy(), "input_sha256": digest(handoff.inputs)}


def claims(name, data):
    if data is None:
        return []
    if name == "konstruktor":
        numbers = {key: (data[key], "N" if key == "peak_cylinder_force_N" else "mm")
                   for key in ("lift_mm", "cylinder_closed_pin_mm", "cylinder_open_pin_mm", "stroke_mm", "peak_cylinder_force_N")}
        numbers.update(span_low_mm=(data["positions"][0]["span_mm"], "mm"),
                       span_high_mm=(data["positions"][-1]["span_mm"], "mm"))
    elif name == "hidravlik":
        numbers = {"max_force_N": (data["max_force_N"], "N")}
        numbers.update({f"bore_{option['pressure_bar']}_bar_mm": (option["theoretical_bore_mm"], "mm")
                        for option in data["pressure_options"]})
        if data["flow_L_min"] is not None:
            numbers["max_flow_L_min"] = (max(data["flow_L_min"]), "L/min")
            numbers["max_hydraulic_power_kW"] = (max(data["hydraulic_power_kW"]), "kW")
    elif name == "ekonomist":
        numbers = {"synthetic_subtotal_EUR": (data["synthetic_subtotal_EUR"], "EUR")}
    else:
        numbers = {}
    return [{"quantity": key, "value": value, "unit": unit} for key, (value, unit) in numbers.items()]


def validate_claims(name, model, expected):
    wanted = {r["quantity"]: r for r in claims(name, expected)}
    actual = model["calculations"]
    if len(actual) != len(wanted) or {r["quantity"] for r in actual} != set(wanted):
        raise EngineeringError("AI ni vrnil vseh zahtevanih numeričnih izračunov.")
    for row in actual:
        target = wanted[row["quantity"]]
        if (row["unit"] != target["unit"] or isinstance(row["value"], bool)
                or not math.isfinite(row["value"])
                or not math.isclose(row["value"], target["value"], rel_tol=1e-4, abs_tol=0.01)):
            raise EngineeringError(f"Napačen AI-izračun ali enota: {target['quantity']}.")
    cost_items = expected["cost_items"] if expected is not None and name == "ekonomist" else []
    if model["cost_items"] != cost_items:
        raise EngineeringError("Stroški nimajo preverljivega izvora ali ne ustrezajo sintetični oceni.")
    if name == "recenzent" and expected is not None:
        if model["decision"] != expected["status"]:
            raise EngineeringError("Recenzent ne sme odobriti nepreverjene konstrukcije.")
        for finding in expected["findings"]:
            if not any(f["target_agent"] == finding["target_agent"] and f["status"] == "open"
                       and f["severity"] in ("major", "critical") for f in model["findings"]):
                raise EngineeringError("Recenzent mora vrniti nerešena tveganja odgovornemu agentu.")


def compare(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(compare(actual[k], v) for k, v in expected.items()))
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(compare(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return (isinstance(actual, (int, float)) and not isinstance(actual, bool)
                and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-7))
    return type(actual) is type(expected) and actual == expected


def validate_stage(handoff, name, result):
    expected = reference(handoff, name)
    if expected is None:
        return
    if not compare(result.get("engineering"), expected) or result.get("engineering_verified") is not False:
        raise EngineeringError("Nepopolna ali spremenjena deterministična inženirska predaja.")
    validate_claims(name, result, expected)
    if result.get("technical_status") != expected["status"]:
        raise EngineeringError("Napačno tehnično stanje predaje.")
    if name == "recenzent" and result["decision"] != expected["status"]:
        raise EngineeringError("Tehnično nepreverjene variante ni dovoljeno odobriti.")
