"""Independent residual/finite-difference checks on the actual handed-over numbers."""

import math
from src.models.contracts import digest
from .costs import allowed_cost_items, cost_issues


def review(inputs, constructor, hydraulic, economic, *, cost_catalogue=None):
    checks = []
    findings = []

    def check(name, owner, condition):
        checks.append({"check": name, "target_agent": owner, "status": "pass" if condition else "fail"})
        if not condition:
            findings.append({"id": f"M{len(findings)+1:02d}", "severity": "critical", "status": "open",
                             "target_agent": owner, "description": name,
                             "required_correction": "Popravi numerično predajo in ponovno preveri izračun."})

    try:
        p = constructor["parameters"]
        rows = constructor["positions"]
        arm = p["arm_length_mm"]
        a = p["cylinder_base_x_mm"]
        f = p["rod_pin_fraction"]
        close = lambda x, y: math.isclose(x, y, rel_tol=1e-5, abs_tol=1e-3)
        defaults = {"arm_length_mm": 1100, "structure_offset_mm": 100,
                    "cylinder_base_x_mm": 250, "rod_pin_fraction": .5,
                    "moving_mass_kg": 100, "load_factor": 1.3, "mechanical_efficiency": .85}
        check("parametri in predpostavke sledijo vhodom", "konstruktor",
              all(close(p[key], inputs.get(key, value)) for key, value in defaults.items()))
        check("enote geometrije in hidravlike", "konstruktor",
              constructor.get("units", {}).get("length") == "mm"
              and constructor.get("units", {}).get("force") == "N"
              and hydraulic.get("units", {}).get("pressure") == "bar")
        check("prečna razporeditev", "konstruktor",
              constructor["scissor_plane_y_mm"] == [inputs["platform_width_mm"]/8, 7*inputs["platform_width_mm"]/8]
              and close(constructor["cylinder_y_mm"], inputs["platform_width_mm"]/2))
        check("višina in dvig", "konstruktor", len(rows) == 11
              and close(rows[0]["platform_height_mm"], inputs["min_height_mm"])
              and close(rows[-1]["platform_height_mm"], inputs["max_height_mm"])
              and close(constructor["lift_mm"], inputs["max_height_mm"] - inputs["min_height_mm"]))
        geometry_ok = force_ok = True
        for index, r in enumerate(rows):
            H, h, s = r["platform_height_mm"], r["scissor_height_mm"], r["span_mm"]
            cylinder = r["cylinder_length_mm"]
            expected_points = {"A_mm": [0, 0], "B_mm": [s, 0], "C_mm": [s, h], "D_mm": [0, h],
                               "cross_pin_mm": [s/2, h/2], "cylinder_base_mm": [a, 0]}
            geometry_ok &= all(len(r[key]) == 2 and all(close(x, y) for x, y in zip(r[key], coords))
                               for key, coords in expected_points.items())
            geometry_ok &= close(r["angle_deg"], math.degrees(math.atan2(h, s)))
            expected_height = inputs["min_height_mm"] + index * constructor["lift_mm"] / 10
            geometry_ok &= (close(H, expected_height) and close(h + p["structure_offset_mm"], H)
                            and close(math.dist(r["A_mm"], r["C_mm"]), arm)
                            and close(math.dist(r["B_mm"], r["D_mm"]), arm)
                            and close(s*s + h*h, arm*arm) and s <= inputs["platform_length_mm"]
                            and close(math.dist(r["cylinder_base_mm"], r["cylinder_rod_pin_mm"]), cylinder)
                            and all(close(x, y) for x, y in zip(r["cylinder_rod_pin_mm"], (f*s, f*h))))
            # Independent numerical derivative, not the producer's analytic dl/dH.
            def pin_length(height):
                span = math.sqrt(arm*arm - height*height)
                return math.sqrt((f*span-a)**2 + (f*height)**2)
            step = min(0.001, h / 100, (arm-h) / 100)
            derivative = (pin_length(h + step) - pin_length(h - step)) / (2*step)
            demand = ((inputs["payload_kg"] + p["moving_mass_kg"]) * 9.81 * p["load_factor"])
            force_ok &= (close(derivative, r["dl_dH"])
                         and close(r["cylinder_force_N"] * derivative * p["mechanical_efficiency"], demand))
        check("dolžine rok, vpetja in položaji", "konstruktor", bool(geometry_ok))
        check("virtualno delo s končno diferenco", "konstruktor", bool(force_ok))
        check("hod in največja sila", "konstruktor",
              close(constructor["stroke_mm"], rows[-1]["cylinder_length_mm"] - rows[0]["cylinder_length_mm"])
              and close(constructor["peak_cylinder_force_N"], max(r["cylinder_force_N"] for r in rows)))
        check("sled hidravlične predaje", "hidravlik", hydraulic["source_constructor_sha256"] == digest(constructor))
        check("krivulja sile hidravlike", "hidravlik", len(hydraulic["force_curve"]) == len(rows)
              and all(close(c["force_N"], r["cylinder_force_N"])
                      and close(c["cylinder_length_mm"], r["cylinder_length_mm"])
                      and close(c["platform_height_mm"], r["platform_height_mm"])
                      for c, r in zip(hydraulic["force_curve"], rows)))
        peak = max(r["cylinder_force_N"] for r in rows)
        check("premeri in enote bar/N/mm²", "hidravlik", close(hydraulic["max_force_N"], peak)
              and [p["pressure_bar"] for p in hydraulic["pressure_options"]] == [160, 200, 250, 315]
              and all(close(math.pi * option["theoretical_bore_mm"]**2 / 4, option["piston_area_mm2"])
                      and close(math.pi * option["theoretical_bore_mm"]**2 / 4 * option["pressure_bar"] * .1, peak)
                      for option in hydraulic["pressure_options"]))
        if inputs.get("lift_time_s") is None:
            check("brez časa ni pretoka ali moči", "hidravlik", hydraulic["flow_L_min"] is None
                  and hydraulic["hydraulic_power_kW"] is None)
        else:
            area = hydraulic["pressure_options"][1]["piston_area_mm2"]
            flows = hydraulic["flow_L_min"]
            powers = hydraulic["hydraulic_power_kW"]
            check("pretoki in hidravlična moč", "hidravlik", len(flows) == len(rows) == len(powers)
                  and all(close(q, area * r["dl_dH"] * constructor["lift_mm"] / inputs["lift_time_s"] * 60 / 1e6)
                          and close(power, 200 * q / 600) for q, power, r in zip(flows, powers, rows)))
        check("sled stroškov", "ekonomist", economic["source_constructor_sha256"] == digest(constructor)
              and economic["source_hydraulics_sha256"] == digest(hydraulic))
        for problem in cost_issues(economic.get("cost_items"), allowed_cost_items(arm) if cost_catalogue is None else cost_catalogue):
            check(f"stroški: {problem['path']} ({problem['category']}): {problem['reason']}", "ekonomist", False)
        check("izvor cen in nepopolna ocena", "ekonomist", economic["verified_prices"] == []
              and economic["total_EUR"] is None
              and all(item["price_kind"] in ("synthetic", "unknown") and bool(item["source"])
                      and ((item["amount_EUR"] is None) == (item["price_kind"] == "unknown"))
                      for item in economic["cost_items"])
              and close(economic["synthetic_subtotal_EUR"], sum(item["amount_EUR"] or 0 for item in economic["cost_items"])))
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        check("nepopolna ali neveljavna numerična predaja", "recenzent", False)
    for owner, text in (("konstruktor", "Preveri napetosti, uklon rok, sornike, drsnike, zvare, stabilnost in nesrediščno obremenitev."),
                        ("hidravlik", "Preveri vgradno dolžino in uklon batnice, pretok, ventile, tlačne izgube ter varno spuščanje."),
                        ("ekonomist", "Pridobi preverljive ponudbe in ovrednoti neznane stroške.")):
        findings.append({"id": f"R{len(findings)+1:02d}", "severity": "major", "status": "open",
                         "target_agent": owner, "description": text, "required_correction": text})
    return {"status": "blocked" if any(c["status"] == "fail" for c in checks) else "changes_required",
            "engineering_verified": False, "checks": checks, "findings": findings,
            "calculation_check_passed": all(c["status"] == "pass" for c in checks)}
