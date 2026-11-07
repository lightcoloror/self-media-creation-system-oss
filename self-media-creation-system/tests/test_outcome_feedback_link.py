"""Bounded false-event regressions; no real operating writes."""
import copy,json,os,sys,unittest
from datetime import timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import outcome_feedback_link as link

class OutcomeFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from outcome_fixture import create_fixture
        path = create_fixture()
        previous = os.environ.get('OUTCOME_LINK_FIXTURE')
        os.environ['OUTCOME_LINK_FIXTURE'] = str(path)
        def restore():
            if previous is None: os.environ.pop('OUTCOME_LINK_FIXTURE', None)
            else: os.environ['OUTCOME_LINK_FIXTURE'] = previous
        cls.addClassCleanup(restore)
        cls.request=link.read(path)
    def setUp(self): self.r=copy.deepcopy(self.request)
    def rejects(self,code):
        with self.assertRaises(Exception) as e: link.build(self.r)
        self.assertEqual(getattr(e.exception,'code',None),code)
    def test_wrong_content(self):
        self.r['outcome']['content_id']='wrong';self.rejects('event_binding_drift')
    def test_wrong_run(self):
        self.r['outcome']['closure_run_id']='wrong';self.rejects('event_binding_drift')
    def test_cross_account(self):
        self.r['outcome']['account_id']='wrong';self.rejects('event_binding_drift')
    def test_time_evidence_missing(self):
        self.r['outcome']['edits'][0]['evidence']=None;self.rejects('time_evidence_required')
    def test_negative_edit_time(self):
        self.r['outcome']['edits'][0]['ended_at']='2026-08-09T00:00:00+08:00';self.rejects('negative_duration')
    def test_fabricated_savings(self):
        self.r['outcome']['time_saved_minutes']=120;self.rejects('savings_not_measured')
    def test_unpublished_observation(self):
        self.r['publication']=None;self.rejects('observation_without_publication')
    def test_window_too_early(self):
        self.r['observations'][0]['observation']['as_of']='2026-08-10T10:00:00+08:00';self.rejects('window_drift')
    def test_negative_capture_lag(self):
        self.r['observations'][0]['observation']['captured_at']='2026-08-10T10:00:00+08:00';self.rejects('stale_observation')
    def test_duplicate_window(self):
        self.r['observations'].append(copy.deepcopy(self.r['observations'][0]));self.rejects('duplicate_window')
    def test_no_signal_is_neutral(self):
        out=link.build(self.r)
        self.assertEqual(out['feedback']['content_signal_status'],'content_no_signal')
        self.assertEqual(out['feedback']['business_signal_status'],'not-observed')
        self.assertEqual(out['feedback']['learning_decision'],'insufficient-evidence')
    def test_default_unknown_no_due_tasks(self):
        self.r.update(outcome=None,publication=None,observations=[])
        out=link.build(self.r)
        self.assertEqual(out['outcome_candidate']['human_outcome'],'no_decision')
        self.assertEqual(out['scheduled_tasks'],[])
        self.assertEqual(out['feedback']['status'],'unknown')
        self.assertNotIn('promptfoo_observation',out['outcome_candidate'])
        self.assertNotIn('call_record_hash',out['outcome_candidate']['contract'])
    def test_content_metrics_not_business(self):
        self.r['observations'][0]['observation']['metrics']=[{'layer':'business','metric_key':'views','value':500,'unit':'count'}]
        self.rejects('metric_layer_mismatch')
    def test_resume_and_idempotence(self):
        root=Path(os.environ['TEST_TMP_ROOT'])/'outcome-link-resume'
        text={'request.json':'one','review.json':'two'}
        link.persist(root,text,stop_after=1);self.assertFalse((root/'review.json').exists())
        link.persist(root,text);before={p.name:p.stat().st_mtime_ns for p in root.iterdir()}
        link.persist(root,text);self.assertEqual(before,{p.name:p.stat().st_mtime_ns for p in root.iterdir()})
    def test_drift_refuses_partial_overwrite(self):
        root=Path(os.environ['TEST_TMP_ROOT'])/'outcome-link-drift';link.persist(root,{'z.json':'a'})
        with self.assertRaises(link.LinkError):link.persist(root,{'a.json':'new','z.json':'b'})
        self.assertFalse((root/'a.json').exists())
    def test_native_approval_gate_stays_required(self):
        p=link.read(ROOT/'fixtures/content-operations-cycle-v1/record-publication.input.json')
        p['data_classification']='deidentified-operational'
        with self.assertRaises(link.cycle.CycleError) as e:link.cycle.validate_publication_input(p)
        self.assertEqual(e.exception.code,'privacy_review_required')

    def test_exact_window_boundaries(self):
        published=link.tracker.parse_time('2026-08-10T09:00:00+08:00','published')
        for label,hours in [('early',48),('early',72),('d7',156),('d7',180)]:
            with self.subTest(label=label,hours=hours):
                observation=copy.deepcopy(self.r['observations'][0]['observation'])
                observation.update(window_label=label,as_of=(published+timedelta(hours=hours)).isoformat(),
                    captured_at=(published+timedelta(hours=hours)).isoformat())
                link.tracker.validate_observation(observation,published,0)

    def test_reported_decision_needs_matching_evidence(self):
        self.r['outcome']['decision']='discarded';self.r['outcome']['edits']=[]
        self.rejects('decision_evidence_drift')

    def test_native_review_cross_account(self):
        fixture=Path(os.environ['OUTCOME_LINK_FIXTURE']).parent
        value=link.read(fixture/'native-build-review.json');value['account_ids']=['other-account']
        p=Path(os.environ['TEST_TMP_ROOT'])/'cross-account-native-review.json';p.write_text(link.text(value),encoding='utf-8')
        self.r['native_requests']=[{'operation':'build-review','input':{'ref':p.relative_to(link.W).as_posix(),'sha256':link.sha(p)}}]
        self.rejects('event_binding_drift')

    def test_native_snapshot_wrong_publication(self):
        fixture=Path(os.environ['OUTCOME_LINK_FIXTURE']).parent
        value=link.read(fixture/'native-snapshot-early.json');value['publication_id']='wrong-publication'
        p=Path(os.environ['TEST_TMP_ROOT'])/'wrong-publication.json';p.write_text(link.text(value),encoding='utf-8')
        self.r['native_requests']=[{'operation':'record-snapshot','input':{'ref':p.relative_to(link.W).as_posix(),'sha256':link.sha(p)}}]
        self.rejects('publication_binding_drift')

    def test_adopted_and_discarded(self):
        self.r.update(publication=None,observations=[],native_requests=[])
        self.r['outcome']['edits']=[]
        for decision in ['adopted','discarded','no_decision']:
            with self.subTest(decision=decision):
                self.r['outcome']['decision']=decision
                ev={k:self.r['outcome'][k] for k in ['content_id','closure_run_id','account_id','decision','decided_at']}
                p=Path(os.environ['TEST_TMP_ROOT'])/(decision+'.json');p.write_text(link.text(ev),encoding='utf-8')
                self.r['outcome']['evidence']={'ref':p.relative_to(link.W).as_posix(),'sha256':link.sha(p)}
                self.assertEqual(link.build(self.r)['outcome_candidate']['human_outcome'],decision)

if __name__=='__main__':unittest.main()
