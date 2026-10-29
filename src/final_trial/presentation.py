"""Verified engineering drives published facts; original model prose stays in JSON."""
from copy import deepcopy
import re
from src.reporting.documents import fmt


def document_view(handoff):
    view=deepcopy(handoff)
    hydraulic=view.results['hidravlik'];catalogue=hydraulic['engineering']['catalogue'];choice=catalogue['choice']
    raw=handoff.results['hidravlik'];notes=[]
    fields={'summary':raw.get('summary',''),'outputs':str(raw.get('outputs',[])),
            'assumptions':str(raw.get('assumptions',[])),'open_questions':str(raw.get('open_questions',[]))}
    for field,text in fields.items():
        others=sorted(set(re.findall(r'\bHYD-0[1-4]\b',text))-{choice['cylinder_id']})
        if others:
            notes.append({'agent':'hidravlik','source_path':f'results.hidravlik.{field}',
                          'reason':'prose_mentions_other_cylinder','mentioned_ids':others,
                          'structured_cylinder_id':choice['cylinder_id'],'status':'unconfirmed_prose'})
    # Never rewrite the source handoff or attribute these words to the model.
    hydraulic['summary']=(f"Deterministični povzetek strukturirane predaje (izvoznik): {choice['cylinder_id']} / {choice['pump_id']}, "
        f"{fmt(choice['pressure_bar'],0)} bar; idealna zmogljivost {fmt(catalogue['ideal_capacity_N'])} N, zahtevana sila "
        f"{fmt(catalogue['peak_required_force_N'])} N. Nominalna sila: {'zadostna' if catalogue['nominal_force_pass'] else 'NEZADOSTNA'}; "
        "hod, vgradnja, dejanski izkoristek in varnost niso potrjeni. Izvirno besedilo AI ostaja v 08_Izvorni_podatki.json.")
    hydraulic['outputs']=[]
    hydraulic['open_questions']=[f"{choice['cylinder_id']}: hod, vgradna mera in uklon niso potrjeni.",
        'Moč na gredi in dejanski hidravlični izkoristek nista potrjena.']
    if hydraulic['engineering']['lift_time_s'] is None:
        hydraulic['open_questions'].append('Čas dviga, zahtevani pretok in hidravlična moč niso določeni; NI PODATKA.')
    if notes:view.open_questions=[f['description'] for f in view.results['recenzent']['engineering']['findings']]
    return view,notes
