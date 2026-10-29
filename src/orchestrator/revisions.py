"""At most R01 and R02, simulation only. No hidden paid-client factory or retries."""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from src.models import Handoff
from src.models.contracts import digest, validate_inputs
from .cycles import CycleRunner
from .revision_policy import (RevisionError, ConservativeConstructorPlanner, B_PARAMETERS, effective_parameters,
                              evaluate_proposal, extract_tasks, fixed_requirements, require_fixed, reconcile)

HARD_REVISION_LIMIT = 2


class RevisionRunner:
    def __init__(self, directory, *, max_revisions=2, mode="simulated", planner=None):
        if mode != "simulated":
            raise RevisionError("Plačljivi večrevizijski način je onemogočen. Dva cikla bi zahtevala do 8 klicev; dovoljenih ostaja največ 4 na ločeno odobren preizkus.")
        if type(max_revisions) is not int or not 1 <= max_revisions <= HARD_REVISION_LIMIT:
            raise RevisionError("Naloga 06 dovoljuje največ dve reviziji; R03 ni dovoljena.")
        self.directory=Path(directory)
        self.max_revisions=max_revisions
        self.planner=planner or ConservativeConstructorPlanner()

    def run(self, initial, *, approved_sequence=None):
        if type(self.max_revisions) is not int or not 1 <= self.max_revisions <= HARD_REVISION_LIMIT:
            raise RevisionError("Presežena trda omejitev dveh revizij.")
        initial.validate();validate_inputs(initial)
        if (initial.variant != "V01" or initial.revision != "R01" or initial.results or initial.revision_context
                or initial.inputs.get("data_origin") != "synthetic" or initial.inputs["payload_kg"] != 300
                or initial.inputs["max_height_mm"]-initial.inputs["min_height_mm"] != 650):
            raise RevisionError("Potreben je začetni sintetični V01-R01, 300 kg in dvig 650 mm; V02 ni dovoljen.")
        scope=f"V01:R01-R{self.max_revisions:02d}"
        if approved_sequence != scope:
            raise RevisionError("Manjka izrecna odobritev omejenega simuliranega zaporedja: "+scope)
        self.directory.mkdir(parents=True,exist_ok=True)
        state_path=self.directory/"sequence.json"
        snapshot=fixed_requirements(initial.inputs)
        state={"variant":"V01","mode":"simulated","approved_sequence":scope,"max_revisions":self.max_revisions,
               "status":"running","api_requests_started":0,"fixed_requirements":snapshot,
               "fixed_requirements_sha256":digest(snapshot),"completed_revisions":[],"revision_records":[],"tasks":[],"change_log":[]}
        with state_path.open("x",encoding="utf-8") as file:
            json.dump(state,file,ensure_ascii=False,indent=2)

        def save():
            temporary=state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
            temporary.replace(state_path)

        def stop_requested():
            return (self.directory/"STOP").exists() or (self.directory/"cycles"/"STOP").exists()

        previous=None
        current=deepcopy(initial)
        tasks=[]
        try:
            for index in range(self.max_revisions):
                if stop_requested():
                    raise RevisionError("Zaporedje je ustavljeno na zahtevo uporabnika.")
                require_fixed(current.inputs,snapshot)
                if current.revision != f"R{index+1:02d}" or current.variant != "V01":
                    raise RevisionError("Neveljavno zaporedje variante/revizije.")
                # A stop between agents is also handled by the existing cycle runner.
                runner=CycleRunner(self.directory/"cycles")
                result=runner.run(current,approved_label=current.label,mode="simulated",
                                  source=f"bounded_sequence:{scope}#sha256:{digest(current.to_dict())}")
                require_fixed(result.inputs,snapshot)
                state["completed_revisions"].append(result.label)
                state["revision_records"].append({"label":result.label,"result_sha256":digest(result.to_dict()),
                                                  "parent_sha256":digest(previous.to_dict()) if previous else None,
                                                  "parameters_B":effective_parameters(result),"deterministic_recalculation":True})
                if previous is None:
                    tasks=extract_tasks(result)
                else:
                    tasks=reconcile(tasks,previous,result)
                state["tasks"]=tasks
                save()
                if index+1 == self.max_revisions:
                    previous=result
                    break
                if result.results["recenzent"]["decision"] != "changes_required":
                    state["stop_reason"]="review_did_not_request_another_revision"
                    previous=result
                    break
                candidate=deepcopy(result.inputs)
                decisions=[]
                assigned=[t for t in tasks if t["responsible_agent"]=="konstruktor"]
                proposals=self.planner.propose(deepcopy(result),deepcopy(assigned))
                if not isinstance(proposals,list):
                    raise RevisionError("Konstruktorjev načrt mora biti seznam strukturiranih predlogov.")
                applied=False
                for proposal in proposals:
                    if not isinstance(proposal,dict):
                        raise RevisionError("Neveljaven predlog spremembe.")
                    task=next((t for t in tasks if t["id"]==proposal.get("task_id")),None)
                    if task is None:
                        raise RevisionError("Predlog nima sledljive naloge Recenzenta.")
                    if applied:
                        decision={"task_id":task["id"],"status":"not_applied","reason":"additional_proposal_requires_review","requires_user_decision":True}
                    else:
                        candidate,decision=evaluate_proposal(result,task,proposal,snapshot)
                        applied=decision["status"]=="applied"
                    task["requires_user_decision"] |= decision.get("requires_user_decision",False)
                    decisions.append(decision)
                require_fixed(candidate,snapshot)
                changes={key:{"before":result.inputs.get(key,effective_parameters(result)[key]),"after":candidate.get(key,effective_parameters(result)[key])}
                         for key in B_PARAMETERS if result.inputs.get(key,effective_parameters(result)[key]) != candidate.get(key,effective_parameters(result)[key])}
                state["change_log"].append({"from":result.revision,"to":f"R{index+2:02d}","parameters":changes,"proposal_decisions":decisions,
                                           "reason":"verified_constructor_proposal" if changes else "Ni utemeljenega geometrijskega popravka; vrednosti so ohranjene."})
                sources=deepcopy(result.input_sources)
                for key in changes:
                    sources[key]=f"verified-proposal:{digest(decisions)}"
                current=Handoff("V01",f"R{index+2:02d}",candidate,input_sources=sources,
                    open_questions=deepcopy(result.open_questions),revision_context={
                        "kind":"bounded_simulation","source_revision":result.revision,"source_result_sha256":digest(result.to_dict()),
                        "fixed_requirements_sha256":digest(snapshot),"tasks":deepcopy(tasks),"change_log":deepcopy(state["change_log"]),
                        "approval_scope":scope,"paid_mode_enabled":False})
                previous=result
                save()
            state["status"]="limit_reached"
            state.setdefault("stop_reason","max_revisions_reached")
            state["classification"]={"resolved":[t["id"] for t in tasks if t["status"]=="resolved"],
                "unresolved":[t["id"] for t in tasks if t["status"]=="unresolved"],
                "open":[t["id"] for t in tasks if t["status"]=="open"],
                "unchanged_open":[t["id"] for t in tasks if t["status"]=="unresolved" and {s["revision"] for s in t["sources"]}>={"R01","R02"}],
                "new_findings":[t["id"] for t in tasks if t["status"]=="open" and any(s["revision"]=="R02" for s in t["sources"])],
                "requires_user_decision":[t["id"] for t in tasks if t["requires_user_decision"]]}
            save()
            if state["completed_revisions"]==["V01-R01","V01-R02"]:
                from src.reporting.revisions import build_revision_package
                archive=build_revision_package(self.directory,state)
                state["development_cycle_package"]=str(archive.relative_to(self.directory))
                save()
            return state
        except BaseException:
            state["status"]="stopped"
            state["stop_reason"]="revision_or_document_failure"
            save()
            raise


