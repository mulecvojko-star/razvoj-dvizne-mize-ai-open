"""Deterministični učni odgovori, brez omrežja ali AI-modelov."""

from dataclasses import dataclass

from src.models.contracts import ORDER, digest

from src.models import Handoff



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
                      "findings": [{"id": "F01", "severity": "major", "status": "open",
                                    "description": "Geometrija in izračuni niso preverjeni.",
                                    "required_correction": "Dopolni geometrijo in strokovno preveri izračune."}],
                      "reviewed_agents": list(handoff.results),
                      "next_revision": f"R{int(handoff.revision[1:]) + 1:02d}",
                      "summary": "Učni cikel zaključen; odprta vprašanja zahtevajo novo revizijo."}
            questions = []
        return handoff.with_result(self.name, common | result, questions)


def default_agents() -> tuple[SimulatedAgent, ...]:
    return tuple(SimulatedAgent(name) for name in ORDER)
