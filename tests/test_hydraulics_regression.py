"""Replay the actual run 40890068418 response entirely offline, without normalizing it."""
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.models import Handoff
from src.models.contracts import ORDER, digest, validate_schema
from src.engineering.calculations import EngineeringError
from src.engineering.contracts import claims, validate_claims
from src.final_trial.agents import SimulatedResponder, schema, prompt, validate_response
from src.final_trial.engineering import geometry, hydraulic, economics, findings
from src.final_trial.runner import APPROVAL, Config, FinalRunner, preflight

ROOT=Path(__file__).resolve().parents[1]
FIXTURE=json.loads((ROOT/'tests/fixtures/hydraulics_run_40890068418.json').read_text(encoding='utf-8'))
SIM=Config(approval=APPROVAL['simulated'])


class HydraulicFailureRegressionTests(unittest.TestCase):
    def setUp(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):self.initial,self.kb,_,_=preflight(SIM)
        c=geometry(self.initial.inputs)
        self.handoff=self.initial.with_result('konstruktor',{'engineering':c})
        self.expected=hydraulic(self.initial.inputs,c,self.kb,FIXTURE['response']['selection'])

    def corrected_control(self):
        data=deepcopy(FIXTURE['response'])
        data['result']['calculations']=claims('hidravlik',self.expected)
        data['source_ids'].append('REV-03')
        return data

    def test_actual_fixture_reproduces_exact_cardinality_ids_and_undefined_zero_failure(self):
        data=deepcopy(FIXTURE['response'])
        self.assertEqual(digest(data),FIXTURE['provenance']['unvalidated_response_sha256'])
        with self.assertRaises(EngineeringError) as caught:
            validate_response(data,'hidravlik',self.handoff,self.kb,self.expected,[])
        error=caught.exception
        self.assertEqual(error.code,'engineering_validation_failed')
        self.assertEqual(error.details[0],{'path':'calculations','reason':'calculation_count_mismatch','expected_count':5,'received_count':9})
        self.assertEqual({r['expected_quantity'] for r in error.details if r['reason']=='missing_quantity'},
                         {'max_force_N','bore_160_bar_mm','bore_200_bar_mm','bore_250_bar_mm','bore_315_bar_mm'})
        unknown=[r for r in error.details if r['reason']=='quantity_undefined_without_lift_time_s']
        self.assertEqual({r['received_quantity'] for r in unknown},{'flow_L_min','hydraulic_power_kW'})
        self.assertTrue(all(r['received_value']==0 and r['expected_state']=='unknown' for r in unknown))
        for actual,expected in zip(data['result']['calculations'][:5],claims('hidravlik',self.expected)):
            self.assertAlmostEqual(actual['value'],expected['value']);self.assertEqual(actual['unit'],expected['unit'])
        self.assertEqual(data,FIXTURE['response'])  # production code never repairs the raw response

    def test_second_proven_failure_is_missing_rev03_source_not_catalogue_selection(self):
        data=deepcopy(FIXTURE['response']);data['result']['calculations']=claims('hidravlik',self.expected)
        with self.assertRaises(EngineeringError) as caught:validate_response(data,'hidravlik',self.handoff,self.kb,self.expected,[])
        self.assertEqual(caught.exception.details,[{'path':'source_ids','reason':'missing_required_source','expected_source':'REV-03'}])
        data['source_ids'].append('REV-03')
        validate_response(data,'hidravlik',self.handoff,self.kb,self.expected,[])
        cat=self.expected['catalogue']
        self.assertAlmostEqual(cat['ideal_capacity_N'],62344.90621048945)
        self.assertAlmostEqual(cat['peak_required_force_N'],64136.449795429005)
        self.assertAlmostEqual(self.expected['pressure_options'][1]['theoretical_bore_mm'],63.898773125335374)
        self.assertFalse(cat['nominal_force_pass']);self.assertTrue(cat['pressure_pass'])
        self.assertFalse(cat['installation_verified']);self.assertIsNone(self.expected['flow_L_min']);self.assertIsNone(self.expected['hydraulic_power_kW'])
        e=economics(self.handoff.inputs,self.handoff.results['konstruktor']['engineering'],self.expected,self.kb)
        r=findings(self.handoff.inputs,self.handoff.results['konstruktor']['engineering'],self.expected,e,self.kb)
        self.assertIn('KB-CAPACITY',[f['id'] for f in r['findings']]);self.assertEqual(r['status'],'changes_required');self.assertFalse(r['engineering_verified'])

    def test_provider_schema_and_prompt_require_exact_ids_units_list_and_sources(self):
        good=self.corrected_control();contract=schema(self.kb,self.expected,'hidravlik')
        validate_schema(good,contract)
        alias=deepcopy(good);alias['result']['calculations'][0]['quantity']='peak_required_force'
        missing=deepcopy(good);missing['result']['calculations'].pop()
        for changed in (deepcopy(FIXTURE['response']),alias,missing):
            with self.assertRaises(ValueError):validate_schema(changed,contract)
        bad=deepcopy(good);bad['result']['calculations'][0]['unit']='kN'
        with self.assertRaises(ValueError):validate_schema(bad,contract)
        instructions,payload=prompt('hidravlik',self.handoff,self.kb,self.expected,[],[])
        body=json.loads(payload)
        self.assertEqual(body['required_source_ids'],['REV-03'])
        self.assertEqual(body['required_calculations'],claims('hidravlik',self.expected))
        self.assertIn('NI PODATKA',instructions);self.assertIn('max_force_N',instructions);self.assertIn('REV-03',instructions)

    def test_duplicate_wrong_numbers_units_and_undefined_zero_still_rejected(self):
        good=self.corrected_control()
        mutations=[lambda d:d['result']['calculations'].__setitem__(1,deepcopy(d['result']['calculations'][0])),
                   lambda d:d['result']['calculations'][0].update(value=0),
                   lambda d:d['result']['calculations'][0].update(unit='kN'),
                   lambda d:d['result']['calculations'].append({'quantity':'flow_L_min','value':0,'unit':'L/min'}),
                   lambda d:d['result']['calculations'].append({'quantity':'hydraulic_power_kW','value':0,'unit':'kW'})]
        for mutation in mutations:
            data=deepcopy(good);mutation(data)
            with self.subTest(mutation=mutation),self.assertRaises(EngineeringError):validate_response(data,'hidravlik',self.handoff,self.kb,self.expected,[])

    def test_known_time_retains_real_flow_and_power_requirements(self):
        inputs={**self.initial.inputs,'lift_time_s':30};c=geometry(inputs)
        h=hydraulic(inputs,c,self.kb,FIXTURE['response']['selection']);rows=claims('hidravlik',h)
        self.assertEqual(len(rows),7)
        self.assertGreater(next(r['value'] for r in rows if r['quantity']=='max_flow_L_min'),0)
        self.assertGreater(next(r['value'] for r in rows if r['quantity']=='max_hydraulic_power_kW'),0)
        validate_claims('hidravlik',{'calculations':rows,'cost_items':[]},h)
        for row in rows:
            if row['quantity']=='max_flow_L_min':row['value']=0
        with self.assertRaises(EngineeringError):validate_claims('hidravlik',{'calculations':rows,'cost_items':[]},h)

    def test_controlled_corrected_fixture_completes_free_cycle_but_does_not_certify(self):
        corrected=self.corrected_control()
        class Control(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                if name=='hidravlik' and h.revision=='R01':return deepcopy(corrected)
                return super().request(name,h,kb,expected,requests)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):
            state=FinalRunner(d,SIM,responder=Control()).run()
            self.assertEqual(len(state['revisions']),2);self.assertEqual(state['api_usage']['call_count'],0)
            self.assertTrue((Path(d)/state['package']).is_file())
            first=state['revisions'][0]['handoff']['results']['hidravlik']['engineering']
            self.assertIsNone(first['flow_L_min']);self.assertIsNone(first['hydraulic_power_kW'])
            self.assertEqual(state['revisions'][-1]['handoff']['results']['recenzent']['decision'],'changes_required')
            self.assertFalse(state['engineering_verified'])

    def test_sdk_replay_stops_after_second_intercepted_request_and_keeps_original_cost_and_diagnostics(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:self.skipTest('Optional [ai] dependency not installed')
        seen=[]
        def handler(request):
            payload=json.loads(request.content);incoming=json.loads(payload['input']);name=incoming['agent'];seen.append(name)
            if name=='hidravlik':data=deepcopy(FIXTURE['response'])
            else:data=SimulatedResponder().request(name,Handoff(**incoming['handoff']),incoming['knowledge_base'],incoming['deterministic_reference'],incoming['received_requests'])
            usage=FIXTURE['observed_usage']['per_agent'][name]
            return httpx.Response(200,json={'id':'resp_offline_replay','object':'response','created_at':0,'status':'completed','model':'gpt-5.4-mini-2026-03-17',
                'output':[{'type':'message','id':'msg','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps(data),'annotations':[]}]}],
                'usage':{'input_tokens':usage['input_tokens'],'output_tokens':usage['output_tokens'],'total_tokens':usage['input_tokens']+usage['output_tokens'],'output_tokens_details':{'reasoning_tokens':0}}})
        client=OpenAI(api_key='offline-placeholder',max_retries=0,http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        class FrozenDate(date):
            @classmethod
            def today(cls):return date(2026,10,29)
        env={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main','GITHUB_RUN_ATTEMPT':'1','OPENAI_API_KEY':'offline-placeholder'}
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,env),patch('openai.OpenAI',return_value=client),patch('src.final_trial.budget.date',FrozenDate):
            with self.assertRaises(EngineeringError):FinalRunner(d,Config(mode='openai',approval=APPROVAL['openai'])).run()
            state=json.loads((Path(d)/'trial.json').read_text())
            self.assertEqual(seen,['konstruktor','hidravlik']);self.assertEqual(state['api_usage']['call_count'],2)
            self.assertAlmostEqual(state['api_usage']['estimated_cost_USD'],.03977025)
            self.assertEqual(state['api_usage']['input_tokens'],40451);self.assertEqual(state['api_usage']['output_tokens'],2096)
            self.assertEqual(state['stop_reason'],'engineering_validation_failed')
            self.assertEqual(state['validation_error']['agent'],'hidravlik');self.assertEqual(state['validation_error']['revision'],'R01')
            self.assertEqual(state['validation_error']['details'][0]['received_count'],9)
            self.assertEqual(state['partial_revision']['unvalidated_response'],FIXTURE['response'])
            self.assertFalse(list(Path(d).glob('*.zip')))
