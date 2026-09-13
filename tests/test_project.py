import copy, importlib.util, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path); m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
update=load('updater',ROOT/'scripts/update.py');deploy=load('deployer',ROOT/'deploy.py')

def empty():return {'schema_version':2,'timezone':'Asia/Shanghai','updated_at':None,'sources':[],'reports':[]}
def example():
    d=empty();d['updated_at']='2026-01-02T01:00:00+00:00';d['sources']=[{'id':'source1','name':'Fixture only','url':'https://example.com/disclosure'}]
    d['reports']=[{'id':'fixture-only','date':'2026-01-02','slot':'09:00','generated_at':d['updated_at'],'information_cutoff':d['updated_at'],'headline':'Fixture only, not investment information','summary':[],'quotes':[{'code':'000001.SH','name':'Fixture only','value':1234.5,'change_pct':-1.0,'observed_at':'2026-01-01T07:00:00+00:00','source_id':'source1'}],'stories':[{'title':'Fixture only','fact':'Fictional test content','source_ids':['source1'],'published_at':'2026-01-01T07:00:00+00:00'}],'opportunities':[],'scenarios':[],'alerts':[]}]
    return d

class ValidationTests(unittest.TestCase):
    def test_empty_is_not_fake_data(self):self.assertEqual(update.validate(empty())['reports'],[])
    def test_valid_fixture(self):self.assertEqual(len(update.validate(example())['reports']),1)
    def test_unknown_quote_source(self):
        d=example();d['reports'][0]['quotes'][0]['source_id']='missing'
        with self.assertRaises(ValueError):update.validate(d)
    def test_post_cutoff_quote(self):
        d=example();d['reports'][0]['quotes'][0]['observed_at']='2026-01-03T07:00:00+00:00'
        with self.assertRaises(ValueError):update.validate(d)
    def test_future_and_naive_timestamps_rejected(self):
        for s in ['2099-01-01T00:00:00+00:00','2026-01-02T09:00:00']:
            with self.assertRaises(ValueError):update.timestamp(s)
    def test_no_private_top_level_fields(self):
        d=empty();d['holdings']={'private':True}
        with self.assertRaises(ValueError):update.validate(d)
    def test_history_cannot_be_rewritten(self):
        d=example();changed=copy.deepcopy(d);changed['reports'][0]['headline']='changed'
        with self.assertRaises(ValueError):update.merge(d,changed)
    def test_history_kept_when_new_feed_empty(self):self.assertEqual(update.merge(example(),empty())['reports'],example()['reports'])
    def test_duplicate_feed_no_duplicate_reports(self):self.assertEqual(len(update.merge(example(),example())['reports']),1)
    def test_no_fake_check_when_unconfigured(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'latest.json';status=Path(tmp)/'status.json';data.write_text(json.dumps(empty()))
            with patch.object(update,'DATA',data),patch.object(update,'STATUS',status),patch.dict(update.os.environ,{'REPORT_BUNDLE_URL':''}):
                self.assertEqual(update.main(),0)
                self.assertIsNone(json.loads(status.read_text())['checked_at']);self.assertIsNone(json.loads(data.read_text())['updated_at'])
    def test_failed_import_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp)/'latest.json';status=Path(tmp)/'status.json';data.write_text(json.dumps(example()))
            with patch.object(update,'DATA',data),patch.object(update,'STATUS',status),patch.dict(update.os.environ,{'REPORT_BUNDLE_URL':'https://example.com/data','GITHUB_OUTPUT':''}),patch.object(update,'urlopen',side_effect=TimeoutError):
                self.assertEqual(update.main(),1);self.assertEqual(json.loads(data.read_text())['reports'],example()['reports']);self.assertEqual(json.loads(status.read_text())['state'],'error')

class DeploymentTests(unittest.TestCase):
    def test_manifest_allowlist(self):
        paths=[v['path'] for v in deploy.manifest()]
        self.assertEqual(len(paths),13);self.assertNotIn('.deploy-state.json',paths);self.assertIn('deploy.py',paths)
    def test_existing_repo_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(deploy,'STATE',Path(tmp)/'state.json'),patch.object(deploy,'api',return_value={'id':12}) as mocked:
            with self.assertRaises(deploy.DeployError):deploy.create_and_push('someone','a-share-brief',deploy.manifest())
            self.assertEqual(mocked.call_count,1)
    def test_token_redaction(self):self.assertNotIn('ghp_secret',deploy.redact('failed ghp_secretABCDE'))
    def test_create_pages_upload_sequence_mocked(self):
        calls=[]
        def fake_api(method,path,payload=None,allow_404=False):
            calls.append((method,path,payload))
            if method=='GET' and path=='repos/test/a-share-brief':return None
            if method=='POST' and path=='user/repos':return {'id':42,'default_branch':'main'}
            if path.endswith('git/ref/heads/main'):return {'object':{'sha':'base'}}
            if path.endswith('/pages'):
                if method=='GET' and not any(c[0]=='POST' and c[1].endswith('/pages') for c in calls):return None
                return {'html_url':'https://test.github.io/a-share-brief/','build_type':'workflow'}
            if path.endswith('git/commits/base'):return {'tree':{'sha':'base-tree'}}
            if path.endswith('/git/trees'):return {'sha':'new-tree'}
            if path.endswith('/git/commits'):return {'sha':'new-commit'}
            if path.endswith('git/refs/heads/main'):return {}
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp,patch.object(deploy,'STATE',Path(tmp)/'state.json'),patch.object(deploy,'api',side_effect=fake_api):
            target,sha,url=deploy.create_and_push('test','a-share-brief',deploy.manifest())
            self.assertEqual(sha,'new-commit');self.assertEqual(target,'test/a-share-brief')
            self.assertFalse(next(c[2] for c in calls if c[0]=='PATCH')['force'])
            create=next(c[2] for c in calls if c[:2]==('POST','user/repos'));self.assertFalse(create['private'])
            self.assertIsNotNone(url)
    def test_scheduled_imports_disabled_by_default(self):
        s=(ROOT/'.github/workflows/pages.yml').read_text()
        self.assertIn("vars.ENABLE_DATA_UPDATES == 'true'",s)
        self.assertIn("'0 1,6 * * *'",s)
        self.assertIn("'7 0-14 * * *'",s)
if __name__=='__main__':unittest.main()
