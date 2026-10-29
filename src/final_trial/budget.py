"""Conservative local reservations; not a provider billing cap. No automatic retries."""
from datetime import date
import math
from src.models.contracts import ORDER

PRICING={'model':'gpt-5.4-mini','input_per_million_USD':0.75,'output_per_million_USD':4.50,
         'source':'https://developers.openai.com/api/docs/models/gpt-5.4-mini','verified_on':'2026-10-29',
         'valid_until':'2026-11-05','basis':'Standard text API; no cache discount; no regional uplift or tax included.'}
LIMITS=dict(zip(ORDER,(3500,3500,4000,4500)))


class Budget:
    def __init__(self, *, model='gpt-5.4-mini', threshold=3.0, pricing=None, output_limits=None, max_input_tokens=100000, max_prompt_bytes=96000):
        if model!='gpt-5.4-mini':raise ValueError('Model ni dovoljen; brez samodejnega nadomestnega modela.')
        if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<threshold<=3:raise ValueError('Prag mora biti >0 in največ 3 USD.')
        self.pricing=dict(PRICING if pricing is None else pricing);self.model=model;self.threshold=threshold
        self.limits=dict(LIMITS if output_limits is None else output_limits)
        if set(self.limits)!=set(ORDER) or any(type(v)is not int or not 256<=v<=6000 for v in self.limits.values()):raise ValueError('Neveljavne izhodne omejitve.')
        if type(max_input_tokens)is not int or not 4096<=max_input_tokens<=100000 or type(max_prompt_bytes)is not int or not 4096<=max_prompt_bytes<=96000:raise ValueError('Neveljavna vhodna omejitev.')
        self.max_input_tokens=max_input_tokens;self.max_prompt_bytes=max_prompt_bytes;self.calls=[]

    def rates(self):
        p=self.pricing
        if not p or p.get('model')!=self.model or not p.get('source','').startswith('https://developers.openai.com/'):
            raise ValueError('Ni preverjenega cenika; plačljivi zagon je blokiran.')
        try:
            if not date.fromisoformat(p['verified_on'])<=date.today()<=date.fromisoformat(p['valid_until']):raise ValueError('Cenik potrebuje ponovno preverjanje.')
            rates=[p[k] for k in ('input_per_million_USD','output_per_million_USD')]
            if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in rates):raise ValueError('Neveljaven cenik.')
        except (KeyError,TypeError):raise ValueError('Nepopoln cenik.') from None
        return rates

    def estimate(self, input_tokens, output_tokens):
        a,b=self.rates();return (input_tokens*a+output_tokens*b)/1e6

    def preflight(self, max_revisions=2):
        try:
            total=sum(self.estimate(self.max_input_tokens,self.limits[n]) for n in ORDER)*max_revisions
            pricing_valid=True
        except ValueError:
            total=None;pricing_valid=False
        return {'model':self.model,'absolute_max_calls':16,'max_calls':min(16,max_revisions*4),'per_agent_call_limit':4,'max_revisions':max_revisions,
                'max_input_tokens_per_call':self.max_input_tokens,'max_prompt_bytes':self.max_prompt_bytes,'output_limits':self.limits,
                'maximum_input_tokens_estimate':self.max_input_tokens*4*max_revisions,'maximum_output_tokens':sum(self.limits.values())*max_revisions,
                'maximum_standard_cost_estimate_USD':total,'pricing_valid':pricing_valid,'threshold_USD':self.threshold,'pricing':self.pricing,
                'warning':'Lokalna konservativna ocena ni trda omejitev obračunavanja ponudnika. Reasoning je del izhodnih tokenov.'}

    def reserve(self, agent, prompt_bytes):
        if agent not in ORDER or len(self.calls)>=16 or sum(c['agent']==agent for c in self.calls)>=4:raise ValueError('Dosežena omejitev API-klicev.')
        # All serialized prompt parts + schema counted in bytes, with allowance for framing.
        conservative_input=prompt_bytes+2048
        if prompt_bytes>self.max_prompt_bytes or conservative_input>self.max_input_tokens:raise ValueError('Prevelik vhodni poziv; klic ni izveden.')
        reservation=self.estimate(self.max_input_tokens,self.limits[agent])
        accounted=sum(c.get('accounted_USD',c['reserved_USD']) for c in self.calls)
        if accounted+reservation>self.threshold:raise ValueError('Stroškovni prag bi bil presežen; klic ni izveden.')
        entry={'agent':agent,'model':self.model,'status':'reserved','reserved_USD':reservation,'input_tokens':None,'output_tokens':None,'reasoning_tokens':None,'estimated_cost_USD':None}
        self.calls.append(entry);return entry

    def finish(self, entry, metadata, *, failed=False):
        for k in ('input_tokens','output_tokens','reasoning_tokens'):entry[k]=metadata.get(k)
        entry['response_model']=metadata.get('model');entry['status']='failed' if failed else 'completed'
        known=all(type(entry[k])is int and entry[k]>=0 for k in ('input_tokens','output_tokens'))
        if known:
            # Missing/unknown response model blocks cost attribution and further calls.
            if metadata.get('model') not in (self.model,'gpt-5.4-mini-2026-03-17'):entry['status']='unpriced_model';return
            cost=self.estimate(entry['input_tokens'],entry['output_tokens']);entry['estimated_cost_USD']=cost
            entry['accounted_USD']=cost
        if not known:entry['status']='unknown_usage'

    def can_continue(self):
        return all(c['status']=='completed' and c['input_tokens']<=self.max_input_tokens and c['output_tokens']<=self.limits[c['agent']] for c in self.calls)

    def report(self):
        known=all(c['estimated_cost_USD'] is not None and c['status'] not in ('unpriced_model','unknown_usage','reserved') for c in self.calls)
        return {'model':self.model,'calls':self.calls,'call_count':len(self.calls),'per_agent':{n:{'calls':sum(c['agent']==n for c in self.calls),
                'input_tokens':sum(c['input_tokens'] or 0 for c in self.calls if c['agent']==n) if all(c['input_tokens'] is not None for c in self.calls if c['agent']==n) else None,
                'output_tokens':sum(c['output_tokens'] or 0 for c in self.calls if c['agent']==n) if all(c['output_tokens'] is not None for c in self.calls if c['agent']==n) else None,
                'estimated_cost_USD':sum(c['estimated_cost_USD'] for c in self.calls if c['agent']==n) if all(c['estimated_cost_USD'] is not None for c in self.calls if c['agent']==n) else None} for n in ORDER},
                'input_tokens':sum(c['input_tokens'] for c in self.calls) if all(c['input_tokens'] is not None for c in self.calls) else None,
                'output_tokens':sum(c['output_tokens'] for c in self.calls) if all(c['output_tokens'] is not None for c in self.calls) else None,
                'estimated_cost_USD':sum(c['estimated_cost_USD'] for c in self.calls) if known else None,
                'reserved_exposure_USD':sum(c['reserved_USD'] for c in self.calls),'pricing':self.pricing,'threshold_USD':self.threshold,
                'warning':'Ocena po objavljenem standardnem ceniku, ne račun ali trda finančna omejitev.'}
