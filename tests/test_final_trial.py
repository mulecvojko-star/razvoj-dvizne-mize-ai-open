"""Final trial regression tests. All API/HTTP responses are intercepted fixtures."""
from datetime import date as RealDate
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from src.models import Handoff
from src.models.contracts import ORDER
from src.final_trial.knowledge import load_knowledge, NS
from src.final_trial.budget import Budget, PRICING
from src.final_trial.engineering import apply_geometry, geometry
from src.final_trial.agents import SimulatedResponder, FinalTransport
from src.final_trial.runner import APPROVAL, Config, FinalRunner, preflight
from src.final_trial.reports import FILES, build_final_package, validate

class FrozenDate(RealDate):
    @classmethod
    def today(cls):return RealDate(2026,10,29)


# Offline pricing arithmetic is tested at the recorded verification date,
# independent of the date CI happens to execute. Runtime expiry remains enforced.
_clock_patch=None

def setUpModule():
    global _clock_patch
    _clock_patch=patch('src.final_trial.budget.date',FrozenDate);_clock_patch.start()

def tearDownModule():_clock_patch.stop()


ROOT=Path(__file__).resolve().parents[1]
KB=ROOT/'knowledge_base/Testna_baza_znanja_V01.docx'
SIM=Config(approval=APPROVAL['simulated'])
PAID=replace(SIM,mode='openai',approval=APPROVAL['openai'])
ENV={'GITHUB_ACTIONS':'true','GITHUB_EVENT_NAME':'workflow_dispatch','GITHUB_REF':'refs/heads/main','GITHUB_RUN_ATTEMPT':'1'}


def edited_docx(destination, transform):
    with ZipFile(KB) as original,ZipFile(destination,'w') as changed:
        for name in original.namelist():
            value=original.read(name)
            if name=='word/document.xml':value=transform(value)
            changed.writestr(name,value)


