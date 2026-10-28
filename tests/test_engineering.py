"""Analytic fixtures, finite-difference checks and deliberately corrupted handoffs."""

from copy import deepcopy
import json
import math
import os
from unittest.mock import patch
from pathlib import Path
import tempfile
import unittest

from src.agents.simulated import SimulatedAgent, default_agents
from src.agents.openai_agent import openai_agents
from src.engineering.calculations import EngineeringError, construction
from src.engineering.review import review
from src.models import Handoff
from src.models.contracts import digest
from src.orchestrator import Orchestrator
from src.orchestrator.cycles import CycleRunner
from test_ai_cycles import FakeTransport, handoff


def cycle(value=None):
    value = value or handoff()
    return Orchestrator().run(value, expected_variant=value.variant, expected_revision=value.revision)


def stages(result):
    return [result.results[name]["engineering"] for name in ("konstruktor", "hidravlik", "ekonomist")]


class EngineeringTests(unittest.TestCase):
    def test_schema_rejects_nonfinite_and_null_numerical_claims(self):
        from src.models.contracts import CALCULATION, validate_schema
        for value in (True, None, float("inf"), float("nan"), "650"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_schema({"quantity": "lift_mm", "value": value, "unit": "mm"}, CALCULATION)

    def test_oversized_required_stroke_is_not_a_packagable_standard_cylinder(self):
        inputs = handoff().inputs
        inputs["cylinder_base_x_mm"] = 500
        with self.assertRaisesRegex(EngineeringError, "Hod presega"):
            construction(inputs)

    def test_bad_geometry_is_rejected_before_any_ai_request(self):
        transport = FakeTransport()
        value = handoff()
        value.inputs["max_height_mm"] = 1200
        with self.assertRaises(EngineeringError):
            Orchestrator(openai_agents(transport)).run(value, expected_variant="V01", expected_revision="R01")
        self.assertEqual(transport.calls, [])

    def test_cloud_process_success_does_not_mean_technical_approval(self):
        from src.orchestrator.cloud import TrialConfig, run_trial, APPROVALS
        config = TrialConfig("simulated", "gpt-5.4-mini", 1500, 48000, APPROVALS["simulated"])
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}):
            run_trial(config, directory)
            report = json.loads((Path(directory)/"report.json").read_text())
            self.assertEqual(report["status"], "awaiting_approval")
            self.assertEqual(report["technical_status"], "changes_required")
            self.assertFalse(report["engineering_verified"])
            self.assertEqual(report["api_requests_started"], 0)

    def test_reference_endpoints_and_stroke_from_independent_triangle(self):
        result = cycle()
        c, h, e = stages(result)
        self.assertEqual(c["lift_mm"], 650)
        self.assertEqual(len(c["positions"]), 11)
        for row, height in ((c["positions"][0], 350), (c["positions"][-1], 1000)):
            z = height - 100
            x = math.sqrt(1100**2 - z**2)
            length = math.sqrt((x / 2 - 250)**2 + (z / 2)**2)
            self.assertAlmostEqual(row["span_mm"], x)
            self.assertAlmostEqual(row["cylinder_length_mm"], length)
            self.assertAlmostEqual(math.dist(row["A_mm"], row["C_mm"]), 1100)
            self.assertAlmostEqual(math.dist(row["B_mm"], row["D_mm"]), 1100)
        self.assertAlmostEqual(c["stroke_mm"], 143.08392948278532)
        self.assertTrue(result.results["recenzent"]["engineering"]["calculation_check_passed"])
        self.assertFalse(result.results["recenzent"]["engineering_verified"])

    def test_force_is_virtual_work_for_one_cylinder_and_peak_is_lower_end(self):
        c = stages(cycle())[0]
        forces = []
        for row in c["positions"]:
            z = row["scissor_height_mm"]
            def length(height):
                return math.sqrt((math.sqrt(1100**2-height**2)/2-250)**2 + (height/2)**2)
            derivative = (length(z+0.001)-length(z-0.001))/.002
            expected = 400 * 9.81 * 1.3 / (.85 * derivative)
            self.assertAlmostEqual(row["cylinder_force_N"], expected, places=3)
            forces.append(row["cylinder_force_N"])
        self.assertAlmostEqual(max(forces), 64136.449795429, places=5)
        self.assertEqual(forces, sorted(forces, reverse=True))

    def test_pressure_conversions_and_missing_time_are_not_invented(self):
        c, h, _ = stages(cycle())
        self.assertEqual([p["pressure_bar"] for p in h["pressure_options"]], [160, 200, 250, 315])
        for option in h["pressure_options"]:
            area_m2 = math.pi * (option["theoretical_bore_mm"] / 1000)**2 / 4
            self.assertAlmostEqual(area_m2 * option["pressure_bar"] * 100000, h["max_force_N"])
        self.assertIsNone(h["flow_L_min"])
        self.assertIsNone(h["hydraulic_power_kW"])
        self.assertIsNone(h["shaft_power_kW"])
        self.assertEqual(h["source_constructor_sha256"], digest(c))

    def test_time_enables_variable_flow_and_pressure_limit_power_only(self):
        value = handoff()
        value.inputs["lift_time_s"] = 20
        value.input_sources["lift_time_s"] = "synthetic:test"
        c, h, _ = stages(cycle(value))
        self.assertEqual(len(h["flow_L_min"]), 11)
        for row, flow, power in zip(c["positions"], h["flow_L_min"], h["hydraulic_power_kW"]):
            area_m2 = h["pressure_options"][1]["piston_area_mm2"] / 1e6
            cylinder_speed_m_s = row["dl_dH"] * .650 / 20
            self.assertAlmostEqual(flow, area_m2 * cylinder_speed_m_s * 60000)
            self.assertAlmostEqual(power, 20e6 * flow / 60000 / 1000)
        self.assertTrue(cycle(value).results["recenzent"]["engineering"]["calculation_check_passed"])

    def test_infeasible_or_singular_geometry_stops_with_explicit_reason(self):
        for change in ({"max_height_mm": 1200}, {"min_height_mm": 100},
                       {"arm_length_mm": 1300}, {"cylinder_base_x_mm": 0},
                       {"cylinder_base_x_mm": 700}, {"rod_pin_fraction": 0},
                       {"mechanical_efficiency": 1.1}, {"load_factor": .9},
                       {"moving_mass_kg": -1}, {"lift_time_s": 0},
                       {"arm_length_mm": float("nan")}):
            value = handoff()
            value.inputs.update(change)
            value.input_sources = {key: "synthetic:test" for key in value.inputs}
            with self.subTest(change=change), self.assertRaises(ValueError):
                cycle(value)

    def test_zero_extra_mass_and_explicit_parameters_are_traceable(self):
        value = handoff()
        value.inputs.update(moving_mass_kg=0, arm_length_mm=1150)
        value.input_sources = {key: "synthetic:test" for key in value.inputs}
        c = stages(cycle(value))[0]
        self.assertEqual(c["parameters"]["moving_mass_kg"], 0)
        self.assertEqual(c["assumption_sources"]["arm_length_mm"], "input")
        self.assertEqual(c["assumption_sources"]["mechanical_efficiency"], "synthetic_default")

    def test_independent_review_detects_geometry_force_pressure_units_and_price_errors(self):
        result = cycle()
        changes = [
            (0, "konstruktor", lambda c: c["positions"][0].update(span_mm=10)),
            (0, "konstruktor", lambda c: c["positions"][0].update(cylinder_force_N=1)),
            (0, "konstruktor", lambda c: c["positions"][0].update(cylinder_base_mm=[0, 0])),
            (0, "konstruktor", lambda c: c["units"].update(length="m")),
            (1, "hidravlik", lambda h: h["pressure_options"][0].update(theoretical_bore_mm=5)),
            (1, "hidravlik", lambda h: h["force_curve"].pop()),
            (2, "ekonomist", lambda e: e["cost_items"][0].update(price_kind="verified")),
            (2, "ekonomist", lambda e: e.update(total_EUR=1200))]
        for index, owner, change in changes:
            values = deepcopy(stages(result))
            change(values[index])
            audit = review(result.inputs, *values)
            with self.subTest(owner=owner, change=change):
                self.assertEqual(audit["status"], "blocked")
                self.assertFalse(audit["calculation_check_passed"])
                self.assertTrue(any(f["severity"] == "critical" and f["target_agent"] == owner for f in audit["findings"]))

    def test_missing_constructor_data_is_rejected_without_inventing_hydraulics(self):
        from src.agents.openai_agent import OpenAIAgent
        value = handoff()
        value.results = {"konstruktor": {}}
        transport = FakeTransport()
        with self.assertRaises(EngineeringError):
            OpenAIAgent("hidravlik", transport).run(value)
        self.assertEqual(transport.calls, [])

    def test_incomplete_review_input_is_blocked(self):
        audit = review(handoff().inputs, {}, {}, {})
        self.assertEqual(audit["status"], "blocked")
        self.assertFalse(audit["engineering_verified"])

    def test_costs_separate_unknown_from_synthetic_and_never_claim_offers(self):
        c, h, e = stages(cycle())
        self.assertEqual(e["verified_prices"], [])
        self.assertEqual(e["synthetic_subtotal_EUR"], 1120)
        self.assertIsNone(e["total_EUR"])
        self.assertEqual(e["source_hydraulics_sha256"], digest(h))
        self.assertTrue(all(i["amount_EUR"] is None for i in e["cost_items"] if i["price_kind"] == "unknown"))

    def test_bad_ai_numbers_missing_claims_wrong_units_and_fake_offers_stop_immediately(self):
        changes = [lambda d: d["calculations"][0].update(value=1),
                   lambda d: d["calculations"][0].update(unit="m"),
                   lambda d: d["calculations"].pop(),
                   lambda d: d["calculations"][0].update(value=True),
                   lambda d: d.update(cost_items=[{"category": "offer", "price_kind": "verified", "amount_EUR": 12, "source": "imaginary"}])]
        for change in changes:
            transport = FakeTransport(change=change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                Orchestrator(openai_agents(transport)).run(handoff(), expected_variant="V01", expected_revision="R01")
            self.assertEqual(len(transport.calls), 1)

    def test_model_cannot_approve_preliminary_design(self):
        def approve(data):
            if data["agent"] == "recenzent":
                data.update(decision="accepted", findings=[])
        transport = FakeTransport(change=approve)
        with self.assertRaises(EngineeringError):
            Orchestrator(openai_agents(transport)).run(handoff(), expected_variant="V01", expected_revision="R01")

    def test_corrupted_stage_is_not_passed_to_next_agent_and_failure_is_recorded(self):
        class BadConstructor:
            name = "konstruktor"
            def run(self, value):
                result = SimulatedAgent(self.name).run(value)
                result.results[self.name]["engineering"]["positions"][0]["cylinder_force_N"] = 0
                return result
        agents = (BadConstructor(), *default_agents()[1:])
        with tempfile.TemporaryDirectory() as directory:
            runner = CycleRunner(Path(directory), Orchestrator(agents))
            with self.assertRaises(EngineeringError):
                runner.run(handoff(), approved_label="V01-R01")
            record = json.loads((Path(directory)/"V01-R01.json").read_text())
            self.assertEqual(record["status"], "stopped")
            self.assertEqual(record["handoff"]["results"], {})
            self.assertEqual(record["error"]["code"], "engineering_validation_failed")

    def test_legacy_minimal_handoff_is_explicitly_not_evaluated(self):
        value = Handoff("V01", "R01", {})
        result = cycle(value)
        self.assertTrue(all(r["technical_status"] == "not_evaluated" and r["engineering_verified"] is False
                            for r in result.results.values()))
