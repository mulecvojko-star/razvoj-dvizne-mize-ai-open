"""Never publish inconsistent model prose as a verified component choice."""
from copy import deepcopy
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from src.models import Handoff
from src.models.contracts import digest
from src.final_trial.runner import Config,APPROVAL,FinalRunner
from src.final_trial.agents import SimulatedResponder
from src.final_trial.presentation import document_view
from src.final_trial.reports import validate,build_final_package

FIXTURE=json.loads(Path(__file__).with_name('fixtures').joinpath('hydraulic_prose_40900628103.json').read_text(encoding='utf-8'))


class DocumentPresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Replay(SimulatedResponder):
            def request(self,name,h,kb,expected,requests):
                data=super().request(name,h,kb,expected,requests)
                if name=='hidravlik':
                    data['selection']['cylinder_id']='HYD-02';data['source_ids'].append('HYD-02')
                    data['result'].update(deepcopy(FIXTURE['prose']))
                return data
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}):cls.state=FinalRunner(cls.root,Config(approval=APPROVAL['simulated']),responder=Replay()).run()

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_actual_prose_is_preserved_but_structured_choice_drives_document_view(self):
        self.assertEqual(digest(FIXTURE['prose']),FIXTURE['provenance']['excerpt_sha256'])
        h=Handoff(**self.state['revisions'][0]['handoff']);before=deepcopy(h.to_dict())
        view,notes=document_view(h)
        self.assertEqual(h.to_dict(),before);self.assertTrue(notes)
        self.assertEqual(h.results['hidravlik']['summary'],FIXTURE['prose']['summary'])
        self.assertIn('HYD-02',view.results['hidravlik']['summary'])
        self.assertNotIn('HYD-01',view.results['hidravlik']['summary'])
        self.assertEqual(view.results['hidravlik']['engineering'],h.results['hidravlik']['engineering'])
        self.assertFalse(view.results['hidravlik']['engineering_verified'])

    def test_pdf_facts_source_json_and_audit_log_are_explicitly_separated_without_api(self):
        from pypdf import PdfReader
        with ZipFile(self.root/self.state['package']) as z:
            source=json.loads(z.read('08_Izvorni_podatki.json'));validate(source)
            self.assertEqual(source['document_presentation']['model_calls'],0)
            self.assertTrue(source['document_presentation']['notes'])
            self.assertEqual(source['revisions'][0]['handoff']['results']['hidravlik']['summary'],FIXTURE['prose']['summary'])
            for filename in ('00_Povzetek_razvoja.pdf','02_Hidravlik.pdf'):
                text=' '.join(' '.join(p.extract_text().split()) for p in PdfReader(BytesIO(z.read(filename))).pages)
                self.assertIn('HYD-02',text);self.assertIn('Deterministični povzetek',text)
                self.assertNotIn(FIXTURE['prose']['summary'],text)
                self.assertIn('engineering_verified=false',text)
            audit=' '.join(p.extract_text() for p in PdfReader(BytesIO(z.read('06_Komunikacija_agentov.pdf'))).pages)
            self.assertIn('Opozorilo za branje izvirne komunikacije',audit)
            self.assertIn('HYD-01',audit)
        with tempfile.TemporaryDirectory() as d,patch('src.final_trial.runner.FinalTransport',side_effect=AssertionError('No model calls')):
            self.assertTrue(build_final_package(self.state,d).is_file())

    def test_document_workflow_accepts_only_successful_allowed_sources_and_has_no_key(self):
        text=Path(__file__).resolve().parents[1].joinpath('.github/workflows/development-package.yml').read_text()
        self.assertIn("run.conclusion !== 'success'",text)
        self.assertIn("run.head_branch !== 'main'",text)
        self.assertIn("run.event !== 'workflow_dispatch'",text)
        self.assertIn("'.github/workflows/final-ai-trial.yml'",text)
        self.assertIn('--report-only source-artifact/trial.json',text)
        self.assertNotIn('secrets.OPENAI_API_KEY',text)
        self.assertIn('actions: read',text)
