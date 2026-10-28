"""Local byte/token estimates. Never creates a client or calls a model/token API."""

import argparse
import math
import json
from pathlib import Path
from zipfile import ZipFile

from src.agents.openai_agent import openai_agents, prompt_parts
from src.engineering.contracts import claims, reference
from src.models.contracts import ORDER
from .cloud import synthetic_handoff, write_json
from .pipeline import Orchestrator


def sample_response(name, handoff, historical=None):
    data = reference(handoff, name)
    result = {"variant": handoff.variant, "revision": handoff.revision, "agent": name,
              "summary": "Preliminarni sintetični račun; tehnična potrditev ni opravljena.",
              "assumptions": data.get("assumptions", data.get("limitations", [])),
              "outputs": [{"name": "status", "value": "preliminary", "unit": "n/a",
                           "basis": "Deterministična sintetična referenca, brez potrditve varnosti."}],
              "open_questions": ["Potrebni so nadaljnji strokovni pregledi in dopolnitve."],
              "calculations": claims(name, data),
              "cost_items": data["cost_items"] if name == "ekonomist" else [],
              "decision": data["status"] if name == "recenzent" else "not_applicable",
              "findings": data["findings"] if name == "recenzent" else []}
    if historical is not None:
        # Reuse only old prose. All new required numerical/price/review fields are local.
        for key in ("summary", "assumptions", "outputs", "open_questions"):
            result[key] = historical[name][key]
    return result


def estimated_tokens(text):
    # A planning range, not tokenizer output or a guaranteed bound. Older observed
    # JSON/Slovenian prompts in this repository average about 3.3 UTF-8 bytes/token.
    size = len(text.encode("utf-8"))
    return [math.floor(size / 4), math.ceil(size / 2.5)]


def audit_cycle(historical=None):
    rows = []

    class AuditTransport:
        def generate(self, instructions, handoff):
            name = ORDER[len(handoff.results)]
            response = sample_response(name, handoff, historical)
            response_json = json.dumps(response, ensure_ascii=False)
            parts = prompt_parts(instructions, handoff)
            rows.append({"agent": name,
                         "prompt_bytes": sum(len(p.encode("utf-8")) for p in parts.values()),
                         "input_token_estimate_range": [sum(estimated_tokens(p)[i] for p in parts.values()) for i in (0, 1)],
                         "output_text_token_estimate_range": estimated_tokens(response_json),
                         "parts": {k: {"bytes": len(v.encode("utf-8")), "token_estimate_range": estimated_tokens(v)}
                                   for k, v in parts.items()}})
            return response, {"model": "offline-audit", "response_id": "offline",
                              "input_tokens": None, "output_tokens": None}

    handoff, _ = synthetic_handoff()
    Orchestrator(openai_agents(AuditTransport())).run(
        handoff, expected_variant=handoff.variant, expected_revision=handoff.revision)
    return {"agents": rows, "input_token_estimate_range": [sum(r["input_token_estimate_range"][i] for r in rows) for i in (0, 1)],
            "output_text_token_estimate_range": [sum(r["output_text_token_estimate_range"][i] for r in rows) for i in (0, 1)],
            "maximum_prompt_bytes": max(r["prompt_bytes"] for r in rows)}


def main():
    parser = argparse.ArgumentParser(description="Lokalna ocena tokenov brez API-ja")
    parser.add_argument("--historical-artifact", type=Path, help="Lokalni ZIP starega sintetičnega AI-preizkusa")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = {"kind": "offline_estimate_not_billing", "method": "UTF-8 bytes / 4 to bytes / 2.5",
              "limitations": ["Hevrističen planski razpon, ne tokenizer in ne jamstvo zgornje meje.",
                              "Ovojnica API-ja, reasoning in nevidni izhodni tokeni niso vključeni.",
                              "Predaje vsebujejo sintetične odgovore; dejanska poraba in velikost lahko odstopata."],
              "compact_synthetic": audit_cycle()}
    if args.historical_artifact:
        with ZipFile(args.historical_artifact) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            result = json.loads(archive.read("result.json"))
            if result["inputs"].get("data_origin") != "synthetic":
                parser.exit(1, "Dovoljen je samo sintetičen zgodovinski primer.\n")
            report["historical_observed"] = {
                "run_id": manifest["run_id"], "commit": manifest["commit"],
                "configuration": manifest["configuration"],
                "agents": {name: {k: result["results"][name]["trace"].get(k)
                                  for k in ("model", "input_tokens", "output_tokens", "reasoning_tokens")}
                           for name in ORDER}}
            report["historical_prose_with_current_contract"] = audit_cycle(result["results"])
    write_json(args.output, report)
    print("Lokalna analiza shranjena; brez API-klica.")


if __name__ == "__main__":
    main()
