from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3, json, os, secrets, hashlib, hmac
from datetime import datetime, timezone

BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'transactionos.db')
app=FastAPI(title='TransactionOS API', version='3.3.4')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

@app.get('/', include_in_schema=False)
def serve_frontend():
    return FileResponse(os.path.join(BASE, 'index.html'))

@app.get('/api.js', include_in_schema=False)
def serve_api_client():
    return FileResponse(os.path.join(BASE, 'api.js'), media_type='application/javascript')

def now(): return datetime.now(timezone.utc).isoformat()
def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def init():
    c=conn(); c.executescript('''
    PRAGMA foreign_keys=ON;
    CREATE TABLE IF NOT EXISTS users(user_id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(user_id));
    CREATE TABLE IF NOT EXISTS properties(property_id TEXT PRIMARY KEY,address_line_1 TEXT NOT NULL,city TEXT,region TEXT,postal_code TEXT,country TEXT,latitude REAL,longitude REAL,property_type TEXT,jurisdiction TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS property_parties(party_id TEXT PRIMARY KEY,property_id TEXT NOT NULL,user_id TEXT,role TEXT NOT NULL,name TEXT NOT NULL,email TEXT,authority_status TEXT DEFAULT 'PENDING',FOREIGN KEY(property_id) REFERENCES properties(property_id),FOREIGN KEY(user_id) REFERENCES users(user_id));
    CREATE TABLE IF NOT EXISTS transactions(transaction_id TEXT PRIMARY KEY,property_id TEXT NOT NULL,status TEXT NOT NULL,created_by TEXT,created_at TEXT NOT NULL,FOREIGN KEY(property_id) REFERENCES properties(property_id));
    CREATE TABLE IF NOT EXISTS offers(offer_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,status TEXT NOT NULL,current_version_id TEXT,current_version_number INTEGER DEFAULT 0,created_by TEXT,created_at TEXT NOT NULL,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS offer_versions(version_id TEXT PRIMARY KEY,offer_id TEXT NOT NULL,version_number INTEGER NOT NULL,actor_party_id TEXT,status TEXT NOT NULL,payload_json TEXT NOT NULL,submitted_at TEXT,accepted_at TEXT,deadline_at TEXT,FOREIGN KEY(offer_id) REFERENCES offers(offer_id));
    CREATE TABLE IF NOT EXISTS conditions(condition_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,label TEXT NOT NULL,owner TEXT,status TEXT NOT NULL,due_at TEXT,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS documents(document_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,name TEXT NOT NULL,status TEXT NOT NULL,storage_ref TEXT,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS signatures(signature_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,document_id TEXT,party_id TEXT,status TEXT NOT NULL,signed_at TEXT,evidence_json TEXT,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS events(event_id TEXT PRIMARY KEY,transaction_id TEXT,type TEXT NOT NULL,actor_party_id TEXT,occurred_at TEXT NOT NULL,metadata_json TEXT);
    CREATE TABLE IF NOT EXISTS deposits(deposit_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,required_amount_cents INTEGER NOT NULL,status TEXT NOT NULL,provider_ref TEXT,received_at TEXT,held_at TEXT,released_at TEXT,refunded_at TEXT,dispute_reason TEXT,created_at TEXT NOT NULL,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS transaction_tasks(task_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,label TEXT NOT NULL,owner TEXT NOT NULL,status TEXT NOT NULL,due_at TEXT,sequence INTEGER NOT NULL,metadata_json TEXT,created_at TEXT NOT NULL,completed_at TEXT,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS identity_verifications(verification_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,user_id TEXT NOT NULL,legal_name TEXT NOT NULL,email TEXT,status TEXT NOT NULL,method TEXT NOT NULL,verified_at TEXT,created_at TEXT NOT NULL,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id),FOREIGN KEY(user_id) REFERENCES users(user_id));
    CREATE TABLE IF NOT EXISTS transaction_communications(communication_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,channel TEXT NOT NULL,sender TEXT,recipient TEXT,message TEXT NOT NULL,status TEXT NOT NULL,related_type TEXT,related_id TEXT,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS transaction_risks(risk_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,severity TEXT NOT NULL,category TEXT NOT NULL,title TEXT NOT NULL,detail TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,resolved_at TEXT);
    CREATE TABLE IF NOT EXISTS transaction_controls(transaction_id TEXT PRIMARY KEY,paused INTEGER NOT NULL DEFAULT 0,pause_reason TEXT,updated_at TEXT NOT NULL,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    CREATE TABLE IF NOT EXISTS brain_evaluations(evaluation_id TEXT PRIMARY KEY,transaction_id TEXT NOT NULL,state TEXT NOT NULL,priority TEXT NOT NULL,next_action_json TEXT,automated_json TEXT,escalations_json TEXT,reason TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(transaction_id) REFERENCES transactions(transaction_id));
    '''); c.commit(); c.close()
init()

def uid(p): return p+'_'+secrets.token_hex(5)
def pwd_hash(p):
    salt=secrets.token_bytes(16); dk=hashlib.scrypt(p.encode(),salt=salt,n=2**14,r=8,p=1); return salt.hex()+':'+dk.hex()
def pwd_ok(p,h):
    salt,dk=h.split(':'); got=hashlib.scrypt(p.encode(),salt=bytes.fromhex(salt),n=2**14,r=8,p=1).hex(); return hmac.compare_digest(got,dk)
def auth(authorization):
    if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Authentication required')
    c=conn(); r=c.execute('SELECT user_id FROM sessions WHERE token=? AND expires_at>?',(authorization[7:],now())).fetchone(); c.close()
    if not r: raise HTTPException(401,'Invalid or expired session')
    return r['user_id']
