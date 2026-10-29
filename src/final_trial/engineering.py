"""Reuse existing mathematics, independently validate catalogue and KB-only costs."""
from copy import deepcopy
import math
from src.models.contracts import digest
from src.engineering.calculations import construction, hydraulics
from src.engineering.contracts import UNITS, compare
from src.engineering.review import review
from src.orchestrator.revision_policy import B_PARAMETERS, fixed_requirements

COST_FOR={'HYD-01':'COST-03','HYD-02':'COST-04','HYD-03':'COST-05','HYD-04':'COST-06','HYD-05':'COST-07','HYD-06':'COST-08'}


def stage(data, inputs):return {**data,'units':UNITS.copy(),'input_sha256':digest(inputs)}


def geometry(inputs):return stage(construction(inputs),inputs)


def catalogue(kb, constructor, choice):
    if set(choice)!={'cylinder_id','pump_id','pressure_bar'}:raise ValueError('Nepopolna izbira hidravlike.')
    cid,pid,pressure=[choice[k] for k in ('cylinder_id','pump_id','pressure_bar')]
    if cid not in ('HYD-01','HYD-02','HYD-03','HYD-04') or pid not in ('HYD-05','HYD-06') or type(pressure)not in (int,float) or pressure not in (160,200,250,315):raise ValueError('Neveljaven kataloški ID ali tlak.')
    cylinder,pump=kb['components'][cid],kb['components'][pid]
    force=pressure*.1*math.pi*cylinder['bore_mm']**2/4
    options=[]
    for identifier in ('HYD-01','HYD-02','HYD-03','HYD-04'):
        c=kb['components'][identifier]
        options.append({'id':identifier,'bore_mm':c['bore_mm'],'max_pressure_bar':c['max_pressure_bar'],
                        'ideal_capacity_at_selected_pressure_N':pressure*.1*math.pi*c['bore_mm']**2/4,
                        'pressure_permitted':pressure<=c['max_pressure_bar'],'price_id':COST_FOR[identifier],
                        'price_EUR':kb['prices'][COST_FOR[identifier]]['amount_EUR']})
    return {'choice':deepcopy(choice),'cylinder':cylinder,'pump':pump,'ideal_capacity_N':force,
            'peak_required_force_N':constructor['peak_cylinder_force_N'],
            'nominal_force_pass':force>=constructor['peak_cylinder_force_N'],
            'pressure_pass':pressure<=min(cylinder['max_pressure_bar'],pump['max_pressure_bar']),
            'required_stroke_mm':constructor['stroke_mm'],'catalogue_stroke_mm':None,'installation_length_mm':None,
            'hydraulic_efficiency':None,'installation_verified':False,'alternatives':options,
            'basis':'F=p×0,1×pi×D²/4, idealni izteg eta=1. Dejanski hidravlični izkoristek, izgube, hod in vgradnja niso potrjeni. Kataloški pretok ni zahtevan pretok.'}



def eligible_hydraulic_choices(kb, force_N):
    """Nominal force/pressure filter only; no assertion of stroke or installation."""
    options=[]
    for cid in ('HYD-01','HYD-02','HYD-03','HYD-04'):
        cylinder=kb['components'][cid]
        for pid in ('HYD-05','HYD-06'):
            pump=kb['components'][pid]
            for pressure in (160,200,250,315):
                if pressure<=min(cylinder['max_pressure_bar'],pump['max_pressure_bar']) and pressure*.1*math.pi*cylinder['bore_mm']**2/4>=force_N:
                    options.append({'cylinder_id':cid,'pump_id':pid,'pressure_bar':pressure})
    return options


def hydraulic(inputs,c,kb,choice):
    data=stage(hydraulics(inputs,c),inputs)
    data['catalogue']=catalogue(kb,c,choice)
    return data


def economics(inputs,c,h,kb):
    cat=h['catalogue'];choice=cat['choice']
    identifiers=['COST-01','COST-02',COST_FOR[choice['cylinder_id']],COST_FOR[choice['pump_id']],'COST-09','COST-10','COST-11','COST-12']
    items=[];bom=[]
    for identifier in identifiers:
        price=kb['prices'][identifier];quantity=1 if price['amount_EUR'] is not None else None
        source=f"{kb['document']}#sha256:{kb['sha256']}#{identifier}:tabela={price['source']['table']}:vrstica={price['source']['row']}"
        items.append({'category':identifier,'price_kind':price['price_kind'],'amount_EUR':price['amount_EUR'],'source':source})
        bom.append({'id':identifier,'description':price['name'],'quantity':quantity,'quantity_unit':'kos / scenarijski sklop' if quantity else 'NI PODATKA',
                    'unit_price_EUR':price['amount_EUR'],'amount_EUR':price['amount_EUR'],'source':source,
                    'quantity_basis':'Sintetičen scenarij enega sklopa; ni proizvodna kosovnica.'})
    return stage({'status':'incomplete_estimate','engineering_verified':False,'source_constructor_sha256':digest(c),'source_hydraulics_sha256':digest(h),
                  'verified_prices':[],'cost_items':items,'bom':bom,'synthetic_subtotal_EUR':sum(i['amount_EUR'] for i in items if i['amount_EUR']is not None),
                  'total_EUR':None,'basis':'Delni sintetični seštevek COST iz KB-01; manjkajo COST-10/11/12, DDV, realne količine in ponudbe.'},inputs)


