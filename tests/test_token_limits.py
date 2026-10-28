"""Per-agent limits and failure accounting, always offline."""

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.agents.openai_agent import ModelError, OpenAITransport
from src.models import Handoff
from src.models.contracts import ORDER
from src.orchestrator.cloud import APPROVALS, TrialConfig, manifest, run_trial
from src.orchestrator.token_audit import audit_cycle, sample_response

LIMITS = dict(zip(ORDER, (2500, 2500, 3000, 3500)))
CONFIG = TrialConfig("openai", "gpt-5.4-mini", 1500, 48000, APPROVALS["openai"], LIMITS)


class LimitConfigurationTests(unittest.TestCase):
    def test_manual_inputs_override_shared_limit_and_manifest_sums_actual_limits(self):
        env = {"GITHUB_ACTIONS": "false", "TRIAL_MODE": "openai", "TRIAL_MODEL": "gpt-5.4-mini",
               "TRIAL_APPROVAL": APPROVALS["openai"], "TRIAL_MAX_OUTPUT_TOKENS": "1500",
               **{f"TRIAL_MAX_OUTPUT_TOKENS_{name.upper()}": str(value) for name, value in LIMITS.items()}}
        with patch.dict(os.environ, env):
            config = TrialConfig.from_environment()
            self.assertEqual(config.agent_limits, LIMITS)
            self.assertEqual(manifest(config, "synthetic")["maximum_output_tokens"], 11500)
        with patch.dict(os.environ, {**env, "TRIAL_MAX_OUTPUT_TOKENS_HIDRAVLIK": "0"}):
            self.assertEqual(TrialConfig.from_environment().agent_limits["hidravlik"], 1500)

    def test_invalid_agent_limits_fail_without_client(self):
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "false"}), \
                patch("src.orchestrator.cloud.OpenAITransport") as client:
            for mapping in ({"wrong": 2000}, {"konstruktor": True}, {"ekonomist": 4001},
                            {"recenzent": 255}, {"hidravlik": -1}, []):
                with tempfile.TemporaryDirectory() as directory, self.subTest(mapping=mapping), self.assertRaises(ValueError):
                    run_trial(replace(CONFIG, agent_output_tokens=mapping), directory)
            client.assert_not_called()
        for mapping in ([], False, {"wrong": 2000}, {"konstruktor": True}):
            with self.subTest(mapping=mapping), self.assertRaises(ValueError):
                OpenAITransport(model="gpt-5.4-mini", agent_max_output_tokens=mapping)

    def test_local_audit_measures_all_roles_without_any_client(self):
        with patch("src.orchestrator.cloud.OpenAITransport", side_effect=AssertionError("No API")):
            report = audit_cycle()
        self.assertEqual([r["agent"] for r in report["agents"]], list(ORDER))
        self.assertTrue(all(0 < r["prompt_bytes"] < 48000 for r in report["agents"]))
        self.assertTrue(all(r["input_token_estimate_range"][0] <= r["input_token_estimate_range"][1]
                            for r in report["agents"]))


