from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import sqlite3, json, os, secrets, hashlib, hmac
from datetime import datetime, timezone

BASE=os.path.dirname(__file__); DB=os.path.join(BASE,'transactionos.db')
app=FastAPI(title='TransactionOS API', version='2.1.0')
app.add_middleware(CORSMiddleware, allow_origins=['*'], allow_methods=['*'], allow_headers=['*'])

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

class AuthIn(BaseModel): email:str; password:str=Field(min_length=8)
class PropertyIn(BaseModel): address_line_1:str; city:str|None=None; region:str|None=None; postal_code:str|None=None; country:str|None=None; latitude:float|None=None; longitude:float|None=None; property_type:str|None=None; jurisdiction:str|None=None
class TxIn(BaseModel): property_id:str
class OfferIn(BaseModel): transaction_id:str
class VersionIn(BaseModel): actor_party_id:str|None=None; payload:dict; deadline_at:str|None=None

@app.get('/api/health')
def health(): return {'ok':True,'version':'2.1.0','database':'sqlite'}
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
@app.post('/api/offers/{oid}/versions')
def add_version(oid:str,x:VersionIn,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone();
    if not o: c.close(); raise HTTPException(404,'Offer not found')
    n=o['current_version_number']+1; vid=uid('ver'); c.execute('UPDATE offer_versions SET status="PRESERVED" WHERE offer_id=? AND status="CURRENT"',(oid,)); c.execute('INSERT INTO offer_versions VALUES (?,?,?,?,?,?,?,?,?)',(vid,oid,n,x.actor_party_id,'CURRENT',json.dumps(x.payload),now(),None,x.deadline_at)); c.execute('UPDATE offers SET status="AWAITING_RESPONSE",current_version_id=?,current_version_number=? WHERE offer_id=?',(vid,n,oid)); c.execute('UPDATE transactions SET status="NEGOTIATING" WHERE transaction_id=?',(o['transaction_id'],)); event(c,o['transaction_id'],'OFFER_VERSION_SUBMITTED',x.actor_party_id,{'offer_id':oid,'version_id':vid,'version_number':n}); c.commit(); c.close(); return {'version_id':vid,'version_number':n,'status':'CURRENT'}
@app.post('/api/offers/{oid}/accept')
def accept(oid:str,authorization:str|None=Header(default=None)):
    u=auth(authorization); c=conn(); o=c.execute('SELECT * FROM offers WHERE offer_id=?',(oid,)).fetchone();
    if not o or not o['current_version_id']: c.close(); raise HTTPException(400,'No current offer version')
    v=c.execute('SELECT * FROM offer_versions WHERE version_id=?',(o['current_version_id'],)).fetchone(); at=now(); c.execute('UPDATE offer_versions SET status="ACCEPTED",accepted_at=? WHERE version_id=?',(at,v['version_id'])); c.execute('UPDATE offers SET status="ACCEPTED" WHERE offer_id=?',(oid,)); c.execute('UPDATE transactions SET status="ACCEPTED" WHERE transaction_id=?',(o['transaction_id'],)); event(c,o['transaction_id'],'OFFER_ACCEPTED',None,{'offer_id':oid,'offer_version_id':v['version_id'],'accepted_at':at}); c.commit(); c.close(); return {'status':'ACCEPTED','offer_version_id':v['version_id'],'accepted_at':at}
@app.get('/api/transactions/{tid}/events')
def events(tid:str,authorization:str|None=Header(default=None)):
    auth(authorization); c=conn(); rs=c.execute('SELECT * FROM events WHERE transaction_id=? ORDER BY occurred_at',(tid,)).fetchall(); c.close(); return [dict(r) for r in rs]