def findings(inputs,c,h,e,kb):
    expected=economics(inputs,c,h,kb)
    r=stage(review(inputs,c,h,e,cost_catalogue=expected['cost_items']),inputs)
    if not r['calculation_check_passed']:raise ValueError('Deterministična recenzija je zavrnila matematično predajo.')
    cat=h['catalogue']
    r['catalogue_checks']=[{'id':'KB-CAPACITY','pass':cat['nominal_force_pass'] and cat['pressure_pass'],'reference':['REV-03',cat['choice']['cylinder_id']],
                            'description':'Idealna sila in dovoljen tlak izbranega kataloškega cilindra.'}]
    fixed=[('REV-03','hidravlik','Hod, vgradnja, uklon in dejanski hidravlični izkoristek niso potrjeni.'),
           ('REV-04','hidravlik','NI PODATKA za čas dviga; zahtevani pretok in moč nista potrjena.'),
           ('REV-05','konstruktor','Napetosti, uklon, spoji, stabilnost in ekscentrična obremenitev niso preverjeni.'),
           ('REV-06','ekonomist','COST-10 do COST-12 so neznani; delni sintetični seštevek ni cena naprave.'),
           ('REV-07','recenzent','Varnostna kategorija in skladnost nista določeni; konstrukcija ni odobrena.')]
    fs=[{'id':i,'severity':'major','status':'open','target_agent':owner,'description':description,'required_correction':description} for i,owner,description in fixed]
    if not r['catalogue_checks'][0]['pass']:
        fs.append({'id':'KB-CAPACITY','severity':'major','status':'open','target_agent':'hidravlik','description':'Izbrani cilinder nima zadostne idealne sile pri dovoljenem tlaku ali je tlak nedovoljen.',
                   'required_correction':'Iz kataloga HYD predlagaj cilinder in tlak z zadostno idealno silo; vgradnje s tem ne potrdiš.'})
    r['findings']=fs;r['status']='changes_required'
    return r


def apply_geometry(inputs, proposal, requests, kb):
    if proposal is None:return deepcopy(inputs),{'status':'unchanged','reason':'Konstruktor ni podal geometrijske spremembe.'}
    if proposal['parameter']not in B_PARAMETERS:raise ValueError('Predlog spreminja fiksno zahtevo ali izračunano vrednost.')
    matches=[r for r in requests if r['id']==proposal['request_id'] and r['target_agent']=='konstruktor' and r.get('objective')=='reduce_peak_force' and 'GEO-01' in r.get('source_ids',[])]
    if not matches:return deepcopy(inputs),{'status':'not_applied','reason':'Ni sledljive konstruktorjeve naloge; ročni pregled.'}
    if not proposal['reason'].strip() or not proposal['source_ids'] or any(s not in kb['records'] for s in proposal['source_ids']):raise ValueError('Predlog nima preverljivega vira in razloga.')
    candidate=deepcopy(inputs);candidate[proposal['parameter']]=proposal['new_value']
    if fixed_requirements(candidate)!=fixed_requirements(inputs):raise ValueError('Fiksne zahteve so zaklenjene.')
    before,after=geometry(inputs),geometry(candidate)
    # Limited supported objective. No invented proof of buckling/stability.
    if proposal['objective']!='reduce_peak_force' or after['peak_cylinder_force_N']>=before['peak_cylinder_force_N']-0.01:
        return deepcopy(inputs),{'status':'not_applied','reason':'Ni dokazanega zmanjšanja sile; druge konstrukcijske kontrole zahtevajo ročni pregled.'}
    return candidate,{'status':'applied','parameter':proposal['parameter'],'before':before['parameters'][proposal['parameter']],
                      'after':candidate[proposal['parameter']],'reason':proposal['reason'],'source_ids':proposal['source_ids'],
                      'request_id':proposal['request_id'],'objective':'reduce_peak_force','before_force_N':before['peak_cylinder_force_N'],
                      'after_force_N':after['peak_cylinder_force_N'],'stroke_before_mm':before['stroke_mm'],'stroke_after_mm':after['stroke_mm'],
                      'tradeoff':'Zmanjšanje idealne sile ne dokazuje stabilnosti, izvedljivosti cilindra ali splošnega izboljšanja konstrukcije.'}
