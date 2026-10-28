"""A manually approved, isolated synthetic cloud trial. No API access on preflight."""

import argparse
from dataclasses import asdict, dataclass, field
from importlib.metadata import PackageNotFoundError, version
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

from src.agents.openai_agent import ModelError, OpenAITransport, openai_agents, prompt_parts
from src.models import Handoff
from src.models.contracts import ORDER, validate_inputs
from .cycles import CycleRunner
from .pipeline import Orchestrator

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "V01-R01.json"
MODELS = ("gpt-4.1-mini", "gpt-4.1-nano", "gpt-5.4-mini")
APPROVALS = {"simulated": "ODOBRIM SIMULACIJO V01-R01", "openai": "ODOBRIM AI V01-R01"}


@dataclass(frozen=True)
class TrialConfig:
    mode: str
    model: str
    max_output_tokens: int
    max_prompt_bytes: int
    approval: str
    agent_output_tokens: dict[str, int] = field(default_factory=dict)

    @property
    def agent_limits(self):
        return {name: self.agent_output_tokens.get(name, self.max_output_tokens) for name in ORDER}

    @classmethod
    def from_environment(cls):
        config = cls(os.environ.get("TRIAL_MODE", "simulated"),
                     os.environ.get("TRIAL_MODEL", MODELS[0]),
                     int(os.environ.get("TRIAL_MAX_OUTPUT_TOKENS", "1500")),
                     int(os.environ.get("TRIAL_MAX_PROMPT_BYTES", "48000")),
                     os.environ.get("TRIAL_APPROVAL", ""))
        overrides = {}
        for name in ORDER:
            value = int(os.environ.get(f"TRIAL_MAX_OUTPUT_TOKENS_{name.upper()}", "0"))
            if value != 0:
                overrides[name] = value
        config = cls(config.mode, config.model, config.max_output_tokens,
                     config.max_prompt_bytes, config.approval, overrides)
        config.validate()
        return config

    def validate(self):
        if self.mode not in APPROVALS or self.approval != APPROVALS[self.mode]:
            raise ValueError("Manjka izrecna odobritev izbranega načina in cikla.")
        if self.model not in MODELS:
            raise ValueError("Model ni na seznamu dovoljenih modelov preizkusa.")
        if type(self.max_output_tokens) is not int or not 256 <= self.max_output_tokens <= 4000:
            raise ValueError("Omejitev izhodnih tokenov mora biti med 256 in 4000.")
        if (not isinstance(self.agent_output_tokens, dict) or set(self.agent_output_tokens) - set(ORDER)
                or any(type(v) is not int or not 256 <= v <= 4000 for v in self.agent_output_tokens.values())):
            raise ValueError("Omejitev za vsakega agenta mora biti med 256 in 4000.")
        if self.max_prompt_bytes not in (16000, 32000, 48000):
            raise ValueError("Neveljavna omejitev velikosti poziva.")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            if (os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch"
                    or os.environ.get("GITHUB_REF") != "refs/heads/main"
                    or os.environ.get("GITHUB_RUN_ATTEMPT") != "1"):
                raise ValueError("Dovoljen je samo nov ročni zagon iz main; Re-run ni dovoljen.")


def synthetic_handoff():
    raw = EXAMPLE.read_bytes()
    handoff = Handoff(**json.loads(raw))
    if (handoff.label != "V01-R01" or handoff.inputs.get("data_origin") != "synthetic"
            or handoff.results or handoff.open_questions):
        raise ValueError("Preizkus zahteva začetni sintetični primer V01-R01.")
    source = f"examples/V01-R01.json#sha256:{hashlib.sha256(raw).hexdigest()}"
    handoff.input_sources = {key: source for key in handoff.inputs}
    validate_inputs(handoff)
    return handoff, source


