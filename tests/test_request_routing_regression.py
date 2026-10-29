"""Actual request-routing failure replay; no API access."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.models.contracts import ORDER, digest, validate_schema
from src.engineering.calculations import EngineeringError
from src.final_trial.runner import Config, APPROVAL, FinalRunner, preflight
from src.final_trial.agents import schema, prompt, validate_response, SimulatedResponder
from src.final_trial.engineering import geometry, hydraulic, economics, findings

FIXTURE=json.loads(Path(__file__).with_name('fixtures').joinpath('hydraulics_run_40896534950.json').read_text(encoding='utf-8'))
SIM=Config(approval=APPROVAL['simulated'])


class RequestRoutingRegressionTests(unittest.TestCase):
    def setUp(self):
        self.h,self.kb,_,_=preflight(SIM)
        self.h=self.h.with_result('konstruktor',{'engineering':geometry(self.h.inputs)})
        self.expected=hydraulic(self.h.inputs,self.h.results['konstruktor']['engineering'],self.kb,FIXTURE['response']['selection'])

    def test_actual_request_updates_are_undelivered_not_invalid_calculations(self):
        raw=deepcopy(FIXTURE['response'])
        self.assertEqual(digest(raw),FIXTURE['provenance']['response_sha256'])
        with self.assertRaises(EngineeringError) as caught:validate_response(raw,'hidravlik',self.h,self.kb,self.expected,[])
        self.assertEqual(len(caught.exception.details),4)
        self.assertTrue(all(d['reason']=='undelivered_request' and d['allowed_request_ids']==[] for d in caught.exception.details))
        self.assertEqual(caught.exception.details[0]['path'],'request_updates[0].request_id')
        raw['request_updates']=[]
        validate_response(raw,'hidravlik',self.h,self.kb,self.expected,[])
        self.assertIsNone(self.expected['flow_L_min']);self.assertFalse(self.expected['catalogue']['nominal_force_pass'])

    def test_schema_forbids_updates_in_r01_and_binds_later_ids_to_recipient(self):
        raw=deepcopy(FIXTURE['response']);contract=schema(self.kb,self.expected,'hidravlik',handoff=self.h)
        self.assertEqual(contract['properties']['request_updates']['maxItems'],0)
        with self.assertRaises(ValueError):validate_schema(raw,contract)
        raw['request_updates']=[];validate_schema(raw,contract)
        tasks=[{'id':'KB-CAPACITY','target_agent':'hidravlik'}, {'id':'GEO-TASK','target_agent':'konstruktor'}]
        bound=schema(self.kb,self.expected,'hidravlik',requests=tasks,handoff=self.h)
        self.assertEqual(bound['properties']['request_updates']['items']['properties']['request_id']['enum'],['KB-CAPACITY'])
        update=deepcopy(FIXTURE['response']['request_updates'][0]);raw['request_updates']=[update]
        with self.assertRaises(ValueError):validate_schema(raw,bound)
        raw['request_updates'][0]['request_id']='KB-CAPACITY';validate_schema(raw,bound)
        validate_response(raw,'hidravlik',self.h,self.kb,self.expected,tasks)
        raw['request_updates'][0]['request_id']='GEO-TASK'
        with self.assertRaises(EngineeringError):validate_response(raw,'hidravlik',self.h,self.kb,self.expected,tasks)

    def test_contract_binds_all_roles_identity_decisions_and_r01_empty_arrays(self):
        h,kb,_,_=preflight(SIM)
        for name in ORDER:
            if name=='konstruktor':expected=geometry(h.inputs)
            elif name=='hidravlik':expected=hydraulic(h.inputs,h.results['konstruktor']['engineering'],kb,{'cylinder_id':'HYD-01','pump_id':'HYD-05','pressure_bar':200})
            elif name=='ekonomist':expected=economics(h.inputs,h.results['konstruktor']['engineering'],h.results['hidravlik']['engineering'],kb)
            else:expected=findings(h.inputs,*(h.results[n]['engineering'] for n in ORDER[:3]),kb)
            contract=schema(kb,expected,name,handoff=h)
            self.assertEqual(contract['properties']['request_updates']['maxItems'],0)
            data=SimulatedResponder().request(name,h,kb,expected,[]);validate_schema(data,contract)
            wrong=deepcopy(data);wrong['result']['agent']=ORDER[(ORDER.index(name)+1)%4]
            with self.assertRaises(ValueError):validate_schema(wrong,contract)
            if name!='recenzent':self.assertEqual(contract['properties']['requests']['maxItems'],0)
            if name=='konstruktor':self.assertEqual(contract['properties']['proposal'],{'type':'null'})
            h=h.with_result(name,{'engineering':expected})

    def test_prompt_separates_knowledge_sources_from_issued_tasks(self):
        instructions,payload=prompt('hidravlik',self.h,self.kb,self.expected,[],[])
        self.assertEqual(json.loads(payload)['allowed_request_update_ids'],[])
        self.assertIn('request_updates=[]',instructions)
        self.assertIn('ID iz baze znanja',instructions)

    def test_saved_bad_response_stops_without_silent_deletion_or_package(self):
        class Replay(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                if name=='hidravlik':return deepcopy(FIXTURE['response'])
                return super().request(name,h,kb,expected,requests)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(EngineeringError):FinalRunner(d,SIM,responder=Replay()).run()
            state=json.loads(Path(d,'trial.json').read_text())
            self.assertEqual(state['validation_error']['agent'],'hidravlik')
            self.assertEqual(state['validation_error']['details'][0]['reason'],'undelivered_request')
            self.assertEqual(state['partial_revision']['unvalidated_response'],FIXTURE['response'])
            self.assertEqual(state['api_usage']['call_count'],0);self.assertFalse(list(Path(d).glob('*.zip')))
