"""Skupna, v JSON zapisljiva predaja med agenti."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import re
from typing import Any

from .contracts import canonical


@dataclass
class Handoff:
    variant: str
    revision: str
    inputs: dict[str, Any]
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    input_sources: dict[str, str] = field(default_factory=dict)

    revision_context: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    @property
    def label(self) -> str:
        return f"{self.variant}-{self.revision}"

    def validate(self) -> None:
        for value, pattern in ((self.variant, r"V[0-9]{2,}"),
                               (self.revision, r"R[0-9]{2,}")):
            if (not isinstance(value, str) or not re.fullmatch(pattern, value)
                    or int(value[1:]) < 1):
                raise ValueError("Pričakovani oznaki: V01 in R01 ali višji številki.")
        if not isinstance(self.inputs, dict) or not isinstance(self.results, dict):
            raise ValueError("Vhodi in rezultati morajo biti slovarji.")
        if any(not isinstance(k, str) or not isinstance(v, dict)
               for k, v in self.results.items()):
            raise ValueError("Rezultat vsakega agenta mora biti slovar.")
        if (not isinstance(self.open_questions, list)
                or any(not isinstance(q, str) for q in self.open_questions)):
            raise ValueError("Odprta vprašanja morajo biti seznam nizov.")

        if (not isinstance(self.input_sources, dict)
                or any(k not in self.inputs or not isinstance(v, str) or not v.strip()
                       for k, v in self.input_sources.items())):
            raise ValueError("Viri morajo povezovati vhodna polja z nepraznimi opisi izvora.")
        if not isinstance(self.revision_context, dict):
            raise ValueError("Revizijski kontekst mora biti strukturiran objekt.")
        try:
            canonical(self.to_dict())
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError("Predaja mora vsebovati končne JSON vrednosti.") from exc

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if not data["revision_context"]:
            data.pop("revision_context")  # preserve old JSON contracts when no revision sequence is used
        return data

    def with_result(self, agent: str, result: dict[str, Any],
                    questions: list[str] | None = None) -> "Handoff":
        if agent in self.results:
            raise ValueError(f"Agent {agent} že ima rezultat v {self.label}.")
        updated = deepcopy(self)
        updated.results[agent] = deepcopy(result)
        updated.open_questions.extend(questions or [])
        updated.validate()
        return updated
