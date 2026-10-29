"""Preserve explicit nested citations and mathematically filter nominal choices."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.models.contracts import digest, validate_schema
from src.engineering.calculations import EngineeringError
from src.final_trial.runner import Config,APPROVAL,preflight,FinalRunner
from src.final_trial.agents import cited_sources,validate_response,schema,SimulatedResponder
from src.final_trial.engineering import geometry,hydraulic,economics,findings,eligible_hydraulic_choices
from src.final_trial.reports import validate

FIXTURE=json.loads(Path(__file__).with_name('fixtures').joinpath('reviewer_run_40899065304.json').read_text(encoding='utf-8'))
SIM=Config(approval=APPROVAL['simulated'])


class CitationManifestTests(unittest.TestCase):
    def setUp(self):
        self.h,self.kb,_,_=preflight(SIM)
        c=geometry(self.h.inputs);h=hydraulic(self.h.inputs,c,self.kb,{'cylinder_id':'HYD-01','pump_id':'HYD-05','pressure_bar':200});e=economics(self.h.inputs,c,h,self.kb)
        for name,data in zip(('konstruktor','hidravlik','ekonomist'),(c,h,e)):self.h=self.h.with_result(name,{'engineering':data})
        self.expected=findings(self.h.inputs,c,h,e,self.kb)

    def test_actual_review_retains_nested_rev06_without_inventing_or_editing_citations(self):
        raw=deepcopy(FIXTURE['response']);before=deepcopy(raw)
        self.assertEqual(digest(raw),FIXTURE['provenance']['response_sha256'])
        self.assertNotIn('REV-06',raw['source_ids'])
        self.assertEqual(cited_sources(raw)['REV-06'],['requests[2].source_ids'])
        validate_response(raw,'recenzent',self.h,self.kb,self.expected,[])
        self.assertEqual(raw,before)
        self.assertEqual(set(cited_sources(raw)),set(raw['source_ids'])|{s for r in raw['requests'] for s in r['source_ids']})

    def test_absent_mandatory_source_and_unknown_nested_source_still_fail(self):
        raw=deepcopy(FIXTURE['response'])
        raw['source_ids'].remove('REV-03')
        for item in raw['requests']:item['source_ids']=[s for s in item['source_ids'] if s!='REV-03']
        with self.assertRaises(EngineeringError) as caught:validate_response(raw,'recenzent',self.h,self.kb,self.expected,[])
        self.assertEqual(caught.exception.details,[{'path':'source_ids','reason':'missing_required_source','expected_source':'REV-03'}])
        raw=deepcopy(FIXTURE['response']);raw['requests'][0]['source_ids'].append('INVENTED')
        with self.assertRaises(ValueError):validate_response(raw,'recenzent',self.h,self.kb,self.expected,[])

    def test_provider_nominal_choices_exclude_c63_but_do_not_certify_installation(self):
        c=self.h.results['konstruktor']['engineering'];expected=self.h.results['hidravlik']['engineering']
        options=eligible_hydraulic_choices(self.kb,c['peak_cylinder_force_N'])
        self.assertTrue(options);self.assertNotIn({'cylinder_id':'HYD-01','pump_id':'HYD-05','pressure_bar':200},options)
        self.assertIn({'cylinder_id':'HYD-02','pump_id':'HYD-05','pressure_bar':200},options)
        for option in options:
            cat=hydraulic(self.h.inputs,c,self.kb,option)['catalogue']
            self.assertTrue(cat['nominal_force_pass'] and cat['pressure_pass']);self.assertFalse(cat['installation_verified'])
        raw=SimulatedResponder().request('hidravlik',self.h,self.kb,expected,[])
        contract=schema(self.kb,expected,'hidravlik',handoff=self.h,eligible_choices=options)
        with self.assertRaises(ValueError):validate_schema(raw,contract)
        raw['selection']=options[0];raw['source_ids'].append(options[0]['cylinder_id']);validate_schema(raw,contract)
        self.assertEqual(eligible_hydraulic_choices(self.kb,1e12),[])

    def test_export_retains_original_manifest_and_validates_derived_citation_locations(self):
        class Replay(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                if name=='recenzent' and h.revision=='R01':return deepcopy(FIXTURE['response'])
                return super().request(name,h,kb,expected,requests)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):
            state=FinalRunner(d,SIM,responder=Replay()).run();validate(state)
            result=state['revisions'][0]['handoff']['results']['recenzent']
            self.assertNotIn('REV-06',result['declared_source_ids']);self.assertIn('REV-06',result['effective_source_ids'])
            self.assertEqual(result['citation_locations']['REV-06'],['requests[2].source_ids'])
            self.assertEqual(state['api_usage']['call_count'],0);self.assertFalse(state['engineering_verified'])
            result['effective_source_ids'].append('INVENTED')
            with self.assertRaises(ValueError):validate(state)