def event(c,tid,typ,actor=None,meta=None):
    c.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',(uid('evt'),tid,typ,actor,now(),json.dumps(meta or {})))

def ensure_control(c,tid):
    c.execute('INSERT OR IGNORE INTO transaction_controls(transaction_id,paused,pause_reason,updated_at) VALUES (?,?,?,?)',(tid,0,None,now()))

def require_ready_for_submission(c,tid):
    ident=c.execute('SELECT 1 FROM identity_verifications WHERE transaction_id=? AND status="VERIFIED" LIMIT 1',(tid,)).fetchone()
    sig=c.execute('SELECT 1 FROM signatures WHERE transaction_id=? AND status="SIGNED" LIMIT 1',(tid,)).fetchone()
    if not ident: raise HTTPException(409,'Buyer identity verification is required before offer submission')
    if not sig: raise HTTPException(409,'Buyer signature is required before offer submission')
    ensure_control(c,tid)
    ctl=c.execute('SELECT paused FROM transaction_controls WHERE transaction_id=?',(tid,)).fetchone()
    if ctl and ctl['paused']: raise HTTPException(409,'Transaction is paused; resume it before continuing')

class AuthIn(BaseModel): email:str; password:str=Field(min_length=8)
class PropertyIn(BaseModel): address_line_1:str; city:str|None=None; region:str|None=None; postal_code:str|None=None; country:str|None=None; latitude:float|None=None; longitude:float|None=None; property_type:str|None=None; jurisdiction:str|None=None
class PropertyResolveIn(BaseModel): address:str; city:str|None=None; region:str|None=None; postal_code:str|None=None; country:str|None=None; property_type:str|None=None
class TxIn(BaseModel): property_id:str
class OfferIn(BaseModel): transaction_id:str
class VersionIn(BaseModel): actor_party_id:str|None=None; payload:dict; deadline_at:str|None=None
class IdentityIn(BaseModel): transaction_id:str; legal_name:str; email:str|None=None; method:str='demo'
class SignatureIn(BaseModel): transaction_id:str; document_id:str|None=None; legal_name:str; signature_data:str; method:str='typed-demo'

