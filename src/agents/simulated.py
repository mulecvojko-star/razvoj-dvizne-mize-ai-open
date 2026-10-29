"""Deterministični učni odgovori, brez omrežja ali AI-modelov."""

from dataclasses import dataclass

from src.models.contracts import ORDER, digest

from src.models import Handoff
from src.engineering.contracts import reference, claims



@dataclass(frozen=True)
class SimulatedAgent:
    name: str

    def run(self, handoff: Handoff) -> Handoff:
        if self.name not in ORDER:
            raise ValueError(f"Neznan agent: {self.name}")
        index = ORDER.index(self.name)
        if tuple(handoff.results) != ORDER[:index]:
            raise ValueError(f"Manjkajo ali so napačno razvrščene predaje za {self.name}.")
        common = {"simulated": True, "handoff_label": handoff.label,
                  "assumptions": ["Sintetičen učni primer; izračuni niso preverjeni."],
                  "trace": {"input_sha256": digest(handoff.inputs),
                            "handoff_sha256": digest(handoff.to_dict()), "mode": "simulated"}}
        if self.name == "konstruktor":
            result = {"concept": "Učna škarjasta dvižna miza",
                      "requirements": handoff.inputs,
                      "engineering_verified": False}
            questions = ["Katere geometrijske omejitve veljajo za dejansko izvedbo?"]
        elif self.name == "hidravlik":
            result = {"source_concept": handoff.results["konstruktor"]["concept"],
                      "analysis": "Simulirana hidravlična analiza; dimenzioniranje še ni izvedeno.",
                      "engineering_verified": False}
            questions = ["Kakšna bosta geometrija vpetja in zahtevani čas dviga?"]
        elif self.name == "ekonomist":
            result = {"currency": "EUR", "synthetic_total": 1200,
                      "basis": "Izmišljena učna ocena, brez ponudb dobaviteljev.",
                      "hydraulics_verified": handoff.results["hidravlik"]["engineering_verified"]}
            questions = ["Katere stroškovne postavke naj zajame naslednja revizija?"]
        else:
            result = {"decision": "changes_required",
                      "findings": [{"id": "F01", "target_agent": "konstruktor", "severity": "major", "status": "open",
                                    "description": "Geometrija in izračuni niso preverjeni.",
                                    "required_correction": "Dopolni geometrijo in strokovno preveri izračune."}],
                      "reviewed_agents": list(handoff.results),
                      "next_revision": f"R{int(handoff.revision[1:]) + 1:02d}",
                      "summary": "Učni cikel zaključen; odprta vprašanja zahtevajo novo revizijo."}
            questions = []
        engineering = reference(handoff, self.name)
        result["engineering_verified"] = False
        result["technical_status"] = "not_evaluated" if engineering is None else engineering["status"]
        if engineering is not None:
            result["engineering"] = engineering
            result["calculations"] = claims(self.name, engineering)
            result["cost_items"] = engineering["cost_items"] if self.name == "ekonomist" else []
            if self.name == "konstruktor":
                common["assumptions"] = engineering["assumptions"]
            if self.name == "ekonomist":
                result["synthetic_total"] = engineering["synthetic_subtotal_EUR"]
                result["basis"] = engineering["basis"]
            if self.name == "recenzent":
                result["decision"] = engineering["status"]
                result["findings"] = engineering["findings"]
        if handoff.revision_context:
            from src.orchestrator.revision_policy import revision_work
            result["revision_work"] = revision_work(self.name, handoff.revision_context)
            if self.name == "recenzent" and handoff.revision == "R02":
                result["next_revision"] = None
                result["summary"] = "R02 je zaključena; dosežena je meja dveh simuliranih revizij. Naloge ostajajo odprte brez tehnične odobritve."
            questions = [q for q in questions if q not in handoff.open_questions]
        return handoff.with_result(self.name, common | result, questions)


def default_agents() -> tuple[SimulatedAgent, ...]:
    return tuple(SimulatedAgent(name) for name in ORDER)
