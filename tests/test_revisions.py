"""Bounded coordination, immutable requirements, evidence and real package export."""

from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from src.models import Handoff
from src.models.contracts import ORDER, digest
from src.agents.simulated import default_agents, SimulatedAgent
from src.agents.openai_agent import OpenAIAgent, OpenAITransport, ModelError
from src.orchestrator.pipeline import Orchestrator
from src.orchestrator.revisions import RevisionRunner
from src.orchestrator.revision_policy import (RevisionError, extract_tasks, reconcile, fixed_requirements, require_fixed,
                                              evaluate_proposal, audit, transition_is_proven)
from src.reporting.revisions import comparison_data
from test_ai_cycles import handoff


def completed():
    return Orchestrator().run(handoff(),expected_variant='V01',expected_revision='R01')


class RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.directory.cleanup)
        cls.state=RevisionRunner(cls.directory.name).run(handoff(),approved_sequence='V01:R01-R02')
        cls.root=Path(cls.directory.name)
        cls.first=Handoff(**json.loads((cls.root/'cycles/V01-R01.json').read_text())['handoff'])
        cls.second=Handoff(**json.loads((cls.root/'cycles/V01-R02.json').read_text())['handoff'])

    def test_complete_sequence_stops_after_r02_and_recalculates_every_agent(self):
        self.assertEqual(self.state['completed_revisions'],['V01-R01','V01-R02'])
        self.assertEqual(self.state['status'],'limit_reached')
        self.assertEqual(self.state['stop_reason'],'max_revisions_reached')
        self.assertEqual(self.state['api_requests_started'],0)
        self.assertFalse((self.root/'cycles/V01-R03.json').exists())
        self.assertIsNone(self.second.results['recenzent']['next_revision'])
        self.assertEqual(self.first.inputs,self.second.inputs)
        for name in ORDER:
            self.assertEqual(self.first.results[name]['engineering'],self.second.results[name]['engineering'])
            self.assertNotEqual(self.first.results[name]['trace']['handoff_sha256'],self.second.results[name]['trace']['handoff_sha256'])
        self.assertTrue(all(record['deterministic_recalculation'] for record in self.state['revision_records']))
        self.assertEqual(self.state['change_log'][0]['parameters'],{})
        self.assertEqual(self.state['classification']['resolved'],[])
        self.assertEqual(len(self.state['classification']['unchanged_open']),3)

    def test_tasks_route_by_explicit_owner_and_every_agent_receives_them(self):
        tasks=self.state['tasks']
        self.assertEqual(len(tasks),3)  # identical local/agent findings are not doubled
        self.assertEqual(len({t['id'] for t in tasks}),3)
        self.assertEqual({t['responsible_agent'] for t in tasks},set(ORDER[:3]))
        for task in tasks:
            self.assertTrue(task['description'] and task['reference'] and task['proposed_correction'])
            self.assertEqual(task['status'],'unresolved')
            self.assertEqual({s['revision'] for s in task['sources']},{'R01','R02'})
        for name in ORDER:
            expected={t['id'] for t in tasks if t['responsible_agent']==name or name=='recenzent'}
            actual=set(self.second.results[name]['revision_work']['received_task_ids'])
            self.assertEqual(actual,expected)
        self.assertEqual(self.second.open_questions,self.first.open_questions)

    def test_missing_owner_is_manual_and_no_keyword_guess_is_used(self):
        value=completed()
        value.results['recenzent']['findings']=[{'id':'UNKNOWN','description':'Hidravlik naj nekaj popravi',
            'severity':'major','status':'open','required_correction':'Preveri ročno.'}]
        tasks=extract_tasks(value)
        manual=[t for t in tasks if t['responsible_agent'] is None]
        self.assertEqual(len(manual),1)
        self.assertTrue(manual[0]['manual_review'] and manual[0]['requires_user_decision'])
        self.assertEqual(manual[0]['reference'],'manual_review')

    def test_unknown_owner_is_allowed_by_json_contract_and_requires_manual_review(self):
        from src.models.contracts import FINDING, validate_schema
        finding={'id':'MANUAL','target_agent':None,'severity':'major','status':'open',
                 'description':'Nejasna odgovornost','required_correction':'Ročni pregled.'}
        validate_schema(finding,FINDING)
        value=completed();value.results['recenzent']['findings'].append(finding)
        task=next(t for t in extract_tasks(value) if t['description']=='Nejasna odgovornost')
        self.assertTrue(task['manual_review'])
        self.assertIsNone(task['responsible_agent'])

    def test_fixed_and_derived_edits_are_not_applied(self):
        before=completed();snapshot=fixed_requirements(before.inputs)
        task=extract_tasks(before)[0]
        for key in ('payload_kg','max_height_mm','lift_time_s','results.konstruktor.engineering.peak_cylinder_force_N'):
            candidate,decision=evaluate_proposal(before,task,{'task_id':task['id'],'parameter':key,'new_value':999,'reason':'AI says so'},snapshot)
            self.assertEqual(candidate,before.inputs)
            self.assertTrue(decision['requires_user_decision'])
            self.assertEqual(decision['status'],'not_applied')
        changed=deepcopy(before.inputs);changed['payload_kg']=299
        with self.assertRaises(RevisionError):require_fixed(changed,snapshot)
        changed=deepcopy(before.inputs);changed['new_requirement']=1
        with self.assertRaises(RevisionError):require_fixed(changed,snapshot)

    def test_unjustified_geometry_change_is_rejected(self):
        before=completed();task=next(t for t in extract_tasks(before) if t['responsible_agent']=='konstruktor')
        candidate,decision=evaluate_proposal(before,task,{'parameter':'arm_length_mm','new_value':1150,'reason':'Make it different'},fixed_requirements(before.inputs))
        self.assertEqual(candidate,before.inputs)
        self.assertEqual(decision['reason'],'no_verifiable_constructor_task')

    def test_geometry_proposal_requires_independent_failure_and_is_recalculated(self):
        # An intentionally inconsistent snapshot exercises the future proposal gate.
        # It is never used as a successful R01 in the delivered two-revision sample.
        before=completed()
        before.inputs["arm_length_mm"]=1300
        before.input_sources["arm_length_mm"]="synthetic:invalid-snapshot-test"
        before.results['konstruktor']['engineering']['parameters']['arm_length_mm']=1300
        before.results['recenzent']['engineering'].update(audit(before))
        before.results['recenzent']['findings']=[]
        task=next(t for t in extract_tasks(before) if t.get('verification') and t['description']=='dolžine rok, vpetja in položaji')
        candidate,decision=evaluate_proposal(before,task,{'parameter':'arm_length_mm','new_value':1100,
            'reason':'Odpravi dokazano prekoračeno geometrijsko omejitev.'},fixed_requirements(before.inputs))
        self.assertEqual(decision['status'],'applied')
        self.assertEqual(candidate['arm_length_mm'],1100)
        self.assertEqual(candidate['payload_kg'],300)
        self.assertEqual(candidate['max_height_mm']-candidate['min_height_mm'],650)
        self.assertIn('probe_sha256',decision['evidence'])
        bad,decision=evaluate_proposal(before,task,{'parameter':'arm_length_mm','new_value':1400,
            'reason':'Still invalid'},fixed_requirements(before.inputs))
        self.assertEqual(decision['status'],'not_applied')
        self.assertEqual(bad,before.inputs)

    def test_review_cannot_change_fixed_inputs_or_revision_context(self):
        current=Handoff(**self.second.to_dict());current.results={}
        original=SimulatedAgent('recenzent')
        for field in ('inputs','revision_context'):
            class BadReviewer:
                name='recenzent'
                def run(self,value):
                    result=original.run(value)
                    if field=='inputs':result.inputs['payload_kg']=999
                    else:result.revision_context['paid_mode_enabled']=True
                    return result
            with self.subTest(field=field),self.assertRaises(ValueError):
                Orchestrator((*default_agents()[:3],BadReviewer())).run(current,expected_variant='V01',expected_revision='R02')

    def test_claimed_or_disappearing_findings_do_not_resolve_without_proof(self):
        before=completed();tasks=extract_tasks(before)
        after=deepcopy(before);after.revision='R02'
        after.results['recenzent']['engineering']['findings']=[]
        after.results['recenzent']['findings']=[]
        updated=reconcile(tasks,before,after)
        self.assertTrue(all(t['status']=='unresolved' for t in updated))
        fake=deepcopy(tasks);fake[0].update(status='resolved',evidence={'claimed':'yes'})
        with self.assertRaises(RevisionError):comparison_data(before,after,fake)

    def test_actual_independent_fail_to_pass_can_close_a_numerical_task_only(self):
        # Isolated synthetic corruption tests evidence logic; it is NOT the delivered
        # simulation and does not claim that the baseline structural risks were fixed.
        before=completed();before.results['konstruktor']['engineering']['positions'][0]['span_mm']=10
        before.results['recenzent']['engineering'].update(audit(before))
        before.results['recenzent']['findings']=[]
        tasks=extract_tasks(before)
        after=completed();after.revision='R02'
        updated=reconcile(tasks,before,after)
        resolved=[t for t in updated if t['status']=='resolved']
        self.assertTrue(resolved)
        self.assertTrue(all(transition_is_proven(t,before,after) for t in resolved))
        self.assertTrue(any(t['status']=='unresolved' for t in updated))

    def test_new_findings_and_user_requirement_decisions_are_separate(self):
        before=completed();after=deepcopy(before);after.revision='R02'
        after.results['recenzent']['findings'].append({'id':'NEW','target_agent':'konstruktor','severity':'major','status':'open',
            'reference':'inputs.payload_kg','description':'Potrebna odločitev o nosilnosti','required_correction':'Odločitev uporabnika; brez spremembe zahteve.'})
        updated=reconcile(extract_tasks(before),before,after)
        new=[t for t in updated if t['status']=='open']
        self.assertEqual(len(new),1)
        self.assertTrue(new[0]['requires_user_decision'])
        self.assertEqual(after.inputs['payload_kg'],300)

    def test_paid_sequence_and_paid_context_are_disabled_before_request(self):
        with tempfile.TemporaryDirectory() as directory,patch('src.agents.openai_agent.OpenAITransport') as factory:
            with self.assertRaises(RevisionError):RevisionRunner(directory,mode='openai')
            factory.assert_not_called()
        current=deepcopy(self.second);current.results={}
        transport=Mock()
        with self.assertRaises(ModelError) as caught:OpenAIAgent('konstruktor',transport).run(current)
        self.assertEqual(caught.exception.code,'multi_revision_paid_disabled')
        transport.generate.assert_not_called()
        adapter=object.__new__(OpenAITransport);adapter.client=Mock()
        with self.assertRaises(ModelError):adapter.generate('test',current)
        adapter.client.responses.create.assert_not_called()

    def test_bounds_approval_reuse_and_one_revision_mode(self):
        for limit in (0,3,100,True):
            with self.subTest(limit=limit),self.assertRaises(RevisionError):RevisionRunner('/tmp/unused',max_revisions=limit)
        with tempfile.TemporaryDirectory() as directory:
            mutated=RevisionRunner(directory);mutated.max_revisions=3
            with self.assertRaises(RevisionError):mutated.run(handoff(),approved_sequence='V01:R01-R03')
            with self.assertRaises(RevisionError):RevisionRunner(directory).run(handoff(),approved_sequence=None)
            self.assertEqual(list(Path(directory).iterdir()),[])
            state=RevisionRunner(directory,max_revisions=1).run(handoff(),approved_sequence='V01:R01-R01')
            self.assertEqual(state['completed_revisions'],['V01-R01'])
            self.assertNotIn('development_cycle_package',state)
            with self.assertRaises(FileExistsError):RevisionRunner(directory,max_revisions=1).run(handoff(),approved_sequence='V01:R01-R01')

    def test_v02_or_other_fixed_trial_requirements_are_rejected(self):
        for field,value in (('variant','V02'),('revision','R02'),('payload_kg',301),('max_height_mm',999)):
            initial=handoff()
            if field in ('variant','revision'):setattr(initial,field,value)
            else:initial.inputs[field]=value
            with tempfile.TemporaryDirectory() as directory,self.subTest(field=field),self.assertRaises(RevisionError):
                RevisionRunner(directory).run(initial,approved_sequence='V01:R01-R02')

    def test_stop_before_second_revision_keeps_first_but_no_full_zip(self):
        root=None
        class StopPlanner:
            def propose(self,previous,tasks):
                (root/'STOP').touch()
                return []
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with self.assertRaises(RevisionError):RevisionRunner(root,planner=StopPlanner()).run(handoff(),approved_sequence='V01:R01-R02')
            state=json.loads((root/'sequence.json').read_text())
            self.assertEqual(state['status'],'stopped')
            self.assertEqual(state['completed_revisions'],['V01-R01'])
            self.assertFalse((root/'V01_R01-R02_Razvojni_cikel.zip').exists())
            self.assertTrue((root/'cycles/packages/V01-R01_Razvojni_paket.zip').exists())

    def test_combined_zip_pdf_and_json_keep_real_nonimprovement_status(self):
        from pypdf import PdfReader
        with ZipFile(self.root/self.state['development_cycle_package']) as archive:
            expected={'V01-R01_Razvojni_paket.zip','V01-R02_Razvojni_paket.zip','V01_R01-R02_Primerjava.pdf',
                      'Ugotovitve_in_statusi.json','Primerjava.json','Sledljivost_cikla.json',
                      'V01-R01_Izvorni_podatki.json','V01-R02_Izvorni_podatki.json'}
            self.assertEqual(set(archive.namelist()),expected)
            self.assertIsNone(archive.testzip())
            data=json.loads(archive.read('Primerjava.json'))
            self.assertFalse(data['improvement_demonstrated'])
            self.assertFalse(data['technical_approval'])
            self.assertEqual(data['resolved_count'],0)
            self.assertEqual(data['review_decision'],'changes_required')
            for item in data['metrics_C'].values():self.assertEqual(item['R01'],item['R02'])
            pdf=PdfReader(io.BytesIO(archive.read('V01_R01-R02_Primerjava.pdf')),strict=True)
            text='\n'.join(p.extract_text() for p in pdf.pages)
            for token in ('Dokazano izboljšanje: NE','nerešeno','650','300','engineering_verified=false','0'):
                self.assertIn(token,text)
            for rev in ('R01','R02'):
                with ZipFile(io.BytesIO(archive.read(f'V01-{rev}_Razvojni_paket.zip'))) as inner:
                    self.assertEqual(len(inner.namelist()),6)
                    source=json.loads(inner.read('05_Izvorni_podatki.json'))
                    self.assertEqual(source['handoff']['revision'],rev)

    def test_comparison_text_stays_within_a4_without_overlaps(self):
        import fitz
        doc=fitz.open(self.root/'V01_R01-R02_Primerjava.pdf')
        for page in doc:
            spans=[s for b in page.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans'] if s['text'].strip()]
            for i,s in enumerate(spans):
                self.assertTrue(page.rect.contains(fitz.Rect(s['bbox'])))
                for t in spans[i+1:]:self.assertLessEqual((fitz.Rect(s['bbox']) & fitz.Rect(t['bbox'])).get_area(),3)
