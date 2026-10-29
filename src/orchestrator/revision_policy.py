"""Immutable A requirements, explicit B proposals and evidence-only task resolution."""

from copy import deepcopy
from src.models.contracts import ORDER, digest
from src.engineering.review import review
from src.engineering.contracts import reference
from src.models import Handoff

B_PARAMETERS = ("arm_length_mm", "structure_offset_mm", "cylinder_base_x_mm", "rod_pin_fraction")
REFERENCES = {"konstruktor": "results.konstruktor.engineering",
              "hidravlik": "results.hidravlik.engineering", "ekonomist": "results.ekonomist.engineering.cost_items",
              "recenzent": "results.recenzent.engineering.checks"}


class RevisionError(ValueError):
    code = "revision_policy_failed"


def fixed_requirements(inputs):
    return {"inputs": {k: deepcopy(v) for k,v in inputs.items() if k not in B_PARAMETERS},
            "required_lift_mm": inputs["max_height_mm"] - inputs["min_height_mm"]}


def require_fixed(inputs, snapshot):
    if fixed_requirements(inputs) != snapshot:
        raise RevisionError("Fiksne zahteve A so bile spremenjene; revizija je ustavljena.")


def effective_parameters(result):
    return {k: result.results["konstruktor"]["engineering"]["parameters"][k] for k in B_PARAMETERS}


def audit(result):
    return review(result.inputs, *(result.results[n]["engineering"] for n in ORDER[:3]))


def extract_tasks(result):
    result.validate()
    reviewer=result.results["recenzent"]
    groups=(("local",reviewer["engineering"]["findings"]),("reviewer",reviewer.get("findings",[])))
    tasks={}
    for origin,findings in groups:
        for index,finding in enumerate(findings):
            if finding.get("status") == "resolved":
                # A reviewer assertion alone is never proof that work was completed.
                claimed_resolved=True
            else:
                claimed_resolved=False
            owner=finding.get("target_agent")
            owner=owner if owner in ORDER else None  # never guess from prose
            link=finding.get("reference")
            link=link if isinstance(link,str) and (link.startswith("inputs.") or link.startswith("results.")) else REFERENCES.get(owner,"manual_review")
            identity={"description":finding.get("description","Manjka opis ugotovitve."),
                      "owner":owner,"reference":link,"correction":finding.get("required_correction","Potreben je ročni pregled."),
                      "severity":finding.get("severity","unknown")}
            fingerprint=digest(identity)
            task_id="V01-T-"+fingerprint[:16]
            if task_id in tasks and tasks[task_id]["fingerprint"] != fingerprint:
                raise RevisionError("Kolizija oznak nalog.")
            if task_id not in tasks:
                tasks[task_id]={"id":task_id,"fingerprint":fingerprint,"description":identity["description"],
                    "responsible_agent":owner,"importance":identity["severity"],"reference":link,
                    "reference_inferred":not bool(finding.get("reference")),"proposed_correction":identity["correction"],
                    "status":"open","manual_review":owner is None,"requires_user_decision":owner is None or link.startswith("inputs."),
                    "sources":[],"verification":None,"reviewer_claimed_resolved":claimed_resolved}
            task=tasks[task_id]
            task["reviewer_claimed_resolved"] |= claimed_resolved
            task["sources"].append({"origin":origin,"finding_id":str(finding.get("id",index)),"revision":result.revision,
                                    "result_sha256":digest(result.to_dict()),"claimed_status":finding.get("status","open")})
            # Only a failed LOCAL numerical check can define a machine-verifiable task.
            if origin == "local":
                for check in reviewer["engineering"]["checks"]:
                    if check["status"] == "fail" and check["check"] == identity["description"] and check["target_agent"] == owner:
                        task["verification"]={"type":"independent_check_transition","check":check["check"],"owner":owner}
    return list(tasks.values())


def transition_is_proven(task, before, after):
    if task.get("manual_review") or task.get("requires_user_decision"):
        return False
    verifier=task.get("verification")
    trusted = any(s["origin"]=="local" and s["result_sha256"]==digest(before.to_dict()) for s in task.get("sources",[]))
    if not trusted or not verifier or verifier.get("type") != "independent_check_transition" or verifier.get("check") != task["description"]:
        return False
    def state(result):
        matches=[c for c in audit(result)["checks"] if c["check"]==verifier["check"] and c["target_agent"]==verifier["owner"]]
        return matches[0]["status"] if len(matches)==1 else None
    return state(before)=="fail" and state(after)=="pass"


