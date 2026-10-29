"""Explicit SI/mm calculations for a single-stage, two-plane scissor concept."""

import math
from .costs import allowed_cost_items
from src.models.contracts import REQUIRED_INPUTS, digest


class EngineeringError(ValueError):
    code = "engineering_validation_failed"

    def __init__(self, message, *, details=None):
        super().__init__(message)
        self.details = details or []


def enabled(handoff):
    # The low-level legacy simulation accepts minimal educational handoffs.
    return all(key in handoff.inputs for key in REQUIRED_INPUTS)


def number(inputs, name, default=None, *, minimum=0, maximum=math.inf, allow_zero=False):
    value = inputs.get(name, default)
    if (isinstance(value, bool) or not isinstance(value, (float, int))
            or not math.isfinite(value) or value > maximum
            or (value < minimum if allow_zero else value <= minimum)):
        raise EngineeringError(f"Neveljaven numerični parameter: {name}.")
    return value


def construction(inputs):
    load = number(inputs, "payload_kg")
    length = number(inputs, "platform_length_mm")
    width = number(inputs, "platform_width_mm")
    low = number(inputs, "min_height_mm")
    high = number(inputs, "max_height_mm")
    arm = number(inputs, "arm_length_mm", 1100)
    offset = number(inputs, "structure_offset_mm", 100, allow_zero=True)
    anchor = number(inputs, "cylinder_base_x_mm", 250)
    fraction = number(inputs, "rod_pin_fraction", 0.5, maximum=1)
    moving_mass = number(inputs, "moving_mass_kg", 100, allow_zero=True)
    factor = number(inputs, "load_factor", 1.3)
    if factor < 1:
        raise EngineeringError("Zahtevan load_factor >= 1.")
    efficiency = number(inputs, "mechanical_efficiency", 0.85, maximum=1)
    if not offset < low < high < offset + arm or arm > length:
        raise EngineeringError("Geometrija ni izvedljiva: zahtevano 0 < Hmin-offset < Hmax-offset < L <= dolžina ploščadi.")
    if anchor >= math.sqrt(arm**2 - (high - offset)**2):
        raise EngineeringError("Vpetje cilindra je zunaj najmanjšega razpona podnožja.")
    if "lift_time_s" in inputs:
        number(inputs, "lift_time_s")
    design_load = (load + moving_mass) * 9.81 * factor
    rows = []
    for index in range(11):
        height = low + (high - low) * index / 10
        h = height - offset
        span = math.sqrt(arm**2 - h**2)
        pin = [fraction * span, fraction * h]
        cylinder = math.hypot(pin[0] - anchor, pin[1])
        derivative = anchor * fraction * h / (cylinder * span)
        rows.append({"platform_height_mm": height, "scissor_height_mm": h,
                     "span_mm": span, "angle_deg": math.degrees(math.asin(h / arm)),
                     "A_mm": [0.0, 0.0], "B_mm": [span, 0.0],
                     "C_mm": [span, h], "D_mm": [0.0, h],
                     "cross_pin_mm": [span / 2, h / 2],
                     "cylinder_base_mm": [anchor, 0.0], "cylinder_rod_pin_mm": pin,
                     "cylinder_length_mm": cylinder, "dl_dH": derivative,
                     "cylinder_force_N": design_load / (efficiency * derivative)})
    if rows[-1]["cylinder_length_mm"] - rows[0]["cylinder_length_mm"] >= rows[0]["cylinder_length_mm"]:
        raise EngineeringError("Hod presega zaprto dolžino: običajnega enostopenjskega cilindra ni mogoče vgraditi.")
    return {"status": "preliminary", "engineering_verified": False,
            "mechanism": "single_stage_two_parallel_scissor_planes_one_central_extension_cylinder",
            "coordinate_system": "x vzdolž ploščadi, z navzgor; A=(0,0); mm; prečni sredini cilindra y=width/2",
            "scissor_plane_y_mm": [width / 8, 7 * width / 8], "cylinder_y_mm": width / 2,
            "parameters": {"arm_length_mm": arm, "structure_offset_mm": offset,
                           "cylinder_base_x_mm": anchor, "rod_pin_fraction": fraction,
                           "moving_mass_kg": moving_mass, "load_factor": factor,
                           "mechanical_efficiency": efficiency, "gravity_m_s2": 9.81},
            "assumptions": ["Dve ravnini s po dvema rokama in sredinskim sklepom; skupaj štiri roke; sintetičen prečni odmik width/8.",
                            "A je spodnji fiksni sklep, B spodnji drsnik, D zgornji sklep na ploščadi, C zgornji drsnik.",
                            "En cilinder v sredini širine prek toge prečke poganja obe ravnini; sila ni deljena z dve.",
                            "Offset vsebuje skupno višino podnožja in ploščadi; navpična ovojnica ni načrt detajlov.",
                            "Vsa predpostavljena premična masa sledi ploščadi; masa rok je konzervativno zgoščena na vrhu.",
                            "Kvazistatičen centričen tovor; load_factor ni predpisan standardni varnostni faktor.",
                            "Vpetje bata je na deležu f roke AC; pozitivno podaljševanje cilindra dviga ploščad.",
                            "Idealni členi brez upogiba; trenje modelira skupni mehanski izkoristek."],
            "assumption_sources": {key: "input" if key in inputs else "synthetic_default"
                                   for key in ("arm_length_mm", "structure_offset_mm", "cylinder_base_x_mm",
                                               "rod_pin_fraction", "moving_mass_kg", "load_factor", "mechanical_efficiency")},
            "lift_mm": high - low, "design_vertical_load_N": design_load,
            "cylinder_closed_pin_mm": rows[0]["cylinder_length_mm"],
            "cylinder_open_pin_mm": rows[-1]["cylinder_length_mm"],
            "stroke_mm": rows[-1]["cylinder_length_mm"] - rows[0]["cylinder_length_mm"],
            "peak_cylinder_force_N": rows[0]["cylinder_force_N"],
            "peak_basis": "Analitično F pada s H za a,f>0 in 0<h<L; največja sila je v spodnji legi.",
            "positions": rows}


