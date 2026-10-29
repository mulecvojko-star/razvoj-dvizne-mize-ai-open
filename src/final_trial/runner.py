"""A new, separately approved capped trial, building on Task 06 and legacy agents."""
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path

from src.models import Handoff
from src.models.contracts import ORDER, digest, validate_inputs
from src.engineering.contracts import claims
from src.engineering.calculations import EngineeringError
from src.orchestrator.cloud import synthetic_handoff
from src.orchestrator.revision_policy import fixed_requirements, require_fixed
from src.reporting.source import redact
from .knowledge import load_knowledge
from .budget import Budget
from .engineering import geometry, hydraulic, economics, findings, apply_geometry
from .agents import FinalTransport, SimulatedResponder, prompt, schema, validate_response

APPROVAL={'simulated':'ODOBRIM KONCNO SIMULACIJO V01','openai':'ODOBRIM KONCNI AI V01 DO 16 KLICEV'}
ROOT=Path(__file__).resolve().parents[2]


def write(path,value):
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(redact(value),ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');temporary.replace(path)


@dataclass(frozen=True)
class Config:
    mode:str='simulated'
    approval:str=''
    model:str='gpt-5.4-mini'
    threshold:float=3.0
    max_input_tokens:int=100000
    max_prompt_bytes:int=96000
    output_tokens:int=0

    @classmethod
    def environment(cls):
        return cls(os.getenv('FINAL_MODE','simulated'),os.getenv('FINAL_APPROVAL',''),os.getenv('FINAL_MODEL','gpt-5.4-mini'),
                   float(os.getenv('FINAL_BUDGET_USD','3')),int(os.getenv('FINAL_MAX_INPUT_TOKENS','100000')),
                   int(os.getenv('FINAL_MAX_PROMPT_BYTES','96000')),int(os.getenv('FINAL_MAX_OUTPUT_TOKENS','0')))

    def validate(self):
        if self.mode not in APPROVAL or self.approval!=APPROVAL[self.mode]:raise ValueError('Manjka ločena izrecna odobritev zaključnega preizkusa.')
        if self.output_tokens!=0 and (type(self.output_tokens)is not int or not 256<=self.output_tokens<=6000):raise ValueError('Neveljavna izhodna omejitev.')
        # Offline simulation may run in CI push/PR jobs. Only the paid path
        # requires a fresh manual main dispatch; it cannot be unlocked by CI.
        if self.mode=='openai':
            if os.getenv('GITHUB_ACTIONS')!='true' or os.getenv('GITHUB_EVENT_NAME')!='workflow_dispatch' or os.getenv('GITHUB_REF')!='refs/heads/main' or os.getenv('GITHUB_RUN_ATTEMPT')!='1':
                raise ValueError('Plačljivi način zahteva nov ročni GitHub Actions zagon main; ponovitve niso dovoljene.')


def preflight(config,kb_path=None):
    config.validate();initial,_=synthetic_handoff()
    kb=load_knowledge(kb_path or ROOT/'knowledge_base/Testna_baza_znanja_V01.docx',initial.inputs)
    budget=Budget(model=config.model,threshold=config.threshold,max_input_tokens=config.max_input_tokens,max_prompt_bytes=config.max_prompt_bytes,
                  output_limits={n:config.output_tokens for n in ORDER} if config.output_tokens else None)
    estimate=budget.preflight(kb['max_revisions'])
    estimate.update({'knowledge_sha256':kb['sha256'],'knowledge_compatible':kb['compatible'],'conflicts':kb['conflicts'],
                     'approval':config.approval,'mode':config.mode,'paid_requests_started':0})
    return initial,kb,budget,estimate


def task_messages(requests,revision):
    return [{'sender':'recenzent','recipient':r['target_agent'] or 'manual_review','revision':revision,'request':r['id'],
             'reason':r['reason'],'data_sources':r['source_ids'],'status':r.get('status','open'),'correction':r['correction']} for r in requests]


def local_tasks(review, model_requests, kb):
    tasks=[]
    for f in review['findings']:
        tasks.append({'id':f['id'],'target_agent':f['target_agent'],'reason':f['description'],'correction':f['required_correction'],
                      'source_ids':[f['id']] if f['id'] in kb['records'] else ['REV-03'],'severity':f['severity'],'status':'open','origin':'deterministic',
                      'objective':'catalogue_capacity' if f['id']=='KB-CAPACITY' else 'manual_review'})
    for request in model_requests:
        local=next((t for t in tasks if t['id']==request['id']),None)
        if local is not None:
            if request['target_agent']!=local['target_agent']:raise ValueError('Recenzent je spremenil odgovornega agenta lokalne naloge.')
            local['model_request']=deepcopy(request);continue
        # Keep AI-only requests distinct; prose is not evidence of completion.
        identity=digest(request)[:16]
        tasks.append({**deepcopy(request),'id':'AI-'+identity,'original_id':request['id'],'severity':'major','status':'unconfirmed',
                      'manual_review':request['target_agent'] is None,'origin':'model'})
    return tasks


class FinalRunner:
    def __init__(self,directory,config,*,responder=None,kb_path=None,transport_factory=FinalTransport):
        self.directory=Path(directory);self.config=config;self.responder=responder;self.kb_path=kb_path;self.transport_factory=transport_factory

    def run(self):
        initial,kb,budget,estimate=preflight(self.config,self.kb_path)
        self.directory.mkdir(parents=True,exist_ok=True)
        state_path=self.directory/'trial.json'
        state={'format':'V01-final-trial-v1','mode':self.config.mode,'status':'preflight','variant':'V01','engineering_verified':False,
               'knowledge':kb,'estimate':estimate,'revisions':[],'messages':[],'tasks':[],'changes':[],
               'source_requirements':deepcopy(initial.inputs),'fixed_requirements':fixed_requirements(initial.inputs),
               'stop_reason':None,'commit':os.getenv('GITHUB_SHA','local'),'run_id':os.getenv('GITHUB_RUN_ID','local')}
        # Exclusive ledger blocks accidental local replay. Workflow additionally forbids reruns.
        with state_path.open('x',encoding='utf-8') as f:json.dump(redact(state),f,ensure_ascii=False,indent=2)
        transport=None;pending=[];inputs=deepcopy(initial.inputs);name=None;label=None
        def save():
            state['api_usage']=budget.report();write(state_path,state);write(self.directory/'09_API_poraba.json',budget.report())
        try:
            write(self.directory/'preflight.json',estimate)
            if not kb['compatible']:raise ValueError('Blokirajoča neskladja Wordove baze; glej preflight.json in trial.json.')
            if self.config.mode=='openai':
                if not estimate['pricing_valid']:raise ValueError('Plačljivi preizkus zahteva ponovno preverjen cenik.')
                # The factory is called only after all free checks and approval checks.
                transport=self.transport_factory(model=self.config.model,max_output_tokens=4500)
            responder=self.responder or SimulatedResponder()
            for index in range(kb['max_revisions']):
                label=f'R{index+1:02d}'
                h=Handoff('V01',label,deepcopy(inputs),input_sources=deepcopy(initial.input_sources))
                for key in h.inputs:
                    if h.inputs[key]!=initial.inputs.get(key):h.input_sources[key]='verified-change:'+digest(state['changes'])
                partial={'label':h.label,'status':'running','handoff':h.to_dict(),'applied_changes':[]}
                state['partial_revision']=partial;state['status']='running';save()
                actual_change=False
                for name in ORDER:
                    if (self.directory/'STOP').exists():raise ValueError('Uporabnik je ustavil zaključni preizkus.')
                    require_fixed(h.inputs,state['fixed_requirements']);validate_inputs(h)
                    if name=='konstruktor':expected=geometry(h.inputs)
                    elif name=='hidravlik':expected=hydraulic(h.inputs,h.results['konstruktor']['engineering'],kb,{'cylinder_id':'HYD-01','pump_id':'HYD-05','pressure_bar':200})
                    elif name=='ekonomist':expected=economics(h.inputs,h.results['konstruktor']['engineering'],h.results['hidravlik']['engineering'],kb)
                    else:expected=findings(h.inputs,*(h.results[n]['engineering'] for n in ORDER[:3]),kb)
                    instructions,payload=prompt(name,h,kb,expected,pending,state['messages'])
                    response_schema=schema(kb,expected,name)
                    size=len(instructions.encode())+len(payload.encode())+len(json.dumps(response_schema,ensure_ascii=False).encode())
                    if size>budget.max_prompt_bytes or size+2048>budget.max_input_tokens:raise ValueError('Poziv presega odobreno vhodno omejitev.')
                    if transport:
                        if not budget.can_continue():raise ValueError('Neznana ali prevelika prejšnja poraba; nadaljevanje je blokirano.')
                        entry=budget.reserve(name,size);entry['revision']=label;entry['prompt_sha256']=digest([instructions,payload,response_schema]);save()
                        try:data,metadata=transport.request_final(instructions,payload,response_schema,budget.limits[name])
                        except Exception as exc:
                            budget.finish(entry,getattr(exc,'metadata',{}),failed=True);save();raise
                        budget.finish(entry,metadata);save()
                        if not budget.can_continue():raise ValueError('Poraba ali odzivni model ni preverljiv; nadaljevanje je blokirano.')
                    else:
                        data=responder.request(name,h,kb,expected,pending);metadata={'model':'simulated','input_tokens':0,'output_tokens':0}
                    partial['unvalidated_response']=deepcopy(data);save()
                    base=validate_response(data,name,h,kb,expected,pending)
                    partial.pop('unvalidated_response',None)
                    if name=='konstruktor':
                        proposed,decision=apply_geometry(h.inputs,data['proposal'],pending,kb)
                        partial['applied_changes'].append(decision)
                        if decision['status']=='applied':
                            h.inputs=proposed;inputs=deepcopy(proposed);expected=geometry(proposed);actual_change=True
                            for key in h.inputs:
                                if h.inputs[key]!=initial.inputs.get(key):h.input_sources[key]='verified-change:'+digest(decision)
                            state['changes'].append({'revision':label,**decision})
                        if index>0 and not actual_change and not any(t['id']=='KB-CAPACITY' and t['status']=='open' for t in pending):
                            # No justified geometry or catalogue correction: do not fabricate a second complete revision.
                            state['stop_reason']='no_justified_next_change';partial['status']='proposal_only';save();break
                    if name=='hidravlik':
                        expected=hydraulic(h.inputs,h.results['konstruktor']['engineering'],kb,data['selection'])
                        if index:
                            old=state['revisions'][-1]['handoff']['results']['hidravlik']['engineering']['catalogue']
                            changed=old['choice']!=expected['catalogue']['choice']
                            proof=(not old['nominal_force_pass'] or not old['pressure_pass']) and expected['catalogue']['nominal_force_pass'] and expected['catalogue']['pressure_pass']
                            if changed and not proof:raise ValueError('Sprememba komponent nima dokazanega popravka idealne sile/tlaka; potreben ročni pregled.')
                            if changed:
                                actual_change=True;state['changes'].append({'revision':label,'parameter':'hydraulic_selection','before':old['choice'],
                                    'after':data['selection'],'reason':'KB-CAPACITY: dokazano odpravljena nezadostna idealna sila ali nedovoljen tlak; vgradnja ostaja nepotrjena.'})
                            if not actual_change:
                                state['stop_reason']='no_justified_next_change';partial['status']='proposal_only';save();break
                    result={**deepcopy(base),'engineering':expected,'engineering_verified':False,'technical_status':expected['status'],
                            'simulated':not bool(transport),'declared_source_ids':data['source_ids'],'proposal':data['proposal'],
                            'selection':data['selection'],'requests':data['requests'],'request_updates':data['request_updates'],
                            'trace':{**metadata,'input_sha256':digest(h.inputs),'received_handoff_sha256':digest(json.loads(payload)['handoff']),
                                     'knowledge_sha256':kb['sha256'],'revision':label,'prompt_bytes':size,
                                     'conservative_input_token_estimate':size+2048,'prompt_sha256':digest([instructions,payload,response_schema])},
                            'validated_calculations':claims(name,expected)}
                    # Constructor proposal response describes the pre-change reference; preserve it and
                    # explicitly report the post-change deterministic numbers separately.
                    if name=='konstruktor' and data['proposal'] is not None:
                        result['pre_change_model_calculations']=deepcopy(base['calculations']);result['calculations']=claims(name,expected)
                    h=h.with_result(name,result,base['open_questions'])
                    for update in data['request_updates']:
                        state['messages'].append({'sender':name,'recipient':'recenzent','revision':label,'request':update['request_id'],
                            'reason':update['reason'],'data_sources':update['source_ids'],'status':'unconfirmed','claimed_status':update['status']})
                    state['messages'].append({'sender':name,'recipient':ORDER[ORDER.index(name)+1] if name!='recenzent' else 'orchestrator',
                        'revision':label,'request':f'{label}:{name}:handoff','reason':base['summary'],'data_sources':data['source_ids'],
                        'status':'validated_handoff','result_sha256':digest(result)})
                    partial['handoff']=h.to_dict();save()
                else:
                    review=h.results['recenzent']['engineering']
                    current=local_tasks(review,h.results['recenzent']['requests'],kb)
                    previous_tasks=state['tasks']
                    for old in previous_tasks:
                        if old['id']=='KB-CAPACITY' and not any(t['id']==old['id'] for t in current):
                            # Only this numeric catalogue criterion has a complete independent proof.
                            old={**old,'status':'resolved','resolution':'Idealna sila in dovoljen tlak ponovno preverjena; ne potrjuje vgradnje.',
                                 'evidence':{'revision':label,'catalogue':h.results['hidravlik']['engineering']['catalogue']}}
                        elif not any(t['id']==old['id'] for t in current):old={**old,'status':'unresolved','resolution':'Ni neodvisnega dokaza popravka; izginotje besedila ne zadošča.'}
                        else:continue
                        current.append(old)
                    if index:
                        for t in current:
                            if t['status']=='open':t['status']='unresolved'
                    partial['status']='completed';partial['handoff']=h.to_dict();state['revisions'].append(deepcopy(partial))
                    state['tasks']=current;state['messages']+=task_messages(current,label);pending=current
                    state.pop('partial_revision',None);save()
                    actionable=any(t['id']=='KB-CAPACITY' and t['status']=='open' for t in current)
                    # AI may request a supported force-reduction objective; never treat structural
                    # prose as a proof. Its next proposal is independently checked before application.
                    actionable |= any(t['target_agent']=='konstruktor' and t.get('objective')=='reduce_peak_force' and 'GEO-01' in t['source_ids'] for t in current)
                    if not actionable:state['stop_reason']='no_justified_next_change';break
                    continue
                break
            state['stop_reason']=state['stop_reason'] or 'knowledge_revision_limit_reached'
            if not state['revisions']:raise ValueError('Ni zaključenega razvojnega cikla.')
            state['status']='completed';save()
            from .reports import build_final_package
            archive=build_final_package(state,self.directory)
            state['package']=archive.name;save()
            return state
        except BaseException as exc:
            state['status']='stopped';state['stop_reason']=getattr(exc,'code','validation_or_budget_failure')
            if isinstance(exc,EngineeringError):
                state['validation_error']={'code':exc.code,'agent':name,'revision':label,
                                           'description':str(exc),'details':deepcopy(exc.details)}
            save();raise
        finally:
            if transport:transport.close()
