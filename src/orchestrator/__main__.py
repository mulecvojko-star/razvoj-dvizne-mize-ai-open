"""One explicitly approved cycle; simulated by default."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from src.models import Handoff
from .cycles import CycleRunner
from .pipeline import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="En odobren cikel štirih agentov")
    parser.add_argument("example", type=Path, help="Vhodna predaja JSON")
    parser.add_argument("--mode", choices=("simulated", "openai"), default="simulated")
    parser.add_argument("--approve-cycle", required=True, metavar="V01-R01",
                        help="Izrecno odobri samo navedeni cikel; v AI-načinu tudi API-stroške")
    parser.add_argument("--runs-dir", type=Path, default=Path(".runs"))
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", ""))
    parser.add_argument("--max-output-tokens", type=int, default=2500)
    args = parser.parse_args()
    transport = None
    try:
        raw = args.example.read_bytes()
        handoff = Handoff(**json.loads(raw))
        source = f"{args.example.name}#sha256:{hashlib.sha256(raw).hexdigest()}"
        # Legacy examples can omit per-field sources: attach exact file content hash locally.
        if not handoff.input_sources:
            handoff.input_sources = {key: source for key in handoff.inputs}
        pipeline = Orchestrator()
        if args.mode == "openai":
            from src.agents.openai_agent import OpenAITransport, openai_agents
            transport = OpenAITransport(model=args.model, max_output_tokens=args.max_output_tokens)
            pipeline = Orchestrator(openai_agents(transport))
        result = CycleRunner(args.runs_dir, pipeline).run(
            handoff, approved_label=args.approve_cycle, mode=args.mode,
            source=source)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, TypeError, OSError):
        # Do not echo arbitrary input, provider exception text or secrets.
        parser.exit(1, "Cikel ni uspel. Preveri odobritev, vhod, konfiguracijo in lokalni dnevnik.\n")
    finally:
        if transport is not None:
            transport.close()


if __name__ == "__main__":
    main()
