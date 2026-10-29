"""Cloud safeguards exercised offline, including the real adapter boundary."""

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from src.orchestrator.cloud import (APPROVALS, BoundedTransport, TrialConfig,
                                    run_trial, synthetic_handoff)
from test_ai_cycles import FakeTransport, answer

CONFIG = TrialConfig("simulated", "gpt-4.1-mini", 1500, 48000, APPROVALS["simulated"])
LIVE = replace(CONFIG, mode="openai", approval=APPROVALS["openai"])


class CloudRunnerTests(unittest.TestCase):
    def setUp(self):
        # CI itself is push/pull_request; only the manual workflow should enforce this gate.
        self.environment = patch.dict(os.environ, {"GITHUB_ACTIONS": "false"})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def test_simulation_writes_complete_artifact_without_constructing_sdk(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch("src.orchestrator.cloud.OpenAITransport") as factory:
            run_trial(CONFIG, directory)
            factory.assert_not_called()
            result = json.loads((Path(directory) / "result.json").read_text())
            record = json.loads((Path(directory) / "runs/V01-R01.json").read_text())
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(len(result["results"]), 4)
            self.assertEqual(record["status"], "awaiting_approval")
            self.assertEqual(report["api_requests_started"], 0)
            self.assertFalse(report["financial_cap_enforced"])
            self.assertTrue((Path(directory) / "summary.md").exists())

    def test_live_preflight_needs_no_key_and_never_constructs_client(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"OPENAI_API_KEY": ""}), \
                patch("src.orchestrator.cloud.OpenAITransport") as factory:
            run_trial(LIVE, directory, preflight=True)
            factory.assert_not_called()
            data = json.loads((Path(directory) / "preflight.json").read_text())
            self.assertEqual(data["maximum_requests"], 4)
            self.assertEqual(data["maximum_output_tokens"], 6000)
            self.assertFalse(data["financial_cap_enforced"])
            self.assertFalse((Path(directory) / "result.json").exists())

    def test_invalid_configuration_and_unapproved_mode_stop_before_client(self):
        cases = [replace(CONFIG, approval=""), replace(LIVE, approval=CONFIG.approval),
                 replace(CONFIG, model="unreviewed-model"), replace(CONFIG, max_output_tokens=255),
                 replace(CONFIG, max_output_tokens=4001), replace(CONFIG, max_output_tokens=True),
                 replace(CONFIG, max_prompt_bytes=999999), replace(CONFIG, mode="other")]
        with tempfile.TemporaryDirectory() as directory, \
                patch("src.orchestrator.cloud.OpenAITransport") as factory:
            for config in cases:
                with self.subTest(config=config), self.assertRaises(ValueError):
                    run_trial(config, directory)
            factory.assert_not_called()

    def test_action_event_branch_and_attempt_gate(self):
        valid = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                 "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1"}
        with patch.dict(os.environ, valid):
            LIVE.validate()
            for changes in ({"GITHUB_EVENT_NAME": "push"}, {"GITHUB_EVENT_NAME": "pull_request"},
                            {"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_RUN_ATTEMPT": "2"}):
                with self.subTest(changes=changes), patch.dict(os.environ, changes), \
                        self.assertRaises(ValueError):
                    LIVE.validate()

    def test_fixed_input_rejects_public_or_noninitial_data(self):
        handoff, _ = synthetic_handoff()
        cases = [dict(handoff.to_dict(), variant="V02"),
                 dict(handoff.to_dict(), revision="R02"),
                 dict(handoff.to_dict(), inputs={**handoff.inputs, "data_origin": "public"}),
                 dict(handoff.to_dict(), results={"konstruktor": {}})]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            for data in cases:
                path.write_text(json.dumps(data))
                with self.subTest(data=data), patch("src.orchestrator.cloud.EXAMPLE", path), \
                        self.assertRaises(ValueError):
                    synthetic_handoff()

    def test_live_offline_trial_configures_adapter_and_reports_usage(self):
        fake = FakeTransport()
        fake.close = Mock()
        with tempfile.TemporaryDirectory() as directory, \
                patch("src.orchestrator.cloud.OpenAITransport", return_value=fake) as factory, \
                patch.dict(os.environ, {"OPENAI_API_KEY": "secret-marker-must-never-be-exported"}):
            run_trial(LIVE, directory)
            factory.assert_called_once_with(model=LIVE.model, max_output_tokens=1500)
            fake.close.assert_called_once()
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(report["api_requests_started"], 4)
            self.assertEqual(report["reported_input_tokens"], 40)
            self.assertEqual(report["reported_output_tokens"], 80)
            self.assertEqual(len(report["prompt_bytes"]), 4)
            self.assertTrue(all(size <= 48000 for size in report["prompt_bytes"]))
            # Reusing the artifact directory cannot silently repeat a paid cycle.
            with self.assertRaises(FileExistsError):
                run_trial(LIVE, directory)
            self.assertEqual(factory.call_count, 1)
            for path in Path(directory).rglob("*"):
                if path.is_file():
                    if path.suffix == ".zip":
                        from zipfile import ZipFile
                        with ZipFile(path) as archive:
                            for name in archive.namelist():
                                self.assertNotIn(b"secret-marker-must-never-be-exported", archive.read(name))
                    else:
                        self.assertNotIn("secret-marker-must-never-be-exported", path.read_text())

    def test_budget_blocks_oversized_prompts_and_fifth_request_before_transport(self):
        value, _ = synthetic_handoff()
        underlying = Mock()
        underlying.generate.return_value = ({}, {"input_tokens": 1, "output_tokens": 2})
        bounded = BoundedTransport(underlying, 48000)
        for _ in range(4):
            bounded.generate("instructions", value)
        with self.assertRaises(ValueError):
            bounded.generate("instructions", value)
        self.assertEqual(underlying.generate.call_count, 4)
        other = BoundedTransport(underlying, 16000)
        with self.assertRaises(ValueError):
            other.generate("x" * 16001, value)
        self.assertEqual(other.calls, 0)
        self.assertEqual(underlying.generate.call_count, 4)

    def test_gpt_54_mini_workflow_input_reaches_sdk_for_all_four_agents_offline(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:
            self.skipTest("Optional [ai] dependency is not installed")
        from src.models import Handoff
        from src.models.contracts import ORDER, RESPONSE_SCHEMA

        requests = []

        def handle(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "gpt-5.4-mini")
            self.assertEqual(payload["max_output_tokens"], 1500)
            from src.engineering.contracts import response_schema
            self.assertEqual(payload["text"]["format"]["schema"], response_schema(Handoff(**json.loads(payload["input"]))))
            self.assertTrue(payload["text"]["format"]["strict"])
            self.assertFalse(payload["store"])
            incoming = Handoff(**json.loads(payload["input"]))
            self.assertEqual(list(incoming.results), list(ORDER[:len(requests)]))
            data = answer(ORDER[len(requests)], incoming)
            requests.append(payload)
            return httpx.Response(200, json={
                "id": f"resp_{len(requests)}", "object": "response", "created_at": 0,
                "status": "completed", "model": "gpt-5.4-mini",
                "output": [{"type": "message", "id": "msg_mock", "role": "assistant",
                            "status": "completed", "content": [{"type": "output_text",
                            "text": json.dumps(data), "annotations": []}]}],
                "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}})

        client = OpenAI(api_key="offline-test-placeholder", max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(handle)))
        environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                       "GITHUB_REF": "refs/heads/main", "GITHUB_RUN_ATTEMPT": "1",
                       "TRIAL_MODE": "openai", "TRIAL_MODEL": "gpt-5.4-mini",
                       "TRIAL_MAX_OUTPUT_TOKENS": "1500", "TRIAL_MAX_PROMPT_BYTES": "48000",
                       "TRIAL_APPROVAL": APPROVALS["openai"],
                       "OPENAI_API_KEY": "offline-test-placeholder"}
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, environment), \
                patch("openai.OpenAI", return_value=client):
            config = TrialConfig.from_environment()
            run_trial(config, directory)
            report = json.loads((Path(directory) / "report.json").read_text())
            manifest = json.loads((Path(directory) / "manifest.json").read_text())
            self.assertEqual(report["status"], "awaiting_approval")
            self.assertEqual(report["api_requests_started"], 4)
            self.assertEqual(manifest["configuration"]["model"], "gpt-5.4-mini")
        self.assertEqual(len(requests), 4)

    def test_missing_secret_is_a_local_failure_with_artifact(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(ValueError):
                run_trial(LIVE, directory)
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(report["status"], "stopped")
            self.assertEqual(report["api_requests_started"], 0)

    def test_provider_failure_preserves_partial_results_without_raw_error(self):
        fake = FakeTransport(fail_at=1)
        fake.close = Mock()
        with tempfile.TemporaryDirectory() as directory, \
                patch("src.orchestrator.cloud.OpenAITransport", return_value=fake):
            with self.assertRaises(ValueError):
                run_trial(LIVE, directory)
            record = json.loads((Path(directory) / "runs/V01-R01.json").read_text())
            report = json.loads((Path(directory) / "report.json").read_text())
            self.assertEqual(list(record["handoff"]["results"]), ["konstruktor"])
            self.assertEqual(report["status"], "stopped")
            self.assertEqual(report["api_requests_started"], 2)
            self.assertFalse((Path(directory) / "result.json").exists())
            for path in Path(directory).rglob("*"):
                if path.is_file():
                    self.assertNotIn("Umetna napaka", path.read_text())
            fake.close.assert_called_once()
