"""En razvojni cikel v predpisanem vrstnem redu."""

from copy import deepcopy
from typing import Callable, Protocol, Sequence

from src.models.contracts import validate_review
from src.engineering.contracts import validate_stage

from src.agents.simulated import ORDER, default_agents
from src.models import Handoff


class Agent(Protocol):
    name: str

    def run(self, handoff: Handoff) -> Handoff: ...


class Orchestrator:
    def __init__(self, agents: Sequence[Agent] | None = None) -> None:
        self.agents = tuple(default_agents() if agents is None else agents)
        if tuple(agent.name for agent in self.agents) != ORDER:
            raise ValueError("Vrstni red mora biti: " + " → ".join(ORDER))

    def run(self, handoff: Handoff, *, expected_variant: str,
            expected_revision: str, on_step: Callable[[Handoff], None] | None = None,
            should_stop: Callable[[], bool] | None = None) -> Handoff:
        handoff.validate()
        identity = (expected_variant, expected_revision)
        if (handoff.variant, handoff.revision) != identity:
            raise ValueError("Vhodna varianta ali revizija ne ustreza pričakovani.")
        if handoff.results:
            raise ValueError("Nov cikel zahteva predajo brez prejšnjih rezultatov.")
        current = deepcopy(handoff)
        for index, agent in enumerate(self.agents):
            if should_stop is not None and should_stop():
                raise ValueError("Proces je ustavljen na zahtevo uporabnika.")
            output = agent.run(deepcopy(current))
            if not isinstance(output, Handoff):
                raise ValueError("Agent mora vrniti strukturirano predajo Handoff.")
            output.validate()
            if (output.variant, output.revision) != identity:
                raise ValueError(f"Agent {agent.name} je spremenil varianto ali revizijo.")
            if output.inputs != current.inputs or output.input_sources != current.input_sources:
                raise ValueError(f"Agent {agent.name} je spremenil vhodne podatke.")
            if tuple(output.results) != ORDER[:index + 1]:
                raise ValueError(f"Napačno zaporedje rezultatov agenta {agent.name}.")
            if any(output.results[name] != value for name, value in current.results.items()):
                raise ValueError("Agent je spremenil že predane rezultate.")
            if output.open_questions[:len(current.open_questions)] != current.open_questions:
                raise ValueError("Agent je odstranil ali spremenil odprta vprašanja.")
            validate_stage(current, agent.name, output.results[agent.name])
            if agent.name == "recenzent":
                validate_review(output.results[agent.name])
            current = deepcopy(output)
            if on_step is not None:
                on_step(deepcopy(current))
        return current
