import argparse
import json
from pathlib import Path

from src.models import Handoff
from src.orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser(description="Simuliran cikel štirih agentov")
    parser.add_argument("example", type=Path, help="Pot do vhodne predaje JSON")
    args = parser.parse_args()
    handoff = Handoff(**json.loads(args.example.read_text(encoding="utf-8")))
    result = Orchestrator().run(handoff, expected_variant=handoff.variant,
                                expected_revision=handoff.revision)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
