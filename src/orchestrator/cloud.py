"""A manually approved, isolated synthetic cloud trial. No API access on preflight."""

import argparse
from dataclasses import asdict, dataclass
from importlib.metadata import PackageNotFoundError, version
import hashlib
import json
import os
from pathlib import Path
import platform
import sys

from src.agents.openai_agent import OpenAITransport, openai_agents
from src.models import Handoff
from src.models.contracts import RESPONSE_SCHEMA, validate_inputs
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

    @classmethod
    def from_environment(cls):
        config = cls(os.environ.get("TRIAL_MODE", "simulated"),
                     os.environ.get("TRIAL_MODEL", MODELS[0]),
                     int(os.environ.get("TRIAL_MAX_OUTPUT_TOKENS", "1500")),
                     int(os.environ.get("TRIAL_MAX_PROMPT_BYTES", "48000")),
                     os.environ.get("TRIAL_APPROVAL", ""))
        config.validate()
        return config

    def validate(self):
        if self.mode not in APPROVALS or self.approval != APPROVALS[self.mode]:
            raise ValueError("Manjka izrecna odobritev izbranega načina in cikla.")
        if self.model not in MODELS:
            raise ValueError("Model ni na seznamu dovoljenih modelov preizkusa.")
        if type(self.max_output_tokens) is not int or not 256 <= self.max_output_tokens <= 4000:
            raise ValueError("Omejitev izhodnih tokenov mora biti med 256 in 4000.")
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
            "maximum_requests": 4, "maximum_output_tokens": 4 * config.max_output_tokens,
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

    def generate(self, instructions, handoff):
        size = (len(instructions.encode("utf-8"))
                + len(json.dumps(handoff.to_dict(), ensure_ascii=False).encode("utf-8"))
                + len(json.dumps(RESPONSE_SCHEMA, ensure_ascii=False).encode("utf-8")))
        if self.calls >= 4 or size > self.max_prompt_bytes:
            raise ValueError("Dosežena omejitev zahtev ali velikosti poziva; cikel je ustavljen.")
        self.calls += 1  # Failed requests count too; there is no retry.
        self.prompt_sizes.append(size)
        data, metadata = self.transport.generate(instructions, handoff)
        self.reported_input_tokens += metadata.get("input_tokens") or 0
        self.reported_output_tokens += metadata.get("output_tokens") or 0
        return data, metadata


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
    try:
        pipeline = Orchestrator()
        if config.mode == "openai":
            transport = OpenAITransport(model=config.model, max_output_tokens=config.max_output_tokens)
            bounded = BoundedTransport(transport, config.max_prompt_bytes)
            pipeline = Orchestrator(openai_agents(bounded))
        result = CycleRunner(directory / "runs", pipeline).run(
            handoff, approved_label=handoff.label, mode=config.mode, source=source)
        write_json(directory / "result.json", result.to_dict())
        status = "awaiting_approval"
    finally:
        report = {"status": status, "mode": config.mode, "engineering_verified": False,
                  "technical_status": result.results["recenzent"].get("technical_status", "not_evaluated") if result else "not_completed",
                  "api_requests_started": bounded.calls if bounded else 0,
                  "reported_input_tokens": bounded.reported_input_tokens if bounded else 0,
                  "reported_output_tokens": bounded.reported_output_tokens if bounded else 0,
                  "prompt_bytes": bounded.prompt_sizes if bounded else [],
                  "financial_cap_enforced": False,
                  "usage_note": "Reported successful responses only; not a billing statement."}
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
