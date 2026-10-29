"""Compare two completed revisions without inventing improvement or a new calculation."""

from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED

from src.models import Handoff
from src.models.contracts import digest
from src.orchestrator.cloud import write_json
from src.orchestrator.revision_policy import B_PARAMETERS, effective_parameters, fixed_requirements, transition_is_proven, RevisionError
from .documents import fonts, paragraph, table, section, pdf, fmt, WIDTH, LABELS
from .source import prepare, redact

STATUS={"open":"odprto","resolved":"rešeno","unresolved":"nerešeno"}


def comparison_data(first, second, tasks):
    if (first.label,second.label)!=("V01-R01","V01-R02"):
        raise RevisionError("Primerjava zahteva V01-R01 in V01-R02.")
    if fixed_requirements(first.inputs)!=fixed_requirements(second.inputs):
        raise RevisionError("Primerjava je zavrnjena: fiksne zahteve niso enake.")
    for task in tasks:
        if task["status"]=="resolved" and not transition_is_proven(task,first,second):
            raise RevisionError("Naloga je označena kot rešena brez neodvisnega dokaza.")
    before=effective_parameters(first);after=effective_parameters(second)
    c1,c2=[r.results["konstruktor"]["engineering"] for r in (first,second)]
    h1,h2=[r.results["hidravlik"]["engineering"] for r in (first,second)]
    e1,e2=[r.results["ekonomist"]["engineering"] for r in (first,second)]
    numeric={"peak_cylinder_force_N":{"R01":c1["peak_cylinder_force_N"],"R02":c2["peak_cylinder_force_N"],"unit":"N"},
             "stroke_mm":{"R01":c1["stroke_mm"],"R02":c2["stroke_mm"],"unit":"mm"},
             "synthetic_subtotal_EUR":{"R01":e1["synthetic_subtotal_EUR"],"R02":e2["synthetic_subtotal_EUR"],"unit":"EUR"}}
    return {"variant":"V01","revisions":["R01","R02"],"fixed_requirements":fixed_requirements(first.inputs),
            "parameters_B":{k:{"R01":before[k],"R02":after[k],"changed":before[k]!=after[k]} for k in B_PARAMETERS},
            "metrics_C":numeric,"hydraulics":{"R01":h1,"R02":h2},"costs":{"R01":e1,"R02":e2},
            "tasks":tasks,"resolved_count":sum(t["status"]=="resolved" for t in tasks),
            "improvement_demonstrated":any(t["status"]=="resolved" and t.get("evidence") for t in tasks),
            "technical_approval":False,"review_decision":second.results["recenzent"]["decision"],
            "source_sha256":{"R01":digest(first.to_dict()),"R02":digest(second.to_dict())}}