class KnowledgeTests(unittest.TestCase):
    def setUp(self):self.initial,self.kb,_,_=preflight(SIM)

    def test_all_paragraphs_rows_sources_and_classes(self):
        kb=self.kb
        self.assertTrue(kb['compatible']);self.assertEqual(len(kb['records']),51)
        with ZipFile(KB) as z:
            body=ET.fromstring(z.read('word/document.xml')).find('w:body',NS)
        self.assertEqual(sum(b['type']=='table' for b in kb['blocks']),len(body.findall('w:tbl',NS)))
        self.assertEqual(sum(b['type']=='paragraph' for b in kb['blocks']),len(body.findall('w:p',NS)))
        for identifier,row in kb['records'].items():
            self.assertIn('section',row['source']);self.assertEqual(row['source']['document_sha256'],kb['sha256'])
            if not identifier.startswith('TEST'):self.assertGreater(row['source']['row'],1)
        self.assertEqual(kb['records']['REQ-01']['classification'],'fixed_requirement')
        self.assertEqual(kb['records']['GEO-01']['classification'],'variable_parameter')
        self.assertEqual(kb['records']['REQ-04']['classification'],'calculated_result')
        self.assertEqual(kb['records']['COST-10']['classification'],'incomplete')
        self.assertEqual(kb['prices']['COST-04']['amount_EUR'],245)
        self.assertIsNone(kb['prices']['COST-10']['amount_EUR'])
        self.assertEqual(len(kb['conflicts']),2);self.assertEqual(kb['max_revisions'],2)

    def test_missing_corrupt_and_duplicate_ids_stop(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'missing.docx'
            with self.assertRaisesRegex(ValueError,'Manjka Wordova'):load_knowledge(p,self.initial.inputs)
            p.write_text('not a DOCX')
            with self.assertRaisesRegex(ValueError,'ni berljiv'):load_knowledge(p,self.initial.inputs)
            edited_docx(p,lambda raw:raw.replace(b'REQ-02',b'REQ-01'))
            with self.assertRaisesRegex(ValueError,'Podvojen'):load_knowledge(p,self.initial.inputs)

    def test_conflicting_fixed_requirement_is_documented_without_mutation(self):
        before=deepcopy(self.initial.inputs)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'conflict.docx';edited_docx(p,lambda raw:raw.replace(b'300 kg',b'301 kg'))
            kb=load_knowledge(p,self.initial.inputs)
            self.assertFalse(kb['compatible']);self.assertEqual(kb['conflicts'][0]['field'],'payload_kg')
            factory=Mock()
            with self.assertRaises(ValueError):FinalRunner(Path(d)/'out',SIM,kb_path=p,transport_factory=factory).run()
            factory.assert_not_called();self.assertEqual(self.initial.inputs,before)
            state=json.loads((Path(d)/'out/trial.json').read_text());self.assertEqual(state['status'],'stopped')
            self.assertFalse(list((Path(d)/'out').glob('*.zip')))


class BudgetTests(unittest.TestCase):
    def test_token_limits_cost_reservations_and_hard_counters(self):
        b=Budget();estimate=b.preflight(2)
        self.assertEqual(estimate['maximum_output_tokens'],31000)
        self.assertEqual(estimate['maximum_input_tokens_estimate'],800000)
        self.assertAlmostEqual(estimate['maximum_standard_cost_estimate_USD'],.7395)
        for _ in range(4):
            for name in ORDER:
                entry=b.reserve(name,1000);b.finish(entry,{'model':b.model,'input_tokens':1000,'output_tokens':100,'reasoning_tokens':20})
        self.assertEqual(len(b.calls),16);self.assertTrue(b.can_continue())
        for name in ORDER:
            with self.assertRaises(ValueError):b.reserve(name,1000)
        self.assertAlmostEqual(b.report()['estimated_cost_USD'],.0192)
        single=Budget()
        for _ in range(4):single.reserve('konstruktor',100)
        with self.assertRaises(ValueError):single.reserve('konstruktor',100)
        with self.assertRaises(ValueError):Budget().reserve('konstruktor',96001)
        with self.assertRaises(ValueError):Budget(threshold=.001).reserve('konstruktor',100)

    def test_missing_usage_unpriced_model_stale_price_stop_not_fake_zero(self):
        for meta in ({'model':'gpt-5.4-mini'},{'model':'unknown','input_tokens':100,'output_tokens':100}):
            b=Budget();e=b.reserve('konstruktor',100);b.finish(e,meta)
            self.assertFalse(b.can_continue());self.assertIsNone(b.report()['estimated_cost_USD'])
            self.assertGreater(b.report()['reserved_exposure_USD'],0)
        b=Budget(pricing={});self.assertFalse(b.preflight()['pricing_valid'])
        with self.assertRaises(ValueError):b.reserve('konstruktor',100)
        stale={**PRICING,'valid_until':'2000-01-01'}
        self.assertFalse(Budget(pricing=stale).preflight()['pricing_valid'])
        class FutureDate(RealDate):
            @classmethod
            def today(cls):return RealDate(2026,11,6)
        with patch('src.final_trial.budget.date',FutureDate):
            self.assertFalse(Budget().preflight()['pricing_valid'])
            with tempfile.TemporaryDirectory() as d:
                self.assertEqual(FinalRunner(d,SIM).run()['api_usage']['call_count'],0)
            factory=Mock()
            with patch.dict(os.environ,ENV),tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):FinalRunner(d,PAID,transport_factory=factory).run()
                factory.assert_not_called()
        for kwargs in ({'threshold':float('nan')},{'threshold':4},{'max_input_tokens':True},{'output_limits':{}},{'model':'other'}):
            with self.assertRaises(ValueError):Budget(**kwargs)


class FinalRunTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        cls.state=FinalRunner(cls.root,SIM).run()
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_complete_two_revision_communication_routing_and_numerical_correction(self):
        s=self.state
        self.assertEqual([r['label'] for r in s['revisions']],['V01-R01','V01-R02'])
        self.assertEqual(s['api_usage']['call_count'],0)
        self.assertEqual([r['handoff']['inputs'] for r in s['revisions']],[s['source_requirements']]*2)
        self.assertEqual(len(s['changes']),1);self.assertEqual(s['changes'][0]['parameter'],'hydraulic_selection')
        resolved=[t for t in s['tasks'] if t['status']=='resolved'];self.assertEqual([t['id'] for t in resolved],['KB-CAPACITY'])
        self.assertTrue(all(t['status']!='resolved' for t in s['tasks'] if t['id'].startswith('REV-')))
        self.assertFalse(s['engineering_verified'])
        for m in s['messages']:
            self.assertTrue({'sender','recipient','revision','request','reason','data_sources','status'}<=set(m))
        self.assertTrue(any(m['recipient']=='hidravlik' and m['request']=='KB-CAPACITY' for m in s['messages']))
        for record in s['revisions']:
            for agent in record['handoff']['results'].values():
                self.assertLess(agent['trace']['prompt_bytes'],96000)
                self.assertEqual(agent['trace']['knowledge_sha256'],s['knowledge']['sha256'])
        first,second=[r['handoff']['results'] for r in s['revisions']]
        self.assertEqual(first['konstruktor']['engineering'],second['konstruktor']['engineering'])
        self.assertEqual(first['ekonomist']['engineering']['synthetic_subtotal_EUR'],1390)
        self.assertEqual(second['ekonomist']['engineering']['synthetic_subtotal_EUR'],1425)
        self.assertIsNone(second['ekonomist']['engineering']['total_EUR'])

    def test_geometry_proposal_is_recalculated_and_forwarded_not_taken_from_model_text(self):
        class Propose(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                data=super().request(name,h,kb,expected,requests)
                if name=='recenzent' and h.revision=='R01':
                    data['requests'].append({'id':'FORCE','target_agent':'konstruktor','reason':'Preuči manjšo idealno silo pri dovoljenem vpetju.',
                        'source_ids':['GEO-01'],'correction':'Predlagaj preverljivo zmanjšanje sile.','objective':'reduce_peak_force'})
                    data['source_ids'].append('GEO-01')
                if name=='konstruktor' and h.revision=='R02':
                    task=next(r for r in requests if r.get('original_id')=='FORCE')
                    data['proposal']={'parameter':'cylinder_base_x_mm','new_value':300,'request_id':task['id'],
                        'reason':'Ponovni izračun omogoča zmanjšanje idealne sile.','objective':'reduce_peak_force','source_ids':['GEO-01']}
                return data
        with tempfile.TemporaryDirectory() as d:
            state=FinalRunner(d,SIM,responder=Propose()).run()
            validate(state)
            a,b=[r['handoff'] for r in state['revisions']]
            self.assertEqual(b['inputs']['cylinder_base_x_mm'],300)
            c=b['results']['konstruktor']
            self.assertNotEqual(c['pre_change_model_calculations'],c['calculations'])
            self.assertLess(c['engineering']['peak_cylinder_force_N'],a['results']['konstruktor']['engineering']['peak_cylinder_force_N'])
            self.assertEqual(b['results']['hidravlik']['engineering']['max_force_N'],c['engineering']['peak_cylinder_force_N'])
            self.assertEqual(b['inputs']['payload_kg'],300)
            self.assertEqual(len(state['changes']),2)

    def test_no_manufactured_revision_when_first_selection_already_nominally_adequate(self):
        class Adequate(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                data=super().request(name,h,kb,expected,requests)
                if name=='hidravlik':data['selection']['cylinder_id']='HYD-02';data['source_ids'][0]='HYD-02'
                return data
        with tempfile.TemporaryDirectory() as d:
            s=FinalRunner(d,SIM,responder=Adequate()).run()
            self.assertEqual(len(s['revisions']),1);self.assertEqual(s['stop_reason'],'no_justified_next_change')
            self.assertFalse(s['changes'])
            self.assertTrue((Path(d)/s['package']).exists())

    def test_stop_invalid_json_numeric_units_sources_and_fake_prices_preserve_diagnostics(self):
        variants=[('unit',lambda data:data['result']['calculations'][0].update(unit='kN')),
                  ('number',lambda data:data['result']['calculations'].pop()),
                  ('source',lambda data:data.update(source_ids=['NOT-A-SOURCE'])),
                  ('identity',lambda data:data['result'].update(revision='R99'))]
        for label,change in variants:
            class Bad(SimulatedResponder):
                def request(self,name,h,kb,expected,requests):
                    data=super().request(name,h,kb,expected,requests)
                    if name=='konstruktor':change(data)
                    return data
            with self.subTest(label=label),tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):FinalRunner(d,SIM,responder=Bad()).run()
                state=json.loads((Path(d)/'trial.json').read_text())
                self.assertEqual(state['status'],'stopped');self.assertIn('unvalidated_response',state['partial_revision'])
                self.assertFalse(list(Path(d).glob('*.zip')))
        class BadPrice(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                data=super().request(name,h,kb,expected,requests)
                if name=='ekonomist':data['result']['cost_items'][0]['price_kind']='verified'
                return data
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):FinalRunner(d,SIM,responder=BadPrice()).run()

    def test_second_revision_failure_keeps_first_source_but_no_complete_package(self):
        class FailSecond(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                data=super().request(name,h,kb,expected,requests)
                if name=='ekonomist' and h.revision=='R02':data['result']['cost_items'][0]['amount_EUR']=0
                return data
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):FinalRunner(d,SIM,responder=FailSecond()).run()
            state=json.loads((Path(d)/'trial.json').read_text())
            self.assertEqual(state['status'],'stopped');self.assertEqual(len(state['revisions']),1)
            self.assertEqual(state['revisions'][0]['label'],'V01-R01')
            self.assertFalse(list(Path(d).glob('*.zip')))
            self.assertEqual(state['partial_revision']['label'],'V01-R02')

    def test_fixed_or_derived_edit_rejected_and_real_geometry_objective_recomputed(self):
        initial,kb,_,_=preflight(SIM)
        task={'id':'FORCE','target_agent':'konstruktor','objective':'reduce_peak_force','source_ids':['GEO-01']}
        p={'parameter':'payload_kg','new_value':100,'request_id':'FORCE','reason':'test','source_ids':['GEO-01'],'objective':'reduce_peak_force'}
        for key in ('payload_kg','max_height_mm','cylinder_force_N','mechanical_efficiency'):
            with self.subTest(key=key),self.assertRaises(ValueError):apply_geometry(initial.inputs,{**p,'parameter':key},[task],kb)
        changed,decision=apply_geometry(initial.inputs,{**p,'parameter':'cylinder_base_x_mm','new_value':300},[task],kb)
        self.assertEqual(decision['status'],'applied');self.assertLess(geometry(changed)['peak_cylinder_force_N'],geometry(initial.inputs)['peak_cylinder_force_N'])
        changed,decision=apply_geometry(initial.inputs,{**p,'parameter':'cylinder_base_x_mm','new_value':200},[task],kb)
        self.assertEqual(decision['status'],'not_applied');self.assertEqual(changed,initial.inputs)

    def test_replay_stop_approval_and_paid_local_guards(self):
        with self.assertRaises(FileExistsError):FinalRunner(self.root,SIM).run()
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'STOP').touch()
            with self.assertRaises(ValueError):FinalRunner(d,SIM).run()
            self.assertFalse(list(Path(d).glob('*.zip')))
        factory=Mock()
        for cfg,env in [(replace(SIM,approval=''),{}),(PAID,{'GITHUB_ACTIONS':'false'}),(PAID,{**ENV,'GITHUB_RUN_ATTEMPT':'2'}),(PAID,{**ENV,'GITHUB_REF':'refs/heads/dev'})]:
            with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,env),self.assertRaises(ValueError):FinalRunner(d,cfg,transport_factory=factory).run()
        factory.assert_not_called()

    def test_final_ten_files_pdf_excel_formulas_and_offline_reexport(self):
        import fitz
        from pypdf import PdfReader
        from openpyxl import load_workbook
        with ZipFile(self.root/self.state['package']) as z:
            self.assertEqual(set(z.namelist()),set(FILES));self.assertIsNone(z.testzip())
            for name in FILES:
                if not name.endswith('.pdf'):continue
                pdf=PdfReader(BytesIO(z.read(name)),strict=True)
                text='\n'.join(p.extract_text() for p in pdf.pages)
                self.assertIn('engineering_verified=false',text)
                self.assertTrue(any(c in text for c in 'čšž'))
                with fitz.open(stream=z.read(name),filetype='pdf') as document:
                    for page in document:
                        self.assertAlmostEqual(page.rect.width,595.276,places=1)
                        spans=[s for b in page.get_text('dict')['blocks'] if 'lines'in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
                        for i,span in enumerate(spans):
                            self.assertTrue(page.rect.contains(fitz.Rect(span['bbox'])),(name,span['text']))
                            for other in spans[i+1:]:self.assertLessEqual((fitz.Rect(span['bbox'])&fitz.Rect(other['bbox'])).get_area(),3,(name,span['text'],other['text']))
            workbook=load_workbook(BytesIO(z.read('03_Ekonomist.xlsx')),data_only=False)
            self.assertEqual(workbook['R02 Kosovnica']['E3'].value,'=IF(AND(ISNUMBER(C3),ISNUMBER(D3)),ROUND(C3*D3,2),"")')
            self.assertIsNone(workbook['R02 Kosovnica']['D8'].value)
            self.assertEqual(workbook['R02 Kosovnica']['F8'].value,'NEZNANO')
            self.assertEqual(workbook['R02 Kosovnica']['F3'].value,'SINTETIČNO')
            source=json.loads(z.read('08_Izvorni_podatki.json'));self.assertEqual(len(source['revisions']),2)
            self.assertEqual(json.loads(z.read('09_API_poraba.json'))['call_count'],0)
        with tempfile.TemporaryDirectory() as d,patch('src.final_trial.runner.FinalTransport',side_effect=AssertionError('No API')):
            self.assertTrue(build_final_package(self.state,d).is_file())
        for mutate in (lambda s:s.update(engineering_verified=True),lambda s:s['revisions'][0]['handoff']['inputs'].update(payload_kg=299),
                       lambda s:s['tasks'][0].update(status='resolved')):
            invalid=deepcopy(self.state);mutate(invalid)
            with self.assertRaises(ValueError):validate(invalid)


class OfflineFinalSDKTests(unittest.TestCase):
    def setUp(self):
        try:
            import httpx
            from openai import OpenAI
        except ImportError:self.skipTest('Optional [ai] dependency not installed')
        self.httpx=httpx;self.OpenAI=OpenAI;self.seen=[]

    def handler(self,request,mutation=None):
        payload=json.loads(request.content);self.seen.append(payload)
        incoming=json.loads(payload['input']);name=incoming['agent'];h=Handoff(**incoming['handoff'])
        self.assertEqual(payload['model'],'gpt-5.4-mini');self.assertEqual(payload['reasoning'],{'effort':'none'})
        self.assertFalse(payload['store']);self.assertEqual(payload['text']['format']['type'],'json_schema')
        data=SimulatedResponder().request(name,h,incoming['knowledge_base'],incoming['deterministic_reference'],incoming['received_requests'])
        body={'id':'resp_offline','object':'response','created_at':0,'status':'completed','model':'gpt-5.4-mini-2026-03-17',
              'output':[{'type':'message','id':'msg','role':'assistant','status':'completed','content':[{'type':'output_text','text':json.dumps(data),'annotations':[]}]}],
              'usage':{'input_tokens':1200,'output_tokens':300,'total_tokens':1500,'output_tokens_details':{'reasoning_tokens':0}}}
        if mutation:mutation(body)
        return self.httpx.Response(200,json=body)

    def run_intercepted(self,directory,handle,config=PAID):
        client=self.OpenAI(api_key='offline-placeholder',max_retries=0,http_client=self.httpx.Client(transport=self.httpx.MockTransport(handle)))
        with patch.dict(os.environ,{**ENV,'OPENAI_API_KEY':'offline-placeholder'}),patch('openai.OpenAI',return_value=client):
            return FinalRunner(directory,config).run()

    def test_actual_sdk_structured_requests_all_roles_two_revisions_and_accounting(self):
        with tempfile.TemporaryDirectory() as d:
            state=self.run_intercepted(d,self.handler)
            self.assertEqual(len(self.seen),8);self.assertEqual(state['mode'],'openai')
            self.assertEqual(state['api_usage']['call_count'],8)
            for name in ORDER:
                usage=state['api_usage']['per_agent'][name]
                self.assertEqual({k:usage[k] for k in ('calls','input_tokens','output_tokens')},{'calls':2,'input_tokens':2400,'output_tokens':600})
                self.assertAlmostEqual(usage['estimated_cost_USD'],.0045)
            self.assertAlmostEqual(state['api_usage']['estimated_cost_USD'],.018)
            self.assertEqual(len(state['revisions']),2)
            self.assertTrue((Path(d)/state['package']).is_file())
            self.assertFalse(any(r['handoff']['results']['konstruktor']['simulated'] for r in state['revisions']))
            self.assertEqual([json.loads(x['input'])['agent'] for x in self.seen],list(ORDER)*2)

    def test_incomplete_json_missing_usage_and_unknown_model_stop_after_one_no_retry(self):
        mutations=[lambda b:b.update(status='incomplete',incomplete_details={'reason':'max_output_tokens'}),
                   lambda b:b['output'][0]['content'][0].update(text='{broken'),
                   lambda b:b.pop('usage'),lambda b:b.update(model='unpriced-model')]
        for mutation in mutations:
            self.seen=[]
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as d:
                with self.assertRaises(ValueError):self.run_intercepted(d,lambda req:self.handler(req,mutation))
                self.assertEqual(len(self.seen),1)
                state=json.loads((Path(d)/'trial.json').read_text())
                self.assertEqual(state['status'],'stopped');self.assertEqual(state['api_usage']['call_count'],1)
                self.assertFalse(list(Path(d).glob('*.zip')))

    def test_api_error_and_budget_threshold_stop_without_retry(self):
        self.seen=[]
        def handle(request):self.seen.append(request);return self.httpx.Response(429,json={'error':{'message':'offline test','type':'rate_limit_error'}})
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):self.run_intercepted(d,handle)
            self.assertEqual(len(self.seen),1)
            state=json.loads((Path(d)/'trial.json').read_text())
            self.assertEqual(state['stop_reason'],'api_rate_limit');self.assertIsNone(state['api_usage']['estimated_cost_USD'])
        self.seen=[]
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):self.run_intercepted(d,self.handler,replace(PAID,threshold=.001))
            self.assertFalse(self.seen)

    def test_missing_key_factory_failure_and_preflight_never_send_request(self):
        with patch.dict(os.environ,ENV):
            with patch('openai.OpenAI',side_effect=AssertionError('No request')):
                initial,kb,budget,estimate=preflight(PAID)
                self.assertEqual(estimate['paid_requests_started'],0)
                self.assertTrue(kb['compatible'])
        with patch.dict(os.environ,{**ENV,'OPENAI_API_KEY':''}),tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):FinalRunner(d,PAID).run()
            state=json.loads((Path(d)/'trial.json').read_text());self.assertEqual(state['api_usage']['call_count'],0)


class FinalWorkflowTests(unittest.TestCase):
    def test_manual_secret_scope_and_separate_approval_without_legacy_limit_changes(self):
        workflow=(ROOT/'.github/workflows/final-ai-trial.yml').read_text()
        self.assertIn('workflow_dispatch:',workflow);self.assertNotIn('\n  push:',workflow);self.assertNotIn('\n  schedule:',workflow)
        self.assertIn('environment: ai-trial',workflow);self.assertEqual(workflow.count('secrets.OPENAI_API_KEY'),1)
        self.assertIn("github.run_attempt == 1",workflow);self.assertIn('needs: preflight',workflow)
        self.assertIn('contents: read',workflow);self.assertIn('ODOBRIM KONCNI AI V01 DO 16 KLICEV',workflow)
        legacy=(ROOT/'.github/workflows/ai-trial.yml').read_text()
        self.assertIn('ODOBRIM AI V01-R01',legacy)
        from src.orchestrator.cloud import TrialConfig, APPROVALS
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(ValueError):TrialConfig('openai','gpt-5.4-mini',1500,48000,APPROVAL['openai']).validate()
