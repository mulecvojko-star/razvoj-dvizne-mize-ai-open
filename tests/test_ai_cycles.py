"""Offline integration tests. No real credentials or model requests."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from src.agents.openai_agent import ModelError, OpenAIAgent, OpenAITransport, openai_agents
from src.agents.simulated import ORDER
from src.models import Handoff
from src.models.contracts import digest, validate_review
from src.orchestrator import Orchestrator
from src.orchestrator.cycles import CycleRunner

ROOT = Path(__file__).resolve().parents[1]


def handoff(revision="R01"):
    data = json.loads((ROOT / "examples/V01-R01.json").read_text())
    data["revision"] = revision
    data["input_sources"] = {key: "synthetic:fixture" for key in data["inputs"]}
    return Handoff(**data)


def answer(name, incoming):
    return {"variant": incoming.variant, "revision": incoming.revision, "agent": name,
            "summary": f"Pregled: {name}", "assumptions": ["Sintetični podatki."],
            "outputs": [{"name": "ocena", "value": "nepreverjeno", "unit": "n/a",
                         "basis": "Učni primer."}], "open_questions": [f"Vprašanje {name}"],
            "decision": "changes_required" if name == "recenzent" else "not_applicable",
            "findings": [{"id": "F1", "severity": "critical", "status": "open",
                          "description": "Manjka geometrija.",
                          "required_correction": "Dopolni geometrijo."}] if name == "recenzent" else []}


class FakeTransport:
    def __init__(self, change=None, fail_at=None):
        self.calls = []
        self.change = change
        self.fail_at = fail_at

    def generate(self, instructions, incoming):
        index = len(self.calls)
        self.calls.append((instructions, deepcopy(incoming)))
        if index == self.fail_at:
            raise ModelError("Umetna napaka.")
        data = answer(ORDER[index], incoming)
        if self.change:
            self.change(data)
        return data, {"model": "offline-model", "response_id": f"fake-{index}",
                      "input_tokens": 10, "output_tokens": 20}


class AIContractTests(unittest.TestCase):
    def test_full_offline_ai_cycle_handoffs_and_provenance(self):
        transport = FakeTransport()
        original = handoff()
        with tempfile.TemporaryDirectory() as directory:
            result = CycleRunner(Path(directory), Orchestrator(openai_agents(transport))).run(
                original, approved_label="V01-R01", mode="openai")
            record = json.loads((Path(directory) / "V01-R01.json").read_text())
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(tuple(result.results), ORDER)
        for index, (instructions, incoming) in enumerate(transport.calls):
            self.assertIn(f"# {ORDER[index].capitalize()}", instructions)
            self.assertEqual(tuple(incoming.results), ORDER[:index])
            self.assertEqual(incoming.input_sources, original.input_sources)
            if index:
                self.assertEqual(incoming.results[ORDER[index - 1]], result.results[ORDER[index - 1]])
            trace = result.results[ORDER[index]]["trace"]
            self.assertEqual(trace["handoff_sha256"], digest(incoming.to_dict()))
            self.assertEqual(trace["input_sha256"], digest(original.inputs))
            self.assertFalse(result.results[ORDER[index]]["simulated"])
        self.assertEqual(len(result.open_questions), 4)
        self.assertEqual(record["status"], "awaiting_approval")
        self.assertEqual(record["review_decision"], "changes_required")
        self.assertEqual(original.results, {})

    def test_missing_wrong_or_stale_model_data_stops_before_next_agent(self):
        changes = [lambda d: d.pop("summary"), lambda d: d.update(variant="V02"),
                   lambda d: d.update(revision="R02"), lambda d: d.update(agent="recenzent"),
                   lambda d: d.update(assumptions="bad"), lambda d: d.update(extra=True),
                   lambda d: d.update(summary=""), lambda d: d.update(decision="accepted")]
        for change in changes:
            with self.subTest(change=change):
                transport = FakeTransport(change=change)
                with self.assertRaises(ValueError):
                    Orchestrator(openai_agents(transport)).run(
                        handoff(), expected_variant="V01", expected_revision="R01")
                self.assertEqual(len(transport.calls), 1)

    def test_invalid_or_missing_inputs_never_reach_transport(self):
        changes = [lambda h: h.inputs.pop("payload_kg"),
                   lambda h: h.inputs.update(payload_kg=True),
                   lambda h: h.inputs.update(payload_kg=-1),
                   lambda h: h.inputs.update(payload_kg="300"),
                   lambda h: h.inputs.update(min_height_mm=2000),
                   lambda h: h.inputs.update(data_origin="confidential"),
                   lambda h: h.input_sources.clear()]
        for change in changes:
            with self.subTest(change=change):
                transport = FakeTransport()
                value = handoff()
                change(value)
                with self.assertRaises(ValueError):
                    OpenAIAgent("konstruktor", transport).run(value)
                self.assertEqual(transport.calls, [])

    def test_non_json_and_invalid_sources_rejected(self):
        for inputs in ({"x": float("nan")}, {"x": object()}, {"x": float("inf")}):
            with self.subTest(inputs=inputs), self.assertRaises(ValueError):
                Handoff("V01", "R01", inputs)
        with self.assertRaises(ValueError):
            Handoff("V01", "R01", {"x": 1}, input_sources={"missing": "source"})

    def test_review_severity_status_corrections_and_consistency(self):
        good = answer("recenzent", handoff())
        validate_review(good)
        changes = [lambda d: d["findings"][0].update(severity="unknown"),
                   lambda d: d["findings"][0].update(status="unknown"),
                   lambda d: d["findings"][0].update(required_correction=""),
                   lambda d: d.update(decision="accepted"),
                   lambda d: d.update(findings=[]),
                   lambda d: d["findings"].append(deepcopy(d["findings"][0]))]
        for change in changes:
            value = deepcopy(good)
            change(value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_review(value)

    def test_changed_source_is_rejected(self):
        from src.agents.simulated import default_agents
        agents = list(default_agents())
        original = agents[0]

        class BadAgent:
            name = "konstruktor"

            def run(self, incoming):
                result = original.run(incoming)
                result.input_sources["payload_kg"] = "changed"
                return result

        agents[0] = BadAgent()
        with self.assertRaises(ValueError):
            Orchestrator(agents).run(handoff(), expected_variant="V01", expected_revision="R01")


class CycleTests(unittest.TestCase):
    def test_approval_is_required_for_every_revision_and_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            runner = CycleRunner(Path(directory))
            for approval in (None, "V02-R01", "V01-R02"):
                with self.subTest(approval=approval), self.assertRaises(ValueError):
                    runner.run(handoff(), approved_label=approval)
            runner.run(handoff(), approved_label="V01-R01")
            for value, approval in ((handoff(), "V01-R01"), (handoff("R03"), "V01-R03"),
                                    (handoff("R02"), None)):
                with self.assertRaises(ValueError):
                    runner.run(value, approved_label=approval)
            runner.run(handoff("R02"), approved_label="V01-R02")
            first = json.loads((Path(directory) / "V01-R01.json").read_text())
            second = json.loads((Path(directory) / "V01-R02.json").read_text())
            self.assertEqual(second["previous_record_sha256"], digest(first))
            self.assertEqual(len(list(Path(directory).glob("V*.json"))), 2)

    def test_transport_failure_saves_partial_results_and_consumes_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            transport = FakeTransport(fail_at=1)
            runner = CycleRunner(Path(directory), Orchestrator(openai_agents(transport)))
            with self.assertRaises(ModelError):
                runner.run(handoff(), approved_label="V01-R01", mode="openai")
            record = json.loads((Path(directory) / "V01-R01.json").read_text())
            self.assertEqual(record["status"], "stopped")
            self.assertEqual(list(record["handoff"]["results"]), ["konstruktor"])
            self.assertEqual(len(transport.calls), 2)
            with self.assertRaises(ValueError):
                runner.run(handoff(), approved_label="V01-R01")
            self.assertFalse((Path(directory) / ".lock").exists())

    def test_stop_file_prevents_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "STOP").touch()
            transport = FakeTransport()
            runner = CycleRunner(Path(directory), Orchestrator(openai_agents(transport)))
            with self.assertRaises(ValueError):
                runner.run(handoff(), approved_label="V01-R01")
            self.assertEqual(transport.calls, [])
            record = json.loads((Path(directory) / "V01-R01.json").read_text())
            self.assertEqual(record["status"], "stopped")

    def test_stop_between_agents(self):
        calls = []
        with self.assertRaises(ValueError):
            Orchestrator().run(handoff(), expected_variant="V01", expected_revision="R01",
                               on_step=lambda h: calls.append(h), should_stop=lambda: bool(calls))
        self.assertEqual(len(calls), 1)
        self.assertEqual(list(calls[0].results), ["konstruktor"])

    def test_existing_lock_prevents_parallel_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / ".lock").touch()
            with self.assertRaises(ValueError):
                CycleRunner(Path(directory)).run(handoff(), approved_label="V01-R01")
            self.assertTrue((Path(directory) / ".lock").exists())

    def test_cli_requires_approval_and_runs_without_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            base = [sys.executable, "-m", "src.orchestrator", "examples/V01-R01.json"]
            with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
                missing = subprocess.run(base, cwd=ROOT, capture_output=True, text=True)
                valid = subprocess.run(base + ["--approve-cycle", "V01-R01", "--runs-dir", directory],
                                       cwd=ROOT, capture_output=True, text=True)
                duplicate = subprocess.run(base + ["--approve-cycle", "V01-R01", "--runs-dir", directory],
                                           cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            self.assertEqual(len(json.loads(valid.stdout)["results"]), 4)
            self.assertNotEqual(duplicate.returncode, 0)


class TransportTests(unittest.TestCase):
    def test_missing_configuration_fails_locally(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ValueError):
                OpenAITransport(model="offline-model")
        with self.assertRaises(ValueError):
            OpenAITransport(model="")
        for limit in (0, True, 16001):
            with self.assertRaises(ValueError):
                OpenAITransport(model="offline-model", max_output_tokens=limit)

    def test_sdk_request_contract_and_no_retries_with_mock_http(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:
            self.skipTest("Optional [ai] dependency is not installed")
        requests = []

        def handle(request):
            requests.append(request)
            payload = json.loads(request.content)
            incoming = Handoff(**json.loads(payload["input"]))
            self.assertEqual(payload["text"]["format"]["type"], "json_schema")
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertFalse(payload["store"])
            self.assertEqual(payload["max_output_tokens"], 2500)
            self.assertNotIn("tools", payload)
            data = answer("konstruktor", incoming)
            return httpx.Response(200, json={
                "id": "resp_mock", "object": "response", "created_at": 0,
                "status": "completed", "model": "offline-model",
                "output": [{"type": "message", "id": "msg_mock", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": json.dumps(data), "annotations": []}]}],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}})

        client = OpenAI(api_key="offline-test-placeholder", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test-placeholder"}), \
                patch("openai.OpenAI", return_value=client) as factory:
            transport = OpenAITransport(model="offline-model")
            try:
                data, trace = transport.generate("offline role", handoff())
                self.assertEqual(trace["response_id"], "resp_mock")
                self.assertEqual(trace["input_tokens"], 10)
                self.assertEqual(data["agent"], "konstruktor")
                self.assertEqual(factory.call_args.kwargs["max_retries"], 0)
                self.assertEqual(factory.call_args.kwargs["timeout"], 60.0)
            finally:
                transport.close()
        self.assertEqual(len(requests), 1)

    def test_timeout_refusal_incomplete_and_bad_json_are_sanitized(self):
        try:
            import openai
        except ImportError:
            self.skipTest("Optional [ai] dependency is not installed")
        for response in (SimpleNamespace(status="incomplete", output_text="{}"),
                         SimpleNamespace(status="completed", output_text=""),
                         SimpleNamespace(status="completed", output_text="bad JSON"),
                         TimeoutError("sensitive-provider-error")):
            client = unittest.mock.Mock()
            if isinstance(response, Exception):
                client.responses.create.side_effect = response
            else:
                client.responses.create.return_value = response
            with patch.dict("os.environ", {"OPENAI_API_KEY": "offline-test-placeholder"}), \
                    patch.object(openai, "OpenAI", return_value=client):
                transport = OpenAITransport(model="offline-model")
                with self.assertRaises(ModelError) as caught:
                    transport.generate("offline", handoff())
                self.assertNotIn("sensitive", str(caught.exception))
                self.assertEqual(client.responses.create.call_count, 1)
                transport.close()