def reconcile(tasks, before, after):
    current=extract_tasks(after)
    matching={t["fingerprint"]:t for t in current}
    updated=[]
    for old in tasks:
        task=deepcopy(old)
        recurring_open=False
        if task["fingerprint"] in matching:
            recurrence=matching.pop(task["fingerprint"])
            task["sources"].extend(recurrence["sources"])
            recurring_open=any(s.get("claimed_status") != "resolved" for s in recurrence["sources"])
        if not recurring_open and transition_is_proven(task,before,after):
            task.update(status="resolved",resolution="Neodvisna deterministična kontrola se je spremenila iz fail v pass.")
            task["evidence"]={"before_sha256":digest(before.to_dict()),"after_sha256":digest(after.to_dict()),"check":task["verification"]["check"]}
        else:
            task.update(status="unresolved",resolution="Ni novega preverljivega dokaza; ponovljen cikel ali izginotje besedila ne odpravi ugotovitve.")
        updated.append(task)
    for task in matching.values():
        task.update(status="open",resolution="Nova ugotovitev v drugi reviziji.")
        updated.append(task)
    return updated


def deterministic_probe(previous, inputs):
    """Recalculate only; no agent, no API, no extra development revision."""
    probe=Handoff(previous.variant,previous.revision,deepcopy(inputs),input_sources={k:"synthetic:proposal-check" for k in inputs})
    for name in ORDER:
        probe.results[name]={"engineering":reference(probe,name)}
    return probe


def evaluate_proposal(previous, task, proposal, snapshot):
    """Future constructor proposal interface; no textual claim can authorize a change."""
    decision={"task_id":task["id"],"parameter":proposal.get("parameter"),"status":"not_applied"}
    parameter=proposal.get("parameter")
    if parameter not in B_PARAMETERS:
        return previous.inputs.copy(),{**decision,"reason":"fixed_or_derived_or_unsupported_field","requires_user_decision":True}
    if task.get("responsible_agent") != "konstruktor" or task.get("manual_review") or task.get("requires_user_decision") or not task.get("verification"):
        return previous.inputs.copy(),{**decision,"reason":"no_verifiable_constructor_task","requires_user_decision":False}
    if not isinstance(proposal.get("reason"),str) or not proposal["reason"].strip():
        return previous.inputs.copy(),{**decision,"reason":"missing_justification","requires_user_decision":False}
    # If recalculation of the unchanged geometry already fixes the numerical error,
    # do that; do not create a cosmetic geometry change.
    try:
        same=deterministic_probe(previous,previous.inputs)
        if transition_is_proven(task,previous,same):
            return previous.inputs.copy(),{**decision,"reason":"recalculation_without_geometry_change_suffices","requires_user_decision":False}
    except ValueError:
        pass
    candidate=deepcopy(previous.inputs);candidate[parameter]=proposal.get("new_value")
    require_fixed(candidate,snapshot)
    try:
        probe=deterministic_probe(previous,candidate)
        if not transition_is_proven(task,previous,probe):
            raise RevisionError("no proof")
    except (ValueError,KeyError,TypeError):
        return previous.inputs.copy(),{**decision,"reason":"candidate_not_verified","requires_user_decision":False}
    return candidate,{**decision,"status":"applied","reason":proposal["reason"],
                      "old_value":effective_parameters(previous)[parameter],"new_value":candidate[parameter],
                      "evidence":{"before_sha256":digest(previous.to_dict()),"probe_sha256":digest(probe.to_dict())}}


class ConservativeConstructorPlanner:
    def propose(self, previous, tasks):
        # Current findings concern structural checks/installation/verified offers,
        # not a proven geometry defect. Never invent material data or optimize just
        # to obtain a different revision. This interface accepts future verified rules.
        return []


def revision_work(name, context):
    assigned=[t for t in context.get("tasks",[]) if t.get("responsible_agent")==name]
    if name=="recenzent":
        assigned=context.get("tasks",[])
    return {"received_task_ids":[t["id"] for t in assigned],
            "actions":[{"task_id":t["id"],"action":"recalculated_and_reviewed",
                        "status":"unresolved","reason":"Preveritev je ponovno izvedena; tehnično zaprtje zahteva ločen dokaz."} for t in assigned]}