def write_comparison(path, first, second, data):
    fonts();story=[]
    section(story,"Obseg primerjave",["Brezplačna simulacija dveh razvojnih revizij V01. Uspešno ponovljeni izračuni ne pomenijo odpravljenih tehničnih tveganj.",
        "Dokazano izboljšanje: "+("odpravljena konkretna numerična napaka; to ni splošna tehnična odobritev." if data["improvement_demonstrated"] else "NE. Ni preverljivega dokaza o odpravljenih ugotovitvah; nespremenjena rešitev ni predstavljena kot izboljšava.")])
    section(story,"A – nespremenjene fiksne zahteve",[])
    story.append(table(["Zahteva","R01 = R02"],[[k,fmt(v)] for k,v in data["fixed_requirements"]["inputs"].items()]+[["Zahtevani dvig [mm]",fmt(data["fixed_requirements"]["required_lift_mm"])]],[WIDTH*.45,WIDTH*.55]))
    section(story,"B – geometrijski parametri",[])
    story.append(table(["Parameter","R01","R02","Sprememba"],[[key,fmt(v["R01"]),fmt(v["R02"]),"da – glej dnevnik dokazov" if v["changed"] else "ne"] for key,v in data["parameters_B"].items()],[WIDTH*.4,WIDTH*.2,WIDTH*.2,WIDTH*.2]))
    section(story,"C – ponovno izračunani rezultati",[])
    story.append(table(["Količina","R01","R02","Enota"],[[key,fmt(v["R01"]),fmt(v["R02"]),v["unit"]] for key,v in data["metrics_C"].items()],[WIDTH*.40,WIDTH*.22,WIDTH*.22,WIDTH*.16]))
    section(story,"Primerjava hidravlike",[])
    h1,h2=data["hydraulics"]["R01"],data["hydraulics"]["R02"]
    story.append(table(["Tlak [bar]","Premer R01 [mm]","Premer R02 [mm]"],[[fmt(a["pressure_bar"],0),fmt(a["theoretical_bore_mm"]),fmt(b["theoretical_bore_mm"])] for a,b in zip(h1["pressure_options"],h2["pressure_options"])]))
    section(story,"Pretok in moč",[f"Čas R01: {fmt(h1['lift_time_s'])}; čas R02: {fmt(h2['lift_time_s'])}.",
        "Neznani pretoki in moči niso primerjani kot nič. Oba izvorna niza sta v JSON; razlik brez vhodnih podatkov ne ocenjujemo."])
    e1,e2=data["costs"]["R01"],data["costs"]["R02"]
    section(story,"Stroškovna primerjava",["Primerja se samo primerljivi nepopolni sintetični seštevek, ne celotna cena naprave. Preverjenih ponudb ni. Neznani stroški ostanejo neznani."])
    story.append(table(["Postavka","R01 [EUR]","R02 [EUR]","Vrsta"],[[a["category"],fmt(a["amount_EUR"]),fmt(b["amount_EUR"]),a["price_kind"]] for a,b in zip(e1["cost_items"],e2["cost_items"])]))
    section(story,"Odpravljene, nerešene in nove naloge",[])
    for task in data["tasks"]:
        owner=LABELS.get(task["responsible_agent"],"Ročni pregled")
        section(story,f"{task['id']} · {STATUS[task['status']]} · {task['importance']} · {owner}",[
            task["description"],"Povezava: "+task["reference"],"Predlagani popravek: "+task["proposed_correction"],task.get("resolution","Odprta naloga."),
            "Potrebna odločitev uporabnika: "+("da" if task["requires_user_decision"] else "ne; še vedno ostaja potrebna strokovna preverba.")])
    section(story,"Končna odločitev in ustavitev",[f"Recenzent: {data['review_decision']}; engineering_verified=false. Odpravljenih nalog: {data['resolved_count']}.",
        "Zaporedje se ustavi po R02. R03 ni ustvarjena. API-klicev v tem postopku je 0. Plačljivi večrevizijski način je onemogočen.",
        "Sled R01 SHA-256: "+data["source_sha256"]["R01"],"Sled R02 SHA-256: "+data["source_sha256"]["R02"]])
    pdf(path,"Primerjava R01–R02",second,story,{"input_file":"Dve zaključeni simulirani reviziji; glej JSON in sledi SHA-256."})


def build_revision_package(directory, state):
    directory=Path(directory)
    if state["status"]!="limit_reached" or state["completed_revisions"]!=["V01-R01","V01-R02"] or state["api_requests_started"]!=0:
        raise RevisionError("Celoten večrevizijski paket zahteva obe uspešni simulirani reviziji.")
    records=[];results=[]
    for revision in ("R01","R02"):
        import json
        record=json.loads((directory/"cycles"/f"V01-{revision}.json").read_text())
        result,_=prepare(record)
        if record.get("development_package",{}).get("status")!="created":
            raise RevisionError("Manjka razvojni paket revizije.")
        records.append(record);results.append(result)
    data=redact(comparison_data(*results,state["tasks"]))
    destination=directory/"V01_R01-R02_Razvojni_cikel.zip"
    with TemporaryDirectory(prefix=".revizije-",dir=directory) as tmp:
        root=Path(tmp)
        pdf_path=root/"V01_R01-R02_Primerjava.pdf"
        write_comparison(pdf_path,*results,data)
        write_json(root/"Ugotovitve_in_statusi.json",redact({"tasks":state["tasks"],"classification":state["classification"]}))
        write_json(root/"Primerjava.json",redact(data))
        write_json(root/"Sledljivost_cikla.json",redact(state))
        for result in results:
            write_json(root/f"{result.label}_Izvorni_podatki.json",redact(result.to_dict()))
        with ZipFile(root/destination.name,"w",ZIP_DEFLATED) as archive:
            for file in root.iterdir():
                if file.name!=destination.name: archive.write(file,file.name)
            for revision,record in zip(("R01","R02"),records):
                archive.write(directory/"cycles"/record["development_package"]["path"],f"V01-{revision}_Razvojni_paket.zip")
        with ZipFile(root/destination.name) as archive:
            if archive.testzip() is not None: raise RevisionError("Neveljaven ZIP revizij.")
        (root/destination.name).replace(destination)
    pdf_path=directory/"V01_R01-R02_Primerjava.pdf"
    with ZipFile(destination) as archive:
        pdf_path.write_bytes(archive.read(pdf_path.name))
    return destination