def hydraulics(inputs, constructor):
    if constructor.get("status") != "preliminary" or len(constructor.get("positions", [])) != 11:
        raise EngineeringError("Hidravlik nima popolne geometrijske predaje.")
    forces = [row["cylinder_force_N"] for row in constructor["positions"]]
    peak = max(forces)
    time = inputs.get("lift_time_s")
    if time is not None:
        time = number(inputs, "lift_time_s")
    pressure_options = []
    for pressure in (160, 200, 250, 315):
        area = peak / (pressure * 0.1)  # 1 bar = 0.1 N/mm²
        pressure_options.append({"pressure_bar": pressure, "theoretical_bore_mm": math.sqrt(4 * area / math.pi),
                                 "piston_area_mm2": area})
    chosen = pressure_options[1]  # Calculation reference only, not a purchased/selected cylinder.
    flow = None
    power = None
    if time is not None:
        speed = constructor["lift_mm"] / time
        flow = [chosen["piston_area_mm2"] * r["dl_dH"] * speed * 60 / 1e6
                for r in constructor["positions"]]
        power = [200 * q / 600 for q in flow]  # bar * L/min / 600 = kW
    return {"status": "preliminary", "engineering_verified": False,
            "source_constructor_sha256": digest(constructor),
            "force_curve": [{"platform_height_mm": r["platform_height_mm"],
                             "cylinder_length_mm": r["cylinder_length_mm"], "force_N": r["cylinder_force_N"]}
                            for r in constructor["positions"]],
            "max_force_N": peak, "pressure_options": pressure_options,
            "reference_pressure_bar": 200, "lift_time_s": time,
            "flow_L_min": flow, "hydraulic_power_kW": power,
            "shaft_power_kW": None,
            "flow_basis": "Konstantna hitrost ploščadi, teoretični premer pri 200 bar; pQ je moč pri nastavljeni meji tlaka.",
            "limitations": ["Brez lift_time_s pretok in moč nista določena.",
                            "Premeri so teoretični za izteg, brez protitlaka in tlačnih izgub; ne pomenijo izbire standardnega cilindra.",
                            "Potrebni so preverba uklona batnice, mrtvih dolžin, bočnih sil, tesnil in dejanske vgradne dolžine.",
                            "Moč na gredi ni določena brez podatkov o izkoristku črpalke/pogona."],
            "safety_functions": ["Nosilni/zadrževalni ventil ob cilindru in zaščita ob pretrgu cevi.",
                                 "Tlačni omejevalni ventil in nadzorovano spuščanje.",
                                 "Mehanska servisna opora, varovanje škarij in preprečitev nenamernega gibanja.",
                                 "Končna stikala, zaustavitev v sili in analiza tveganja; zasnovo mora preveriti strokovnjak."]}


def economics(constructor, hydraulic):
    length = constructor["parameters"]["arm_length_mm"]
    items = allowed_cost_items(length)
    return {"status": "incomplete_estimate", "engineering_verified": False,
            "source_constructor_sha256": digest(constructor), "source_hydraulics_sha256": digest(hydraulic),
            "verified_prices": [], "cost_items": items,
            "synthetic_subtotal_EUR": sum(row["amount_EUR"] or 0 for row in items),
            "total_EUR": None, "basis": "Nepopoln sintetičen vmesni seštevek, brez DDV in dobaviteljskih ponudb."}
