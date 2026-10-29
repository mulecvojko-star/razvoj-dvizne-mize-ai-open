"""Cost regressions use synthetic responses, not the unavailable failed AI response."""

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.agents.openai_agent import openai_agents, prepare_instructions, prompt_parts
from src.agents.simulated import SimulatedAgent
from src.engineering.calculations import EngineeringError
from src.engineering.contracts import response_schema, validate_cost_items
from src.engineering.costs import allowed_cost_items, cost_issues
from src.engineering.review import review
from src.models.contracts import RESPONSE_SCHEMA, validate_schema
from src.orchestrator.cloud import APPROVALS, TrialConfig, run_trial
from src.orchestrator.pipeline import Orchestrator
from test_ai_cycles import FakeTransport, handoff


def economist_handoff():
    value = handoff()
    for name in ("konstruktor", "hidravlik"):
        value = SimulatedAgent(name).run(value)
    return value


class CostHandoffTests(unittest.TestCase):
    def setUp(self):
        self.items = allowed_cost_items(1100)

    def test_correct_costs_allow_reordering_and_equivalent_json_number_forms(self):
        rows = deepcopy(self.items[::-1])
        rows[-1]["amount_EUR"] = 220  # same value as reference 220.0
        validate_cost_items(rows, self.items)
        self.assertEqual(cost_issues(rows, self.items), [])
        self.assertTrue(all(r["price_kind"] != "verified" for r in self.items))

    def test_binary_float_artifact_does_not_reject_the_same_cent_value(self):
        legacy = deepcopy(self.items)
        legacy[0]["amount_EUR"] = 4 * 1100 / 1000 * 50
        ordinary = deepcopy(self.items)
        ordinary[0]["amount_EUR"] = 220
        self.assertNotEqual(legacy, ordinary)  # exact old list guard would fail
        validate_cost_items(ordinary, legacy)
        validate_cost_items(legacy, self.items)
        self.assertEqual(self.items[0]["amount_EUR"], 220.0)
        self.assertEqual(allowed_cost_items(1111.11)[0]["amount_EUR"], 222.22)

    def test_field_specific_rejections_keep_source_private(self):
        cases = [
            (lambda r: r[0].update(amount_EUR=220.001), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=220.01), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=221), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=True), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR="220"), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=1e100), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=10**1000), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=float("nan")), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(amount_EUR=None), "arms", "amount_EUR", "amount_mismatch"),
            (lambda r: r[0].update(price_kind="verified"), "arms", "price_kind", "price_kind_mismatch"),
            (lambda r: r[0].update(source="private-untrusted-provider-text"), "arms", "source", "source_mismatch"),
            (lambda r: r[0].update(source=""), "arms", "source", "source_mismatch"),
            (lambda r: r[0].pop("source"), "arms", "source", "missing_field"),
            (lambda r: r[3].update(amount_EUR=0), "hydraulic_unit", "amount_EUR", "amount_mismatch"),
            (lambda r: r[3].update(amount_EUR="null"), "hydraulic_unit", "amount_EUR", "amount_mismatch"),
            (lambda r: r[3].update(price_kind="synthetic"), "hydraulic_unit", "price_kind", "price_kind_mismatch"),
        ]
        for change, category, field, reason in cases:
            rows = deepcopy(self.items)
            change(rows)
            with self.subTest(field=field, reason=reason), self.assertRaises(EngineeringError) as caught:
                validate_cost_items(rows, self.items)
            detail = caught.exception.details[0]
            self.assertEqual((detail["category"], detail["field"], detail["reason"]), (category, field, reason))
            self.assertIn(field, detail["path"])
            self.assertNotIn("private-untrusted-provider-text", str(caught.exception))
            self.assertNotIn("private-untrusted-provider-text", json.dumps(caught.exception.details))
            json.dumps(caught.exception.details, allow_nan=False)

    def test_missing_duplicate_unknown_and_extra_costs_are_not_silently_repaired(self):
        for change, reason in ((lambda r: r.pop(), "missing_category"),
                               (lambda r: r.append(deepcopy(r[0])), "duplicate_category"),
                               (lambda r: r[0].update(category="invented-offer"), "unknown_category"),
                               (lambda r: r[0].update(extra="not allowed"), "unexpected_fields")):
            rows = deepcopy(self.items)
            change(rows)
            with self.subTest(reason=reason), self.assertRaises(EngineeringError) as caught:
                validate_cost_items(rows, self.items)
            self.assertIn(reason, {d["reason"] for d in caught.exception.details})
        for rows, reason in ((None, "expected_array"), ({}, "expected_array"), (["bad"], "expected_object")):
            with self.subTest(rows=rows), self.assertRaises(EngineeringError) as caught:
                validate_cost_items(rows, self.items)
            self.assertEqual(caught.exception.details[0]["reason"], reason)

    def test_economist_schema_matches_the_actual_catalogue_and_prompt(self):
        value = economist_handoff()
        schema = response_schema(value)
        instructions, expected = prepare_instructions("ekonomist", value)
        self.assertEqual(expected["cost_items"], self.items)
        self.assertIn("DOVOLJENI COST_ITEMS", instructions)
        self.assertIn(json.dumps(self.items, ensure_ascii=False), instructions)
        self.assertEqual(json.loads(prompt_parts(instructions, value)["schema"]), schema)
        array = schema["properties"]["cost_items"]
        self.assertEqual((array["minItems"], array["maxItems"]), (6, 6))
        self.assertEqual(len(array["items"]["anyOf"]), 6)
        validate_schema(self.items[::-1], array)
        for field, new_value in (("source", "paraphrased"), ("price_kind", "verified"),
                                 ("amount_EUR", 221), ("category", "new")):
            rows = deepcopy(self.items)
            rows[0][field] = new_value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_schema(rows, array)
        self.assertEqual(response_schema(handoff()), RESPONSE_SCHEMA)  # other roles remain compatible
        self.assertNotIn("minItems", RESPONSE_SCHEMA["properties"]["cost_items"])

    def test_schema_price_follows_constructor_arm_length(self):
        value = handoff()
        value.inputs["arm_length_mm"] = 1150
        value.input_sources["arm_length_mm"] = "synthetic:test"
        for name in ("konstruktor", "hidravlik"):
            value = SimulatedAgent(name).run(value)
        array = response_schema(value)["properties"]["cost_items"]
        validate_schema(allowed_cost_items(1150), array)
        with self.assertRaises(ValueError):
            validate_schema(self.items, array)

    def test_invalid_third_response_records_exact_item_field_reason_without_fourth_call(self):
        def alter(data):
            if data["agent"] == "ekonomist":
                data["cost_items"][2]["source"] = "private-untrusted-provider-text"
        fake = FakeTransport(change=alter)
        fake.close = Mock()
        config = TrialConfig("openai", "gpt-5.4-mini", 1500, 48000, APPROVALS["openai"],
                             dict(konstruktor=2500, hidravlik=2500, ekonomist=3000, recenzent=3500))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
                patch("src.orchestrator.cloud.OpenAITransport", return_value=fake):
            with self.assertRaises(EngineeringError):
                run_trial(config, directory)
            record = json.loads((Path(directory)/"runs/V01-R01.json").read_text())
            report = json.loads((Path(directory)/"report.json").read_text())
            self.assertEqual(report["api_requests_started"], 3)
            self.assertEqual(report["technical_status"], "not_completed")
            self.assertFalse(report["engineering_verified"])
            self.assertEqual(list(record["handoff"]["results"]), ["konstruktor", "hidravlik"])
            detail = report["validation_details"][0]
            self.assertEqual(detail["path"], "cost_items[2].source")
            self.assertEqual(detail["category"], "cylinder")
            self.assertEqual(detail["reason"], "source_mismatch")
            self.assertEqual(record["error"]["details"], report["validation_details"])
            self.assertNotIn("result.json", [p.name for p in Path(directory).iterdir()])
            for path in Path(directory).rglob("*.json"):
                self.assertNotIn("private-untrusted-provider-text", path.read_text())
        self.assertEqual(len(fake.calls), 3)
        fake.close.assert_called_once()

    def test_missing_field_also_has_diagnostics_before_generic_schema_error(self):
        def alter(data):
            if data["agent"] == "ekonomist":
                data["cost_items"][0].pop("amount_EUR")
        fake = FakeTransport(change=alter)
        with self.assertRaises(EngineeringError) as caught:
            Orchestrator(openai_agents(fake)).run(handoff(), expected_variant="V01", expected_revision="R01")
        self.assertEqual(caught.exception.details[0]["field"], "amount_EUR")
        self.assertEqual(caught.exception.details[0]["reason"], "missing_field")
        self.assertEqual(len(fake.calls), 3)

    def test_independent_review_flags_item_and_does_not_approve_costs(self):
        result = Orchestrator().run(handoff(), expected_variant="V01", expected_revision="R01")
        c, h, e = [result.results[n]["engineering"] for n in ("konstruktor", "hidravlik", "ekonomist")]
        e = deepcopy(e)
        e["cost_items"][0]["source"] = "invented verified price"
        audit = review(result.inputs, c, h, e)
        self.assertEqual(audit["status"], "blocked")
        self.assertFalse(audit["engineering_verified"])
        self.assertTrue(any("cost_items[0].source" in f["description"] and f["target_agent"] == "ekonomist"
                            for f in audit["findings"]))

    def test_reordered_valid_model_costs_complete_cycle_but_never_approve_design(self):
        def alter(data):
            if data["agent"] == "ekonomist":
                data["cost_items"].reverse()
        fake = FakeTransport(change=alter)
        result = Orchestrator(openai_agents(fake)).run(handoff(), expected_variant="V01", expected_revision="R01")
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(result.results["recenzent"]["decision"], "changes_required")
        self.assertFalse(result.results["ekonomist"]["engineering_verified"])
        self.assertEqual(result.results["ekonomist"]["engineering"]["verified_prices"], [])