def write_json(path, data, *, exclusive=False):
    with path.open("x" if exclusive else "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, allow_nan=False)


def manifest(config, source):
    try:
        sdk_version = version("openai")
    except PackageNotFoundError:
        sdk_version = None
    return {"configuration": asdict(config), "source": source,
            "commit": os.environ.get("GITHUB_SHA", "local"),
            "actor": os.environ.get("GITHUB_ACTOR", "local"),
            "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
            "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
            "python": platform.python_version(), "openai_sdk": sdk_version,
            "maximum_requests": 4, "agent_output_limits": config.agent_limits,
            "maximum_output_tokens": sum(config.agent_limits.values()),
            "financial_cap_enforced": False}


class BoundedTransport:
    """Bound calls and serialized prompt size before delegating to the real adapter."""

    def __init__(self, transport, max_prompt_bytes):
        self.transport = transport
        self.max_prompt_bytes = max_prompt_bytes
        self.calls = 0
        self.reported_input_tokens = 0
        self.reported_output_tokens = 0
        self.prompt_sizes = []
        self.attempts = []

    def generate(self, instructions, handoff):
        size = sum(len(part.encode("utf-8")) for part in prompt_parts(instructions, handoff).values())
        if self.calls >= 4:
            raise ModelError("Dosežena meja štirih zahtev.", code="request_limit")
        if size > self.max_prompt_bytes:
            raise ModelError("Poziv presega omejitev bajtov.", code="prompt_bytes_limit")
        self.calls += 1  # Failed requests count too; there is no retry.
        self.prompt_sizes.append(size)
        name = ORDER[len(handoff.results)]
        try:
            data, metadata = self.transport.generate(instructions, handoff)
        except ModelError as exc:
            self.record_attempt(name, "failed", exc.metadata, exc.code)
            raise
        self.record_attempt(name, "completed_response", metadata)
        return data, metadata

    def record_attempt(self, name, status, metadata, code=None):
        allowed = ("model", "response_id", "max_output_tokens", "input_tokens", "output_tokens", "reasoning_tokens")
        safe = {k: metadata.get(k) for k in allowed}
        self.attempts.append({"agent": name, "response_status": status, "error_code": code, **safe})
        self.reported_input_tokens += metadata.get("input_tokens") or 0
        self.reported_output_tokens += metadata.get("output_tokens") or 0


def run_trial(config, directory, *, preflight=False):
    config.validate()
    handoff, source = synthetic_handoff()
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / ("preflight.json" if preflight else "manifest.json"),
               manifest(config, source), exclusive=True)
    if preflight:
        return  # Never construct a client or check/print the credential.
    transport = None
    bounded = None
    status = "stopped"
    result = None
    failure_code = None
    try:
        pipeline = Orchestrator()
        if config.mode == "openai":
            extra = {"agent_max_output_tokens": config.agent_output_tokens} if config.agent_output_tokens else {}
            transport = OpenAITransport(model=config.model, max_output_tokens=config.max_output_tokens, **extra)
            bounded = BoundedTransport(transport, config.max_prompt_bytes)
            pipeline = Orchestrator(openai_agents(bounded))
        result = CycleRunner(directory / "runs", pipeline).run(
            handoff, approved_label=handoff.label, mode=config.mode, source=source)
        write_json(directory / "result.json", result.to_dict())
        status = "awaiting_approval"
    except BaseException as exc:
        from src.engineering.calculations import EngineeringError
        failure_code = (exc.code if isinstance(exc, (ModelError, EngineeringError))
                        else "configuration_error" if transport is None and config.mode == "openai"
                        else "interrupted" if isinstance(exc, KeyboardInterrupt)
                        else "validation_or_runtime_error")
        raise
    finally:
        report = {"status": status, "mode": config.mode, "engineering_verified": False,
                  "technical_status": result.results["recenzent"].get("technical_status", "not_evaluated") if result else "not_completed",
                  "failure_code": failure_code,
                  "api_requests_started": bounded.calls if bounded else 0,
                  "reported_input_tokens": bounded.reported_input_tokens if bounded else 0,
                  "reported_output_tokens": bounded.reported_output_tokens if bounded else 0,
                  "prompt_bytes": bounded.prompt_sizes if bounded else [],
                  "agent_output_limits": config.agent_limits,
                  "requests_with_unknown_usage": (bounded.calls - sum(a["input_tokens"] is not None and a["output_tokens"] is not None
                                                                         for a in bounded.attempts)) if bounded else 0,
                  "attempts": bounded.attempts if bounded else [],
                  "financial_cap_enforced": False,
                  "usage_note": "Available provider usage, including incomplete responses when reported; unknown usage is not zero cost. Not a billing statement."}
        write_json(directory / "report.json", report)
        (directory / "summary.md").write_text(
            f"# AI preizkus V01-R01\n\nStanje: `{status}`\n\nNačin: `{config.mode}`\n\n"
            f"Začete API-zahteve: {report['api_requests_started']} od največ 4.\n\n"
            "Celotni in delni rezultati so v artifactu. Finančna meja ni zagotovljena.\n",
            encoding="utf-8")
        if transport is not None:
            transport.close()


def main():
    parser = argparse.ArgumentParser(description="En izoliran sintetični preizkus V01-R01")
    parser.add_argument("--preflight", action="store_true", help="Preveri brez API-ja in ključa")
    parser.add_argument("--output-dir", type=Path, default=Path("cloud-artifacts"))
    args = parser.parse_args()
    try:
        run_trial(TrialConfig.from_environment(), args.output_dir, preflight=args.preflight)
    except (ValueError, TypeError, OSError):
        print("Preizkus ni uspel. Preveri odobritev, main, nov ročni zagon, konfiguracijo in artifact.",
              file=sys.stderr)
        raise SystemExit(1) from None
    print("Preverjanje končano; brez API-klica." if args.preflight else "Cikel končan; glej artifact.")


if __name__ == "__main__":
    main()