class OfflineSDKFailureTests(unittest.TestCase):
    def setUp(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:
            self.skipTest("Optional [ai] dependency is not installed")
        self.httpx = httpx
        self.OpenAI = OpenAI

    def invoke(self, handle):
        client = self.OpenAI(api_key="offline-placeholder", max_retries=0,
                             http_client=self.httpx.Client(transport=self.httpx.MockTransport(handle)))
        error = None
        with tempfile.TemporaryDirectory() as directory, \
                patch.dict(os.environ, {"GITHUB_ACTIONS": "false", "OPENAI_API_KEY": "offline-placeholder"}), \
                patch("openai.OpenAI", return_value=client):
            try:
                run_trial(CONFIG, directory)
            except ValueError as exc:
                error = exc
            files = {str(p.relative_to(directory)): json.loads(p.read_text())
                     for p in Path(directory).rglob("*.json")}
        return error, files

    def response(self, request, change=None, *, usage=True):
        payload = json.loads(request.content)
        incoming = Handoff(**json.loads(payload["input"]))
        name = ORDER[len(incoming.results)]
        self.assertEqual(payload["max_output_tokens"], LIMITS[name])
        data = sample_response(name, incoming)
        if change:
            change(data)
        body = {"id": f"resp_{name}", "object": "response", "created_at": 0,
                "status": "completed", "model": "gpt-5.4-mini",
                "output": [{"type": "message", "id": "msg", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "text": json.dumps(data), "annotations": []}]}]}
        if usage:
            body["usage"] = {"input_tokens": 100, "output_tokens": 200, "total_tokens": 300,
                             "output_tokens_details": {"reasoning_tokens": 20}}
        return self.httpx.Response(200, json=body)

    def assert_stopped(self, files):
        self.assertEqual(files["report.json"]["status"], "stopped")
        self.assertEqual(files["report.json"]["technical_status"], "not_completed")
        self.assertFalse(files["report.json"]["engineering_verified"])
        self.assertNotIn("result.json", files)

    def test_four_requests_use_four_distinct_limits_and_record_usage(self):
        calls = []
        def handle(request):
            calls.append(request)
            return self.response(request)
        error, files = self.invoke(handle)
        self.assertIsNone(error)
        self.assertEqual(len(calls), 4)
        self.assertEqual(files["manifest.json"]["maximum_output_tokens"], 11500)
        self.assertEqual(files["report.json"]["agent_output_limits"], LIMITS)
        self.assertEqual([a["max_output_tokens"] for a in files["report.json"]["attempts"]], list(LIMITS.values()))
        self.assertEqual([a["reasoning_tokens"] for a in files["report.json"]["attempts"]], [20]*4)
        self.assertEqual(files["report.json"]["technical_status"], "changes_required")

    def test_incomplete_token_exhaustion_keeps_usage_and_stops_without_retry(self):
        calls = []
        def handle(request):
            calls.append(request)
            return self.httpx.Response(200, json={
                "id": "resp_incomplete", "object": "response", "created_at": 0,
                "status": "incomplete", "model": "gpt-5.4-mini", "output": [],
                "incomplete_details": {"reason": "max_output_tokens"},
                "usage": {"input_tokens": 4000, "output_tokens": 2500, "total_tokens": 6500,
                          "output_tokens_details": {"reasoning_tokens": 600}}})
        error, files = self.invoke(handle)
        self.assertIsInstance(error, ModelError)
        self.assert_stopped(files)
        self.assertEqual(len(calls), 1)
        self.assertEqual(files["report.json"]["failure_code"], "max_output_tokens")
        self.assertEqual(files["report.json"]["reported_output_tokens"], 2500)
        self.assertEqual(files["report.json"]["attempts"][0]["reasoning_tokens"], 600)
        self.assertEqual(files["runs/V01-R01.json"]["error"]["code"], "max_output_tokens")

    def test_http_errors_and_timeout_never_retry_or_store_raw_provider_text(self):
        for status, code in ((429, "api_rate_limit"), (401, "api_authentication"),
                             (400, "api_bad_request"), (500, "api_error"), (None, "api_timeout")):
            calls = []
            def handle(request):
                calls.append(request)
                if status is None:
                    raise self.httpx.ReadTimeout("private-provider-message", request=request)
                return self.httpx.Response(status, json={"error": {"message": "private-provider-message", "type": "test"}})
            with self.subTest(status=status):
                error, files = self.invoke(handle)
                self.assert_stopped(files)
                self.assertEqual(len(calls), 1)
                self.assertEqual(files["report.json"]["failure_code"], code)
                self.assertEqual(files["report.json"]["requests_with_unknown_usage"], 1)
                self.assertNotIn("private-provider-message", json.dumps(files))

    def test_invalid_json_refusal_and_other_incomplete_response_are_not_success(self):
        for kind, code in (("json", "invalid_json"), ("refusal", "empty_or_refused"), ("incomplete", "incomplete_response")):
            calls = []
            def handle(request):
                calls.append(request)
                response = self.response(request)
                body = response.json()
                if kind == "json":
                    body["output"][0]["content"][0]["text"] = "{bad JSON"
                elif kind == "refusal":
                    body["output"][0]["content"] = [{"type": "refusal", "refusal": "private-provider-message"}]
                else:
                    body["status"] = "incomplete"
                    body["incomplete_details"] = {"reason": "content_filter"}
                return self.httpx.Response(200, json=body)
            with self.subTest(kind=kind):
                error, files = self.invoke(handle)
                self.assert_stopped(files)
                self.assertEqual(files["report.json"]["failure_code"], code)
                self.assertEqual(files["report.json"]["reported_input_tokens"], 100)
                self.assertEqual(len(calls), 1)

    def test_math_or_schema_error_halts_handoff_after_last_good_agent(self):
        for change in (lambda d: d["calculations"].clear(),
                       lambda d: d["calculations"][0].update(unit="wrong"),
                       lambda d: d.pop("summary")):
            calls = []
            def handle(request):
                calls.append(request)
                return self.response(request, change if len(calls) == 2 else None)
            with self.subTest(change=change):
                error, files = self.invoke(handle)
                self.assert_stopped(files)
                self.assertEqual(len(calls), 2)
                self.assertEqual(list(files["runs/V01-R01.json"]["handoff"]["results"]), ["konstruktor"])
                self.assertEqual(files["report.json"]["reported_output_tokens"], 400)

    def test_prompt_limit_can_stop_later_agent_even_with_large_output_budget(self):
        calls = []
        def handle(request):
            calls.append(request)
            return self.response(request, lambda d: d.update(summary="x" * 48001))
        error, files = self.invoke(handle)
        self.assert_stopped(files)
        self.assertEqual(len(calls), 1)
        self.assertEqual(files["report.json"]["failure_code"], "prompt_bytes_limit")

    def test_absent_usage_is_explicitly_unknown(self):
        error, files = self.invoke(lambda request: self.response(request, usage=False))
        self.assertIsNone(error)
        self.assertEqual(files["report.json"]["requests_with_unknown_usage"], 4)
        self.assertTrue(all(a["input_tokens"] is None for a in files["report.json"]["attempts"]))