@app.get('/api/transactions/{tid}/overview')
def transaction_overview(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn();
    tx=c.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    if not tx: c.close(); raise HTTPException(404,'Transaction not found')
    ensure_control(c,tid)
    ctl=c.execute('SELECT * FROM transaction_controls WHERE transaction_id=?',(tid,)).fetchone()
    tasks=[dict(x) for x in c.execute('SELECT * FROM transaction_tasks WHERE transaction_id=? ORDER BY sequence,created_at',(tid,)).fetchall()]
    risks=[dict(x) for x in c.execute('SELECT * FROM transaction_risks WHERE transaction_id=? AND status!=\"RESOLVED\" ORDER BY CASE severity WHEN \"HIGH\" THEN 0 WHEN \"MEDIUM\" THEN 1 ELSE 2 END,created_at DESC',(tid,)).fetchall()]
    comms=[dict(x) for x in c.execute('SELECT * FROM transaction_communications WHERE transaction_id=? ORDER BY created_at DESC LIMIT 50',(tid,)).fetchall()]
    identity=c.execute('SELECT * FROM identity_verifications WHERE transaction_id=? ORDER BY verified_at DESC LIMIT 1',(tid,)).fetchone()
    sig=c.execute('SELECT * FROM signatures WHERE transaction_id=? ORDER BY signed_at DESC LIMIT 1',(tid,)).fetchone()
    dep=c.execute('SELECT * FROM deposits WHERE transaction_id=? ORDER BY created_at DESC LIMIT 1',(tid,)).fetchone()
    c.commit(); c.close()
    open_tasks=[x for x in tasks if x['status']!='COMPLETED']
    next_task=open_tasks[0] if open_tasks else None
    return {'transaction':dict(tx),'paused':bool(ctl['paused']),'pause_reason':ctl['pause_reason'],'tasks':tasks,'risks':risks,'communications':comms,'identity':dict(identity) if identity else None,'latest_signature':dict(sig) if sig else None,'deposit':dict(dep) if dep else None,'next_action':next_task}

class CommunicationIn(BaseModel):
    channel:str='workspace'; sender:str|None=None; recipient:str|None=None; message:str; related_type:str|None=None; related_id:str|None=None
class RiskIn(BaseModel):
    severity:str='MEDIUM'; category:str='workflow'; title:str; detail:str
class PauseIn(BaseModel): reason:str

@app.post('/api/transactions/{tid}/seller-verify')
def seller_verify(tid:str,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn()
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    event(c,tid,'SELLER_IDENTITY_AUTHORITY_VERIFIED',None,{'method':'demo','prototype':True})
    c.commit(); c.close(); return {'transaction_id':tid,'status':'VERIFIED','authority_status':'VERIFIED','prototype':True}

@app.post('/api/offers/{oid}/withdraw')
def withdraw_offer(oid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone()
    if not o: c.close(); raise HTTPException(404,'Offer not found')
    if o['status'] not in ('AWAITING_RESPONSE','DRAFT'): c.close(); raise HTTPException(409,'Offer cannot be withdrawn in its current state')
    at=now(); c.execute('UPDATE offers SET status="WITHDRAWN" WHERE offer_id=?',(oid,)); event(c,o['transaction_id'],'OFFER_WITHDRAWN',None,{'offer_id':oid,'withdrawn_at':at}); c.commit(); c.close(); return {'offer_id':oid,'status':'WITHDRAWN','withdrawn_at':at}

@app.post('/api/offers/{oid}/expire')
def expire_offer_api(oid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone()
    if not o: c.close(); raise HTTPException(404,'Offer not found')
    at=now(); c.execute('UPDATE offers SET status="EXPIRED" WHERE offer_id=? AND status="AWAITING_RESPONSE"',(oid,)); event(c,o['transaction_id'],'OFFER_EXPIRED',None,{'offer_id':oid,'expired_at':at}); c.commit(); c.close(); return {'offer_id':oid,'status':'EXPIRED','expired_at':at}

@app.post('/api/transactions/{tid}/communications')
def add_communication(tid:str,x:CommunicationIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn()
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    cid=uid('com'); c.execute('INSERT INTO transaction_communications VALUES (?,?,?,?,?,?,?,?,?,?)',(cid,tid,x.channel,x.sender or u,x.recipient,x.message,'RECORDED',x.related_type,x.related_id,now()))
    event(c,tid,'COMMUNICATION_RECORDED',None,{'communication_id':cid,'channel':x.channel,'related_type':x.related_type,'related_id':x.related_id}); c.commit(); r=dict(c.execute('SELECT * FROM transaction_communications WHERE communication_id=?',(cid,)).fetchone()); c.close(); return r

@app.post('/api/transactions/{tid}/risks')
def add_risk(tid:str,x:RiskIn,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn()
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    rid=uid('risk'); c.execute('INSERT INTO transaction_risks VALUES (?,?,?,?,?,?,?,?,?)',(rid,tid,x.severity,x.category,x.title,x.detail,'OPEN',now(),None)); event(c,tid,'RISK_FLAGGED',None,{'risk_id':rid,'severity':x.severity,'category':x.category,'title':x.title}); c.commit(); r=dict(c.execute('SELECT * FROM transaction_risks WHERE risk_id=?',(rid,)).fetchone()); c.close(); return r

@app.get('/api/transactions/{tid}/risks')
def list_risks(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rs=c.execute('SELECT * FROM transaction_risks WHERE transaction_id=? ORDER BY created_at DESC',(tid,)).fetchall(); c.close(); return [dict(x) for x in rs]

@app.post('/api/transactions/{tid}/pause')
def pause_transaction(tid:str,x:PauseIn,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn();
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    c.execute('INSERT OR REPLACE INTO transaction_controls(transaction_id,paused,pause_reason,updated_at) VALUES (?,?,?,?)',(tid,1,x.reason,now())); event(c,tid,'TRANSACTION_PAUSED',None,{'reason':x.reason}); c.commit(); c.close(); return {'transaction_id':tid,'paused':True,'reason':x.reason}

@app.post('/api/transactions/{tid}/resume')
def resume_transaction(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); c.execute('INSERT OR REPLACE INTO transaction_controls(transaction_id,paused,pause_reason,updated_at) VALUES (?,?,?,?)',(tid,0,None,now())); event(c,tid,'TRANSACTION_RESUMED'); c.commit(); c.close(); return {'transaction_id':tid,'paused':False}

@app.post('/api/transactions/{tid}/ai-orchestrate')
def ai_orchestrate(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn();
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    ensure_control(c,tid); ctl=c.execute('SELECT * FROM transaction_controls WHERE transaction_id=?',(tid,)).fetchone()
    tasks=[dict(x) for x in c.execute('SELECT * FROM transaction_tasks WHERE transaction_id=? ORDER BY sequence,created_at',(tid,)).fetchall()]
    risks=[dict(x) for x in c.execute('SELECT * FROM transaction_risks WHERE transaction_id=? AND status!=\"RESOLVED\"',(tid,)).fetchall()]
    if ctl['paused']:
        c.close(); return {'transaction_id':tid,'automated_items':[],'escalations':['Transaction is paused. Human action is required to resume it.'],'next_action':None,'message':'AI monitoring is paused with the transaction.'}
    automated=[]; escalations=[]
    # Safe administrative automation only: never mark conditions, signatures, financing, inspection, funds or closing complete.
    for t in tasks:
        meta=json.loads(t['metadata_json'] or '{}')
        if t['status']=='OPEN' and meta.get('automation_level') in ('ASSISTED','AUTO'):
            if meta.get('type')=='deposit':
                automated.append('Prepared deposit payment instructions and receipt-tracking task')
            elif meta.get('type')=='documents':
                automated.append('Prepared document package and mapping review')
    # Detect obvious inconsistencies from stored task/document labels without making legal conclusions.
    doc_rows=c.execute('SELECT name,status FROM documents WHERE transaction_id=?',(tid,)).fetchall()
    if len(doc_rows)>1 and len({r['status'] for r in doc_rows})>1:
        escalations.append('Document package contains mixed statuses; review required before automation continues.')
    for r in risks:
        if r['severity']=='HIGH': escalations.append(r['title'])
    open_tasks=[t for t in tasks if t['status']!='COMPLETED']
    next_action=open_tasks[0] if open_tasks else None
    event(c,tid,'AI_ORCHESTRATION_RUN',None,{'automated_items':automated,'escalations':escalations,'next_task_id':next_action['task_id'] if next_action else None})
    c.commit(); c.close()
    return {'transaction_id':tid,'automated_items':automated,'escalations':escalations,'next_action':next_action,'message':'AI advanced only administrative work it can safely prepare. Human decisions remain required for legally significant actions.'}


def evaluate_transaction_state(c,tid):
    tx=c.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    if not tx: raise HTTPException(404,'Transaction not found')
    ctl=c.execute('SELECT * FROM transaction_controls WHERE transaction_id=?',(tid,)).fetchone()
    if ctl and ctl['paused']:
        return {'state':'PAUSED','priority':'HOLD','next_action':None,'automated_items':[],'escalations':[ctl['pause_reason'] or 'Transaction is paused for human review.'],'reason':'Paused transactions are monitored but not advanced.'}
    risks=[dict(r) for r in c.execute('SELECT * FROM transaction_risks WHERE transaction_id=? AND status!="RESOLVED" ORDER BY CASE severity WHEN "HIGH" THEN 0 WHEN "MEDIUM" THEN 1 ELSE 2 END,created_at DESC',(tid,)).fetchall()]
    high=next((r for r in risks if r['severity']=='HIGH'),None)
    if high:
        return {'state':'EXCEPTION','priority':'HOLD','next_action':{'title':'Resolve transaction risk','label':high['title'],'detail':high['detail'],'owner':'Human review'},'automated_items':[],'escalations':[r['title'] for r in risks if r['severity'] in ('HIGH','MEDIUM')],'reason':'A high-severity risk blocks safe automation.'}
    dep=c.execute('SELECT * FROM deposits WHERE transaction_id=? ORDER BY created_at DESC LIMIT 1',(tid,)).fetchone()
    if dep and dep['status'] in ('REQUIRED','PAYMENT_INITIATED'):
        return {'state':'POST_ACCEPTANCE','priority':'ACTION','next_action':{'title':'Complete deposit','label':'Deposit','detail':f"Deposit of ${dep['required_amount_cents']/100:,.2f} must be completed and independently confirmed.",'owner':'Buyer','automation_prepared':True},'automated_items':['Deposit obligation and payment workflow are prepared.'],'escalations':[r['title'] for r in risks if r['severity']=='MEDIUM'],'reason':'The accepted transaction has an outstanding deposit obligation.'}
    tasks=[dict(t) for t in c.execute('SELECT * FROM transaction_tasks WHERE transaction_id=? ORDER BY sequence,created_at',(tid,)).fetchall()]
    open_tasks=[t for t in tasks if t['status']!='COMPLETED']
    if open_tasks:
        t=open_tasks[0]; meta=json.loads(t.get('metadata_json') or '{}')
        label=t['label']; detail=f"{label} is assigned to {t['owner']}. TransactionOS can prepare the administrative work, but the responsible party must complete the action."
        return {'state':'POST_ACCEPTANCE','priority':'ACTION','next_action':{'title':label,'label':label,'detail':detail,'owner':t['owner'],'due_at':t['due_at'],'task_id':t['task_id'],'automation_prepared':meta.get('automation_level') in ('ASSISTED','AUTO')},'automated_items':[f'Prepared task context for {label}.'],'escalations':[r['title'] for r in risks if r['severity']=='MEDIUM'],'reason':'The workflow engine found the earliest incomplete required task.'}
    return {'state':'READY_FOR_CLOSING','priority':'COMPLETE','next_action':None,'automated_items':['All current workflow tasks are complete.'],'escalations':[r['title'] for r in risks if r['severity']=='MEDIUM'],'reason':'No open workflow task remains.'}

@app.post('/api/transactions/{tid}/brain/evaluate')
def brain_evaluate(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); result=evaluate_transaction_state(c,tid)
    eid=uid('brain'); c.execute('INSERT INTO brain_evaluations VALUES (?,?,?,?,?,?,?,?,?)',(eid,tid,result['state'],result['priority'],json.dumps(result['next_action']) if result['next_action'] else None,json.dumps(result['automated_items']),json.dumps(result['escalations']),result['reason'],now()))
    event(c,tid,'BRAIN_EVALUATED',None,{'evaluation_id':eid,'state':result['state'],'priority':result['priority']})
    c.commit(); c.close(); result['evaluation_id']=eid; return result

@app.get('/api/transactions/{tid}/brain/history')
def brain_history(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rows=c.execute('SELECT * FROM brain_evaluations WHERE transaction_id=? ORDER BY created_at DESC LIMIT 25',(tid,)).fetchall(); c.close()
    return [dict(r, next_action=json.loads(r['next_action_json']) if r['next_action_json'] else None, automated_items=json.loads(r['automated_json'] or '[]'), escalations=json.loads(r['escalations_json'] or '[]')) for r in rows]

@app.get('/api/health')
def health(): return {'ok':True,'version':'3.3.4','database':'sqlite','features':['property-service','offer-lifecycle','transaction-engine','deposit-ledger','transaction-tasks','identity-gate','ai-orchestration','risk-escalation','communications','pause-resume','recovery','transaction-brain','deterministic-state-engine','brain-evaluation-history','authentication','session-management','identity-linked-transactions']}
@app.post('/api/auth/register')
def register(x:AuthIn):
    c=conn();
    try:
        u=uid('usr'); c.execute('INSERT INTO users VALUES (?,?,?,?)',(u,x.email.lower().strip(),pwd_hash(x.password),now())); c.commit(); return {'user_id':u,'email':x.email.lower().strip()}
    except sqlite3.IntegrityError: raise HTTPException(409,'Email already registered')
    finally: c.close()
@app.post('/api/auth/login')
def login(x:AuthIn):
    c=conn(); r=c.execute('SELECT * FROM users WHERE email=?',(x.email.lower().strip(),)).fetchone()
    if not r or not pwd_ok(x.password,r['password_hash']): c.close(); raise HTTPException(401,'Invalid credentials')
    tok=secrets.token_urlsafe(32); exp=datetime.fromtimestamp(datetime.now(timezone.utc).timestamp()+86400,timezone.utc).isoformat(); c.execute('INSERT INTO sessions VALUES (?,?,?,?)',(tok,r['user_id'],now(),exp)); c.commit(); c.close(); return {'access_token':tok,'token_type':'bearer','expires_at':exp,'user_id':r['user_id']}
@app.get('/api/auth/me')
def me(authorization:str|None=Header(default=None)): 
    u=auth(authorization); c=conn(); r=c.execute('SELECT user_id,email,created_at FROM users WHERE user_id=?',(u,)).fetchone(); c.close(); return dict(r)

def normalize_address(address: str) -> str:
    return ' '.join(address.strip().replace('\n', ' ').split())

def infer_jurisdiction(country: str|None, region: str|None, city: str|None) -> str|None:
    c=(country or '').strip().lower(); r=(region or '').strip().lower(); ci=(city or '').strip().lower()
    if c in {'canada','ca'}:
        if r in {'ontario','on'}:
            return 'CA-ON-TORONTO' if ci == 'toronto' else 'CA-ON'
        return 'CA'
    if c in {'united states','usa','us'}: return 'US'
    if c in {'thailand','th'}: return 'TH'
    if c in {'united kingdom','uk','gb'}: return 'GB'
    if c in {'australia','au'}: return 'AU'
    return None

@app.post('/api/properties/resolve')
def resolve_property(x:PropertyResolveIn, authorization:str|None=Header(default=None)):
    u=auth(authorization)
    address=normalize_address(x.address)
    if len(address) < 5: raise HTTPException(422,'A usable property address is required')
    jurisdiction=infer_jurisdiction(x.country,x.region,x.city)
    c=conn()
    # Local canonicalization layer: provider-neutral now; a real address provider plugs into this boundary later.
    r=c.execute('SELECT * FROM properties WHERE lower(address_line_1)=lower(?) AND lower(coalesce(city,""))=lower(coalesce(?,"")) AND lower(coalesce(region,""))=lower(coalesce(?,"")) AND lower(coalesce(country,""))=lower(coalesce(?,"")) LIMIT 1',(address,x.city,x.region,x.country)).fetchone()
    if r:
        c.close(); out=dict(r); out['resolution_source']='local_canonical_store'; out['created']=False; return out
    pid=uid('prop')
    c.execute('INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?)',(pid,address,x.city,x.region,x.postal_code,x.country,None,None,x.property_type,jurisdiction,now()))
    c.commit(); r=c.execute('SELECT * FROM properties WHERE property_id=?',(pid,)).fetchone(); c.close()
    out=dict(r); out['resolution_source']='local_canonical_store'; out['created']=True; return out

@app.get('/api/properties')
def search_properties(q:str|None=None,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn()
    if q:
        like=f'%{q.strip()}%'
        rs=c.execute('SELECT * FROM properties WHERE address_line_1 LIKE ? OR city LIKE ? OR region LIKE ? OR country LIKE ? ORDER BY created_at DESC LIMIT 25',(like,like,like,like)).fetchall()
    else:
        rs=c.execute('SELECT * FROM properties ORDER BY created_at DESC LIMIT 25').fetchall()
    c.close(); return [dict(r) for r in rs]

@app.post('/api/properties')
def create_property(x:PropertyIn, authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); p=uid('prop'); c.execute('INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?,?,?)',(p,x.address_line_1,x.city,x.region,x.postal_code,x.country,x.latitude,x.longitude,x.property_type,x.jurisdiction,now())); c.commit(); c.close(); return {'property_id':p,**x.model_dump()}
@app.get('/api/properties/{pid}')
def get_property(pid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM properties WHERE property_id=?',(pid,)).fetchone(); c.close();
    if not r: raise HTTPException(404,'Property not found')
    return dict(r)
@app.post('/api/transactions')
def create_tx(x:TxIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn();
    if not c.execute('SELECT 1 FROM properties WHERE property_id=?',(x.property_id,)).fetchone(): c.close(); raise HTTPException(404,'Property not found')
    t=uid('txn'); c.execute('INSERT INTO transactions VALUES (?,?,?,?,?)',(t,x.property_id,'INITIATED',u,now())); event(c,t,'TRANSACTION_CREATED',None); c.commit(); c.close(); return {'transaction_id':t,'property_id':x.property_id,'status':'INITIATED'}
@app.get('/api/transactions/{tid}')
def get_tx(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone();
    if not r: c.close(); raise HTTPException(404,'Transaction not found')
    out=dict(r); out['conditions']=[dict(x) for x in c.execute('SELECT * FROM conditions WHERE transaction_id=?',(tid,))]; out['documents']=[dict(x) for x in c.execute('SELECT * FROM documents WHERE transaction_id=?',(tid,))]; out['events']=[dict(x) for x in c.execute('SELECT * FROM events WHERE transaction_id=? ORDER BY occurred_at',(tid,))]; c.close(); return out
@app.post('/api/transactions/{tid}/offers')
def create_offer(tid:str,x:OfferIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn();
    if tid!=x.transaction_id or not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    oid=uid('offer'); c.execute('INSERT INTO offers VALUES (?,?,?,?,?,?,?)',(oid,tid,'DRAFT',None,0,u,now())); event(c,tid,'OFFER_CREATED',None,{'offer_id':oid}); c.commit(); c.close(); return {'offer_id':oid,'transaction_id':tid,'status':'DRAFT'}
@app.post('/api/identity/verify')
def verify_identity(x:IdentityIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn()
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(x.transaction_id,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    vid=uid('idv'); at=now()
    c.execute('INSERT INTO identity_verifications VALUES (?,?,?,?,?,?,?,?,?)',(vid,x.transaction_id,u,x.legal_name,x.email,'VERIFIED',x.method,at,at))
    event(c,x.transaction_id,'BUYER_IDENTITY_VERIFIED',None,{'verification_id':vid,'method':x.method,'legal_name':x.legal_name})
    c.commit(); c.close(); return {'verification_id':vid,'transaction_id':x.transaction_id,'status':'VERIFIED','legal_name':x.legal_name,'verified_at':at}

@app.get('/api/transactions/{tid}/identity')
def get_identity(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM identity_verifications WHERE transaction_id=? ORDER BY verified_at DESC LIMIT 1',(tid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,'Buyer identity not verified')
    return dict(r)

@app.post('/api/signatures')
def create_signature(x:SignatureIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn()
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(x.transaction_id,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    # Prototype signature evidence is intentionally simple; production uses a qualified e-sign provider.
    sid=uid('sig'); at=now(); evidence={'method':x.method,'legal_name':x.legal_name,'signature_data':x.signature_data,'recorded_at':at,'prototype':True}
    c.execute('INSERT INTO signatures VALUES (?,?,?,?,?,?,?)',(sid,x.transaction_id,x.document_id,None,'SIGNED',at,json.dumps(evidence)))
    event(c,x.transaction_id,'SIGNATURE_COMPLETED',None,{'signature_id':sid,'document_id':x.document_id,'method':x.method,'prototype':True})
    c.commit(); c.close(); return {'signature_id':sid,'transaction_id':x.transaction_id,'status':'SIGNED','signed_at':at,'evidence':evidence}

@app.get('/api/transactions/{tid}/signatures')
def get_signatures(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rs=c.execute('SELECT * FROM signatures WHERE transaction_id=? ORDER BY signed_at',(tid,)).fetchall(); c.close(); return [dict(r) for r in rs]

@app.post('/api/offers/{oid}/versions')
def add_version(oid:str,x:VersionIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone();
    if not o: c.close(); raise HTTPException(404,'Offer not found')
    # Initial buyer submission is gated by identity + signature. Subsequent negotiation versions inherit the verified transaction.
    if o['current_version_number']==0: require_ready_for_submission(c,o['transaction_id'])
    n=o['current_version_number']+1; vid=uid('ver'); c.execute('UPDATE offer_versions SET status="PRESERVED" WHERE offer_id=? AND status="CURRENT"',(oid,)); c.execute('INSERT INTO offer_versions VALUES (?,?,?,?,?,?,?,?,?)',(vid,oid,n,x.actor_party_id,'CURRENT',json.dumps(x.payload),now(),None,x.deadline_at)); c.execute('UPDATE offers SET status="AWAITING_RESPONSE",current_version_id=?,current_version_number=? WHERE offer_id=?',(vid,n,oid)); c.execute('UPDATE transactions SET status="NEGOTIATING" WHERE transaction_id=?',(o['transaction_id'],)); event(c,o['transaction_id'],'OFFER_VERSION_SUBMITTED',x.actor_party_id,{'offer_id':oid,'version_id':vid,'version_number':n}); c.commit(); c.close(); return {'version_id':vid,'version_number':n,'status':'CURRENT'}
@app.post('/api/offers/{oid}/accept')
def accept(oid:str,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone();
    if not o or not o['current_version_id']: c.close(); raise HTTPException(400,'No current offer version')
    v=c.execute('SELECT * FROM offer_versions WHERE version_id=?',(o['current_version_id'],)).fetchone();
    if not v: c.close(); raise HTTPException(400,'Current offer version not found')
    at=now(); payload=json.loads(v['payload_json'] or '{}')
    c.execute('UPDATE offer_versions SET status="ACCEPTED",accepted_at=? WHERE version_id=?',(at,v['version_id']))
    c.execute('UPDATE offers SET status="ACCEPTED" WHERE offer_id=?',(oid,))
    c.execute('UPDATE transactions SET status="ACTIVE" WHERE transaction_id=?',(o['transaction_id'],))
    tid=o['transaction_id']
    event(c,tid,'OFFER_ACCEPTED',None,{'offer_id':oid,'offer_version_id':v['version_id'],'accepted_at':at})

    # Turn the accepted agreement into a real persisted transaction work queue.
    # This is intentionally a demo ruleset; production rules will be jurisdiction/form driven.
    existing=c.execute('SELECT COUNT(*) n FROM transaction_tasks WHERE transaction_id=?',(tid,)).fetchone()['n']
    if not existing:
        due_date=None
        closing_text=payload.get('closing') or ''
        try:
            import re
            m=re.search(r'([A-Za-z]+ \d{1,2}, \d{4})',closing_text)
            if m: due_date=datetime.strptime(m.group(1),'%B %d, %Y').replace(tzinfo=timezone.utc).isoformat()
        except Exception: due_date=None
        conditions=payload.get('conditions') or []
        task_defs=[]
        if payload.get('deposit') and str(payload.get('deposit')).strip() not in ('—','$0'):
            task_defs.append(('Deposit','Buyer',None,0,{'type':'deposit','automation_level':'ASSISTED'}))
        for i,label in enumerate(conditions,1):
            task_defs.append((str(label).strip(),'Buyer',None,i,{'type':'condition','automation_level':'MANUAL'}))
        task_defs += [
            ('Purchase agreement & schedules','Both parties',None,20,{'type':'documents'}),
            ('E-signature package','Both parties',None,30,{'type':'signatures','automation_level':'MANUAL'}),
            ('Closing readiness','Both parties',due_date,40,{'type':'closing'}),
        ]
        for label,owner,due,seq,meta in task_defs:
            c.execute('INSERT INTO transaction_tasks VALUES (?,?,?,?,?,?,?,?,?,?)',(uid('task'),tid,label,owner,'OPEN',due,seq,json.dumps(meta),now(),None))
            event(c,tid,'TASK_CREATED',None,{'label':label,'owner':owner,'sequence':seq})

    # Create a transaction document record from the accepted offer.
    if not c.execute('SELECT 1 FROM documents WHERE transaction_id=?',(tid,)).fetchone():
        c.execute('INSERT INTO documents VALUES (?,?,?,?,?)',(uid('doc'),tid,'Purchase agreement · prepared from accepted offer','READY_FOR_REVIEW','demo://accepted-offer'))
        event(c,tid,'DOCUMENT_PREPARED',None,{'document':'Purchase agreement · prepared from accepted offer','demo':True})

    # Create the deposit obligation once, based on the accepted offer.
    raw=str(payload.get('deposit') or '')
    import re
    nums=re.sub(r'[^0-9.]','',raw)
    try: amount_cents=round(float(nums)*100) if nums else 0
    except Exception: amount_cents=0
    if amount_cents and not c.execute('SELECT 1 FROM deposits WHERE transaction_id=? AND status NOT IN ("REFUNDED","RELEASED","CANCELLED")',(tid,)).fetchone():
        did=uid('dep'); c.execute('INSERT INTO deposits VALUES (?,?,?,?,?,?,?,?,?,?,?)',(did,tid,amount_cents,'REQUIRED',None,None,None,None,None,None,now()))
        event(c,tid,'DEPOSIT_REQUIRED',None,{'deposit_id':did,'amount_cents':amount_cents,'source':'accepted_offer'})

    c.commit(); c.close(); return {'status':'ACCEPTED','offer_version_id':v['version_id'],'accepted_at':at,'transaction_id':tid}

@app.get('/api/transactions/{tid}/tasks')
def get_tasks(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn();
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone(): c.close(); raise HTTPException(404,'Transaction not found')
    rs=c.execute('SELECT * FROM transaction_tasks WHERE transaction_id=? ORDER BY sequence,created_at',(tid,)).fetchall(); c.close(); return [dict(r) for r in rs]

@app.post('/api/transactions/{tid}/ai-next-action')
def ai_next_action(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn()
    tx=c.execute('SELECT * FROM transactions WHERE transaction_id=?',(tid,)).fetchone()
    if not tx: c.close(); raise HTTPException(404,'Transaction not found')
    ensure_control(c,tid)
    ctl=c.execute('SELECT * FROM transaction_controls WHERE transaction_id=?',(tid,)).fetchone()
    rs=c.execute('SELECT * FROM transaction_tasks WHERE transaction_id=? ORDER BY sequence,created_at',(tid,)).fetchall()
    if not rs: c.close(); raise HTTPException(404,'No workflow tasks found')
    risks=[dict(r) for r in c.execute('SELECT * FROM transaction_risks WHERE transaction_id=? AND status!="RESOLVED" ORDER BY CASE severity WHEN "HIGH" THEN 0 WHEN "MEDIUM" THEN 1 ELSE 2 END,created_at DESC',(tid,)).fetchall()]
    if ctl['paused']:
        c.close(); return {'transaction_id':tid,'automated_items':[],'escalations':['Transaction is paused: '+(ctl['pause_reason'] or 'human review requested')],'next_action':None,'priority':'HOLD','message':'AI is monitoring but will not advance a paused transaction.'}
    open_tasks=[dict(r) for r in rs if r['status']!='COMPLETED']
    prepared=[]
    # Prepare, but never complete, safe administrative work. The metadata records the preparation state.
    for r in open_tasks:
        meta=json.loads(r['metadata_json'] or '{}')
        if meta.get('automation_level') in ('AUTO','ASSISTED') and not meta.get('ai_prepared'):
            meta['ai_prepared']=True; meta['ai_prepared_at']=now()
            c.execute('UPDATE transaction_tasks SET metadata_json=? WHERE task_id=?',(json.dumps(meta),r['task_id']))
            event(c,tid,'AI_TASK_PREPARED',None,{'task_id':r['task_id'],'label':r['label']})
            prepared.append(r['label'])
    # Highest priority: unresolved risk, then due dates, then workflow sequence.
    high=next((r for r in risks if r['severity']=='HIGH'),None)
    if high:
        next_action={'kind':'RISK','title':high['title'],'detail':high['detail'],'owner':'Human reviewer','source':'transaction_risk','risk_id':high['risk_id']}
        priority='HOLD'
    else:
        import datetime as _dt
        def task_key(t):
            due=t.get('due_at') or '9999-12-31T23:59:59+00:00'
            return (due,t.get('sequence',9999))
        nxt=min(open_tasks,key=task_key) if open_tasks else None
        if nxt:
            meta=json.loads(nxt.get('metadata_json') or '{}')
            priority='ACTION'
            next_action={'kind':'TASK','task_id':nxt['task_id'],'title':nxt['label'],'detail':'AI prepared what it safely can. The responsible party must complete the transactionally significant action.','owner':nxt['owner'],'due_at':nxt['due_at'],'automation_prepared':bool(json.loads(c.execute('SELECT metadata_json FROM transaction_tasks WHERE task_id=?',(nxt['task_id'],)).fetchone()['metadata_json'] or '{}').get('ai_prepared')),'source':'transaction_task'}
        else:
            priority='COMPLETE'; next_action=None
    event(c,tid,'AI_NEXT_ACTION_CALCULATED',None,{'priority':priority,'next_action':next_action,'prepared_count':len(prepared)})
    c.commit(); c.close()
    return {'transaction_id':tid,'automated_items':prepared,'escalations':[r['title'] for r in risks if r['severity'] in ('HIGH','MEDIUM')],'next_action':next_action,'priority':priority,'message':'AI prepared safe administrative work without completing human-controlled actions.'}

@app.post('/api/tasks/{task_id}/complete')
def complete_task(task_id:str,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); r=c.execute('SELECT * FROM transaction_tasks WHERE task_id=?',(task_id,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Task not found')
    if r['status']=='COMPLETED': c.close(); return dict(r)
    at=now(); c.execute('UPDATE transaction_tasks SET status="COMPLETED",completed_at=? WHERE task_id=?',(at,task_id)); event(c,r['transaction_id'],'TASK_COMPLETED',None,{'task_id':task_id,'label':r['label']}); c.commit(); out=dict(c.execute('SELECT * FROM transaction_tasks WHERE task_id=?',(task_id,)).fetchone()); c.close(); return out

@app.get('/api/offers/{oid}')
def get_offer(oid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone()
    if not o: c.close(); raise HTTPException(404,'Offer not found')
    out=dict(o); out['versions']=[dict(v) for v in c.execute('SELECT * FROM offer_versions WHERE offer_id=? ORDER BY version_number',(oid,))]; c.close(); return out
@app.get('/api/offers/{oid}/versions')
def get_offer_versions(oid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rs=c.execute('SELECT * FROM offer_versions WHERE offer_id=? ORDER BY version_number',(oid,)).fetchall(); c.close(); return [dict(r) for r in rs]

class DepositIn(BaseModel):
    amount_cents:int=Field(gt=0)
    provider_ref:str|None=None

@app.post('/api/transactions/{tid}/deposit')
def create_deposit(tid:str,x:DepositIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn();
    if not c.execute('SELECT 1 FROM transactions WHERE transaction_id=?',(tid,)).fetchone():
        c.close(); raise HTTPException(404,'Transaction not found')
    existing=c.execute('SELECT * FROM deposits WHERE transaction_id=? ORDER BY created_at DESC LIMIT 1',(tid,)).fetchone()
    if existing and existing['status'] not in ('REFUNDED','RELEASED','CANCELLED'):
        c.close(); raise HTTPException(409,'An active deposit already exists for this transaction')
    did=uid('dep'); c.execute('INSERT INTO deposits VALUES (?,?,?,?,?,?,?,?,?,?,?)',(did,tid,x.amount_cents,'REQUIRED',x.provider_ref,None,None,None,None,None,now()))
    event(c,tid,'DEPOSIT_REQUIRED',None,{'deposit_id':did,'amount_cents':x.amount_cents})
    c.commit(); r=c.execute('SELECT * FROM deposits WHERE deposit_id=?',(did,)).fetchone(); c.close(); return dict(r)

@app.get('/api/transactions/{tid}/deposit')
def get_deposit(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM deposits WHERE transaction_id=? ORDER BY created_at DESC LIMIT 1',(tid,)).fetchone(); c.close()
    if not r: raise HTTPException(404,'No deposit record for transaction')
    return dict(r)

@app.post('/api/deposits/{did}/simulate-receipt')
def simulate_deposit_receipt(did:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM deposits WHERE deposit_id=?',(did,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Deposit not found')
    if r['status']!='REQUIRED': c.close(); raise HTTPException(409,'Deposit is not awaiting payment')
    at=now(); provider_ref=r['provider_ref'] or 'DEMO-TRUST-'+secrets.token_hex(4).upper(); c.execute('UPDATE deposits SET status="HELD",provider_ref=?,received_at=?,held_at=? WHERE deposit_id=?',(provider_ref,at,at,did)); event(c,r['transaction_id'],'DEPOSIT_RECEIVED',None,{'deposit_id':did,'provider_ref':provider_ref,'simulated':True}); c.commit(); out=dict(c.execute('SELECT * FROM deposits WHERE deposit_id=?',(did,)).fetchone()); c.close(); return out

@app.post('/api/deposits/{did}/simulate-release')
def simulate_deposit_release(did:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); r=c.execute('SELECT * FROM deposits WHERE deposit_id=?',(did,)).fetchone()
    if not r: c.close(); raise HTTPException(404,'Deposit not found')
    if r['status']!='HELD': c.close(); raise HTTPException(409,'Only a held deposit can be released in this demo')
    at=now(); c.execute('UPDATE deposits SET status="RELEASED",released_at=? WHERE deposit_id=?',(at,did)); event(c,r['transaction_id'],'DEPOSIT_RELEASED',None,{'deposit_id':did,'simulated':True}); c.commit(); out=dict(c.execute('SELECT * FROM deposits WHERE deposit_id=?',(did,)).fetchone()); c.close(); return out

@app.get('/api/transactions/{tid}/events')
def events(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rs=c.execute('SELECT * FROM events WHERE transaction_id=? ORDER BY occurred_at',(tid,)).fetchall(); c.close(); return [dict(r) for r in rs]
