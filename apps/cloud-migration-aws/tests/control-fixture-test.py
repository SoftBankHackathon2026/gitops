import json,time,urllib.request,urllib.error,uuid
import adapter

def call(method,url,body=None,token=None):
 h={'Content-Type':'application/json'}
 if token:h['Authorization']='Bearer '+token
 req=urllib.request.Request(url,data=json.dumps(body).encode() if body is not None else None,headers=h,method=method)
 try:
  with urllib.request.urlopen(req,timeout=20) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
base='http://ingress:8080';ctl='http://ingress:9092'
for _ in range(60):
 try:
  if call('GET',base+'/readyz')[0]==200:break
 except Exception:time.sleep(.3)
else:raise AssertionError('ingress failed startup')
assert call('GET',ctl+'/status')[0]==401
assert call('POST',base+'/api/requests',{})[0]==401
app=adapter.Adapter(ctl,'local-test-control',{'aws':{'url':'https://backend:8443','environment':'aws','database':'aws'},'gcp':{'url':'https://backend:8444','environment':'gcp','database':'gcp'}})
assert app.status()['target']=='aws'
assert app.status()['state']=='PAUSED'
def request(n):return {'request_id':str(uuid.uuid4()),'run_id':'cloud_test','phase':'cloud','request_no':str(n),'payload':'test','created_at':'2026-11-07T00:00:00.000Z'}
def enqueue(r): assert call('POST',base+'/api/requests',r,'local-test-api')[0]==202
def wait_committed(r,env):
 for _ in range(100):
  status,d=call('GET',base+'/api/requests/'+r['request_id'],token='local-test-api')
  if d.get('status')=='committed':assert d['environment']==env;return
  time.sleep(.05)
 raise AssertionError('not committed')
r1=request(1);enqueue(r1)
assert call('GET',base+'/api/requests/'+r1['request_id'],token='local-test-api')[1]['status']=='accepted'
app.handle('POST','/resume',{});wait_committed(r1,'aws')
app.handle('POST','/pause',{})
r2=request(2);enqueue(r2)
assert app.handle('POST','/drain',{})['settled']
app.handle('POST','/target',{'target':'gcp'})
assert app.status()['state']=='PAUSED'
app.handle('POST','/resume',{});wait_committed(r2,'gcp')
print('PASS: auth, AWS initial target, accepted during pause, drain with backlog, epoch switch, GCP delivery, read-only readiness')
