from copy import deepcopy
import json
from pathlib import Path
import unittest

from src.agents import SimulatedAgent, default_agents
from src.agents.simulated import ORDER
from src.models import Handoff
from src.orchestrator import Orchestrator


class AlteredAgent:
    def __init__(self, name, change):
        self.name = name
        self.change = change

    def run(self, handoff):
        output = SimulatedAgent(self.name).run(handoff)
        self.change(output)
        return output


class PipelineTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "V01-R01.json"
        self.handoff = Handoff(**json.loads(path.read_text(encoding="utf-8")))

    def run_cycle(self, pipeline=None, handoff=None, revision="R01"):
        return (pipeline or Orchestrator()).run(
            handoff or self.handoff, expected_variant="V01", expected_revision=revision
        )

    def test_full_cycle_order_and_data_flow(self):
        original = deepcopy(self.handoff)
        result = self.run_cycle()
        self.assertEqual(tuple(result.results), ORDER)
        self.assertEqual(result.results["recenzent"]["reviewed_agents"], list(ORDER[:3]))
        self.assertEqual(result.results["hidravlik"]["source_concept"],
                         result.results["konstruktor"]["concept"])
        self.assertEqual(result.label, "V01-R01")
        self.assertEqual(result.results["recenzent"]["next_revision"], "R02")
        self.assertEqual(len(result.open_questions), 3)
        self.assertTrue(all(value["simulated"] for value in result.results.values()))
        self.assertEqual(self.handoff, original)
        self.assertEqual(json.loads(json.dumps(result.to_dict())), result.to_dict())

    def test_wrong_missing_or_duplicate_agent_order_rejected(self):
        agents = default_agents()
        for sequence in (agents[::-1], agents[:-1], (), (agents[0],) * 4):
            with self.subTest(sequence=sequence), self.assertRaises(ValueError):
                Orchestrator(sequence)

    def test_stale_revision_or_wrong_variant_rejected(self):
        for variant, revision in (("V02", "R01"), ("V01", "R02")):
            with self.subTest(variant=variant, revision=revision), self.assertRaises(ValueError):
                self.run_cycle(handoff=Handoff(variant, revision, {}))

    def test_invalid_identity_rejected(self):
        for variant, revision in (("V00", "R01"), ("V01", "R00"),
                                  ("V1", "R01"), ("V01", "R-1")):
            with self.subTest(variant=variant, revision=revision), self.assertRaises(ValueError):
                Handoff(variant, revision, {})

    def test_agent_cannot_change_identity(self):
        for field, value in (("variant", "V02"), ("revision", "R02")):
            agents = list(default_agents())
            agents[1] = AlteredAgent("hidravlik", lambda h: setattr(h, field, value))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.run_cycle(Orchestrator(agents))

    def test_agent_cannot_change_inputs_or_previous_results(self):
        changes = (
            lambda h: h.inputs.update(payload_kg=999),
            lambda h: h.results["konstruktor"].update(concept="Spremenjeno"),
            lambda h: h.open_questions.clear(),
            lambda h: h.results.pop("hidravlik"),
        )
        for change in changes:
            agents = list(default_agents())
            agents[1] = AlteredAgent("hidravlik", change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.run_cycle(Orchestrator(agents))

    def test_completed_handoff_cannot_be_reused(self):
        with self.assertRaises(ValueError):
            self.run_cycle(handoff=self.run_cycle())

    def test_new_revision_requires_fresh_handoff(self):
        result = self.run_cycle(handoff=Handoff("V01", "R02", {"data_origin": "synthetic"}),
                                revision="R02")
        self.assertEqual(result.label, "V01-R02")
        self.assertEqual(result.results["recenzent"]["next_revision"], "R03")

    def test_hydraulics_cannot_run_first(self):
        with self.assertRaises(ValueError):
            SimulatedAgent("hidravlik").run(self.handoff)


if __name__ == "__main__":
    unittest.main()
