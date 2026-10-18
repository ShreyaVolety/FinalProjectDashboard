"""Offline tests: no network or paid API calls."""
import unittest,tempfile,json,sys,io,types,hashlib,zipfile,threading,importlib.util,os
from pathlib import Path
from unittest.mock import patch
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
from runtime import Ledger,BudgetStop,execute,aggregate,context
from controller import import_archive,scrub
import pipeline

class FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__('streamlit');self.session_state=State()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def __getattr__(self,name):
        if name in ['sidebar']:return self
        if name=='tabs':return lambda names:[self for _ in names]
        if name=='columns':return lambda n:[self for _ in range(n)]
        if name in ['form','expander']:return lambda *a,**k:self
        if name=='fragment':return lambda **kwargs:lambda fn:fn
        if name in ['button','form_submit_button']:return lambda *a,**k:False
        if name=='file_uploader':return lambda *a,**k:None
        if name in ['text_input','date_input','number_input','checkbox']:return lambda *a,**k:k.get('value')
        if name=='multiselect':return lambda *a,**k:k.get('default',[])
        if name=='selectbox':return lambda *a,**k:list(a[1] if len(a)>1 else k['options'])[0]
        return lambda *a,**k:None
class State(dict):
    __getattr__=dict.__getitem__
    __setattr__=dict.__setitem__

def cfg():return dict(as_of='2026-10-18',budgets={'openai':1.,'twitter':1.,'bigquery':1.},monitor_start='2026-07',input_price=.75,output_price=4.5,max_new_items=16,workers=2,complete_through='2026-09-01')