def main():
    parser=argparse.ArgumentParser(description="Omejena brezplačna simulacija V01-R01 → V01-R02")
    parser.add_argument("input",type=Path)
    parser.add_argument("--output-dir",type=Path,default=Path("revision-artifacts"))
    parser.add_argument("--max-revisions",type=int,default=2)
    parser.add_argument("--mode",choices=("simulated","openai"),default="simulated")
    parser.add_argument("--approve-sequence",required=True,help="V01:R01-R02 odobri samo omejeno simulacijo")
    args=parser.parse_args()
    try:
        data=json.loads(args.input.read_text(encoding="utf-8"))
        initial=Handoff(**data)
        if not initial.input_sources:
            initial.input_sources={key:f"synthetic:{args.input.name}" for key in initial.inputs}
        state=RevisionRunner(args.output_dir,max_revisions=args.max_revisions,mode=args.mode).run(initial,approved_sequence=args.approve_sequence)
    except (ValueError,OSError,TypeError):
        parser.exit(1,"Zaporedje ni zaključeno. Preveri odobritev, V01, omejitve in sequence.json; plačljivi način je onemogočen.\n")
    print(json.dumps({"status":state["status"],"revisions":state["completed_revisions"],"api_requests_started":0,
                      "package":state.get("development_cycle_package")},ensure_ascii=False))


if __name__=="__main__":
    main()
