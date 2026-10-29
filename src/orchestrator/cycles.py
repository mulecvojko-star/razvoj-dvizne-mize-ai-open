"""Explicit, single-use cycle approval with a persistent local revision ledger."""

from datetime import datetime, timezone
import json
from pathlib import Path

from src.models import Handoff
from src.models.contracts import digest, validate_inputs
from .pipeline import Orchestrator


def now():
    return datetime.now(timezone.utc).isoformat()


class CycleRunner:
    def __init__(self, directory: Path, orchestrator: Orchestrator | None = None):
        self.directory = Path(directory)
        self.orchestrator = orchestrator or Orchestrator()

    def run(self, handoff: Handoff, *, approved_label: str | None = None,
            mode: str = "simulated", source: str = "programmatic") -> Handoff:
        handoff.validate()
        validate_inputs(handoff)
        if approved_label != handoff.label:
            raise ValueError("Vsak cikel zahteva izrecno odobritev točne oznake variante in revizije.")
        if handoff.results:
            raise ValueError("Nov cikel zahteva prazne rezultate.")
        self.directory.mkdir(parents=True, exist_ok=True)
        lock = self.directory / ".lock"
        try:
            fd = lock.open("x")
        except FileExistsError:
            raise ValueError("Drug cikel teče ali je ostal zaklep po prekinitvi; preveri dnevnik.") from None
        try:
            with fd:
                fd.write(f"{handoff.label}\n")
            records = []
            for path in self.directory.glob(f"{handoff.variant}-R*.json"):
                records.append(json.loads(path.read_text(encoding="utf-8")))
            previous = max(records, key=lambda r: int(r["revision"][1:])) if records else None
            expected = int(previous["revision"][1:]) + 1 if previous else 1
            if int(handoff.revision[1:]) != expected:
                raise ValueError(f"Pričakovana naslednja revizija: R{expected:02d}.")
            record = {"variant": handoff.variant, "revision": handoff.revision,
                      "approved_label": approved_label, "approved_at": now(), "mode": mode,
                      "source": source, "input_sha256": digest(handoff.inputs),
                      "previous_record_sha256": digest(previous) if previous else None,
                      "status": "running", "handoff": handoff.to_dict()}
            # Exclusive creation prevents overwriting an existing revision or its approval.
            path = self.directory / f"{handoff.label}.json"
            with path.open("x", encoding="utf-8") as file:
                json.dump(record, file, ensure_ascii=False, indent=2, allow_nan=False)

            def save():
                temporary = path.with_suffix(".tmp")
                temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2,
                                                 allow_nan=False), encoding="utf-8")
                temporary.replace(path)

            def checkpoint(current):
                record["handoff"] = current.to_dict()
                save()

            try:
                result = self.orchestrator.run(
                    handoff, expected_variant=handoff.variant, expected_revision=handoff.revision,
                    on_step=checkpoint, should_stop=lambda: (self.directory / "STOP").exists())
                record["status"] = "awaiting_approval"
                record["review_decision"] = result.results["recenzent"]["decision"]
                record["engineering_verified"] = False
                record["technical_status"] = result.results["recenzent"].get("technical_status", "not_evaluated")
                record["finished_at"] = now()
                save()
            except BaseException as exc:
                record["status"] = "stopped"
                from src.engineering.calculations import EngineeringError
                from src.agents.openai_agent import ModelError
                if isinstance(exc, ModelError):
                    record["error"] = {"code": exc.code}
                if isinstance(exc, EngineeringError):
                    record["error"] = {"code": exc.code, "description": str(exc), "details": exc.details}
                record["finished_at"] = now()
                # Persist partial results, never raw exceptions or credentials.
                save()
                raise
            # Document rendering never re-runs agents. A document failure preserves
            # the completed handoff and is repairable with the offline JSON command.
            from src.reporting.package import build_package
            from src.reporting.source import PackageError
            try:
                import os
                manifest = {"run_id": os.environ.get("GITHUB_RUN_ID", "local"),
                            "commit": os.environ.get("GITHUB_SHA", "local"),
                            "actor": os.environ.get("GITHUB_ACTOR", "local"),
                            "configuration": {"mode": mode,
                                              "model": result.results["konstruktor"].get("trace", {}).get("model", "simulated")}}
                archive = build_package(record, self.directory / "packages",
                                        metadata={"input_file": source, "manifest": manifest})
            except Exception:
                record["development_package"] = {"status": "failed", "code": "document_generation_failed"}
                save()
                raise PackageError("Cikel je zaključen, izdelava paketa pa ni uspela; uporabi shranjeni JSON brez ponovnega API-zagona.") from None
            record["development_package"] = {"status": "created", "path": str(archive.relative_to(self.directory))}
            save()
            return result
        finally:
            lock.unlink()