class Tests(unittest.TestCase):
    def test_override(self):
        ns={};execute("%pip install forbidden\nX=1\ntry:\n from google.colab import drive\n drive.mount('never')\nexcept ImportError:pass\nY=X+1",ns,{'X':7})
        self.assertEqual(ns['Y'],8)
    def test_budget_concurrency(self):
        with tempfile.TemporaryDirectory() as t:
            ledger=Ledger(Path(t)/'ledger.json',{'openai':1.})
            counts=[]
            def call(i):
                try:ledger.reserve(str(i),'openai',.2);counts.append(i)
                except BudgetStop:pass
            threads=[threading.Thread(target=call,args=(i,)) for i in range(20)]
            for x in threads:x.start()
            for x in threads:x.join()
            self.assertEqual(len(counts),5);self.assertAlmostEqual(ledger.spent('openai'),1.)
            ledger.finish(str(counts[0]),.05);self.assertAlmostEqual(ledger.spent('openai'),.85)
            with self.assertRaises(RuntimeError):ledger.reserve(str(counts[0]),'openai',.01)
    def test_import(self):
        with tempfile.TemporaryDirectory() as t:
            def archive(name):
                b=io.BytesIO()
                with zipfile.ZipFile(b,'w') as z:z.writestr(name,'x,y\n1,2')
                return b.getvalue()
            self.assertEqual(import_archive(archive('data/example.csv'),t),1)
            self.assertTrue((Path(t)/'exports/example.csv').exists())
            with self.assertRaises(ValueError):import_archive(archive('../outside.csv'),t)
            self.assertEqual(import_archive(archive('data/example.csv'),t),0)
            with self.assertRaises(ValueError):import_archive(archive('project/credentials.json'),t)
    def test_redaction(self):
        secret={'openai':'sk-test-SENTINEL','gcp_service_account':{'private_key':'TEST\nPRIVATE'}}
        self.assertNotIn('SENTINEL',scrub('error sk-test-SENTINEL',secret))
        self.assertNotIn('PRIVATE',scrub(json.dumps('TEST\nPRIVATE'),secret))
    def namespace(self,folder):
        h=lambda x:hashlib.sha256(str(x).encode()).hexdigest()
        rows=[dict(item_id='N:'+str(i),platform='News',text='sample '+str(i)) for i in range(10)]
        return dict(cohort=pd.DataFrame(rows),model_input=lambda r:dict(item_id=r['item_id'],item_type=r['platform'],text=r['text']),input_key=lambda item:h(json.dumps(item,sort_keys=True)),CACHE={},UNRESOLVED=set(),digest=h,CONFIG_HASH='test-config',CALLS=folder,SYSTEM='guide',SCHEMA={},MAX_OUTPUT_TOKENS=100,MODEL='test-model',BATCH_SIZE=8,evidence_problems=lambda label,text:[])
    def test_score_and_cache(self):
        class Client:
            count=0
            def __init__(self,**kw):self.responses=self
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def create(self,**kw):
                Client.count+=1;items=json.loads(kw['input'][1]['content']);labels=[dict(item_id=i['item_id'],political_attribution='Neither',attribution_target='',attribution_voice='Not applicable') for i in items]
                return types.SimpleNamespace(status='completed',model='test-model',output_text=json.dumps({'items':labels}),model_dump=lambda **k:{'status':'completed'},usage=types.SimpleNamespace(model_dump=lambda **k:dict(input_tokens=50,output_tokens=50)))
        with tempfile.TemporaryDirectory() as t,patch.dict(sys.modules,{'openai':types.SimpleNamespace(OpenAI=Client),'jsonschema':types.SimpleNamespace(validate=lambda *args:None)}):
            old=os.environ.get('OPENAI_API_KEY')
            p=pipeline.Pipeline(t,cfg(),{'openai':'sentinel'});ns=self.namespace(Path(t)/'calls');ns['CALLS'].mkdir()
            p.score_pending(ns);self.assertEqual(len(ns['CACHE']),10);self.assertEqual(Client.count,2)
            p.score_pending(ns);self.assertEqual(Client.count,2)
            self.assertAlmostEqual(p.ledger.spent('openai'),2*(50*.75+50*4.5)/1e6)
            for f in ns['CALLS'].glob('*.json'):self.assertEqual(json.loads(f.read_text())['status'],'completed')
            if old is None:os.environ.pop('OPENAI_API_KEY',None)
            else:os.environ['OPENAI_API_KEY']=old
    def test_quota_stops_and_releases(self):
        class Denied(Exception):status_code=429
        class Client:
            def __init__(self,**kw):self.responses=self
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def create(self,**kw):raise Denied('insufficient_quota sk-secret')
        with tempfile.TemporaryDirectory() as t,patch.dict(sys.modules,{'openai':types.SimpleNamespace(OpenAI=Client),'jsonschema':types.SimpleNamespace(validate=lambda *args:None)}),patch.object(pipeline,'aggregate',lambda ns:Path(t)):
            config=cfg();config['workers']=1
            p=pipeline.Pipeline(t,config,{'openai':'sk-secret'});ns=self.namespace(Path(t)/'calls');ns['CALLS'].mkdir()
            with self.assertRaises(RuntimeError):p.score_pending(ns)
            self.assertEqual(len(list(ns['CALLS'].glob('*.json'))),1);self.assertEqual(p.ledger.spent('openai'),0)
            record=json.loads(next(ns['CALLS'].glob('*.json')).read_text());self.assertNotIn('sk-secret',record['error_message'])
    def test_aggregate(self):
        with tempfile.TemporaryDirectory() as t:
            cols=dict(platform=['News','News','X'],analysis_month=['2026-08']*3,source=['A','B','user'],item_id=['N:1','N:2','X:1'],production_sample=[True]*3)
            frame=pd.DataFrame(cols)
            def predictions(f):
                return pd.DataFrame(dict(item_id=f.item_id,ai_status='ok',relevance='Relevant',geography='US',economic_tone=['Negative','Positive','Negative'],emotional_wording='Absent',price_frame='Neither',experience_frame='Neither',time_frame='Current-recent conditions',political_attribution='Neither',topic_prices=0))
            ns=dict(cohort=frame,predictions_for=predictions,RUN=Path(t),BINARY_RULES={'topic_prices':'rule'})
            aggregate(ns);out=pd.read_csv(Path(t)/'media_monthly_for_section4.csv')
            self.assertEqual(out.news_negative_share.iloc[0],.5);self.assertEqual(out.x_negative_share.iloc[0],1.)
    def test_startup_without_keys(self):
        st=FakeStreamlit()
        with tempfile.TemporaryDirectory() as t,patch.dict(sys.modules,{'streamlit':st}),patch.dict(os.environ,{'DASHBOARD_WORKSPACES':t}):
            spec=importlib.util.spec_from_file_location('startup_test',Path(__file__).parent/'app.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
            self.assertEqual(st.session_state.credentials,{})
if __name__=='__main__':unittest.main()
