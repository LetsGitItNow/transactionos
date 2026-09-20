// TransactionOS v2.2 API client. The browser talks to the local HTTP API when available.
const TransactionOSAPI = (() => {
  const BASE = '/api';
  let token = localStorage.getItem('transactionos_token') || '';
  const fallback = { properties: {}, transactions: {}, offers: {}, events: [], deposits: {} };
  const now = () => new Date().toISOString();
  const id = p => `${p}_${Math.random().toString(36).slice(2,10)}`;
  const mockEvent = (transactionId,type,actorPartyId,metadata={}) => { const e={event_id:id('evt'),transaction_id:transactionId,type,actor_party_id:actorPartyId,occurred_at:now(),metadata}; fallback.events.push(e); return e; };

  async function request(path, options={}) {
    const headers = {'Content-Type':'application/json', ...(options.headers||{})};
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(BASE+path, {...options, headers});
    if (!res.ok) { let detail='API request failed'; try { const body=await res.json(); detail=body.detail||detail; } catch {} throw new Error(detail); }
    return res.status===204 ? null : res.json();
  }

  async function ensureDemoAuth(){
    if(token) { try { await request('/auth/me'); return true; } catch { token=''; localStorage.removeItem('transactionos_token'); } }
    const email='demo@transactionos.local', password='TransactionOS-Demo-2026!';
    try { await request('/auth/register',{method:'POST',body:JSON.stringify({email,password})}); } catch(e) { /* already registered is fine */ }
    try { const r=await request('/auth/login',{method:'POST',body:JSON.stringify({email,password})); token=r.access_token; localStorage.setItem('transactionos_token',token); return true; } catch { return false; }
  }

  async function localOrMock(fn, mockFn){
    try { if(await ensureDemoAuth()) return await fn(); } catch(e) { console.warn('TransactionOS API fallback:',e.message); }
    return mockFn();
  }

  return {
    async ensureReady(){ return ensureDemoAuth(); },
    async resolveProperty(input){
      return localOrMock(
        ()=>request('/properties/resolve',{method:'POST',body:JSON.stringify(input)}),
        ()=>{ const p={property_id:id('prop'),address_line_1:input.address,city:input.city||null,region:input.region||null,country:input.country||null,property_type:input.property_type||null,jurisdiction:null,resolution_source:'browser_mock',created:true}; fallback.properties[p.property_id]=p; return p; }
      );
    },
    async searchProperties(q=''){
      return localOrMock(()=>request('/properties'+(q?`?q=${encodeURIComponent(q)}`:'')),()=>Object.values(fallback.properties).filter(p=>!q || JSON.stringify(p).toLowerCase().includes(q.toLowerCase())));
    },
    async createProperty(input){ return localOrMock(()=>request('/properties',{method:'POST',body:JSON.stringify(input)}),()=>{const p={property_id:id('prop'),...input};fallback.properties[p.property_id]=p;return p;}); },
    async getProperty(propertyId){ return localOrMock(()=>request(`/properties/${propertyId}`),()=>fallback.properties[propertyId]||null); },
    async createTransaction(input){ return localOrMock(()=>request('/transactions',{method:'POST',body:JSON.stringify({property_id:input.property_id})}),()=>{const t={transaction_id:id('txn'),status:'INITIATED',created_at:now(),...input};fallback.transactions[t.transaction_id]=t;mockEvent(t.transaction_id,'TRANSACTION_CREATED',input.actor_party_id||null);return t;}); },
    async getTransaction(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}`),()=>fallback.transactions[transactionId]||null); },
    async createOffer(input){ return localOrMock(()=>request(`/transactions/${input.transaction_id}/offers`,{method:'POST',body:JSON.stringify(input)}),()=>{const offer={offer_id:id('offer'),status:'DRAFT',current_version_id:null,versions:[],...input};fallback.offers[offer.offer_id]=offer;mockEvent(input.transaction_id,'OFFER_CREATED',input.actor_party_id||null);return offer;}); },
    async addOfferVersion(offerId,input){ return localOrMock(()=>request(`/offers/${offerId}/versions`,{method:'POST',body:JSON.stringify(input)}),()=>{const o=fallback.offers[offerId];if(!o)throw Error('Offer not found');const v={version_id:id('ver'),offer_id:offerId,version_number:o.versions.length+1,status:'CURRENT',submitted_at:now(),...input};o.versions.push(v);o.current_version_id=v.version_id;o.status='AWAITING_RESPONSE';mockEvent(o.transaction_id,'OFFER_VERSION_SUBMITTED',input.actor_party_id||null,{version_id:v.version_id});return v;}); },
    async acceptOffer(offerId){ return localOrMock(()=>request(`/offers/${offerId}/accept`,{method:'POST'}),()=>{const o=fallback.offers[offerId];const v=o?.versions.find(x=>x.version_id===o.current_version_id);if(!v)throw Error('No current version');v.status='ACCEPTED';v.accepted_at=now();o.status='ACCEPTED';return mockEvent(o.transaction_id,'OFFER_ACCEPTED',null,{offer_version_id:v.version_id,accepted_at:v.accepted_at});}); },
    async listEvents(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/events`),()=>fallback.events.filter(e=>e.transaction_id===transactionId)); },
    async createDeposit(transactionId, amountCents){ return localOrMock(()=>request(`/transactions/${transactionId}/deposit`,{method:'POST',body:JSON.stringify({amount_cents:amountCents})}),()=>{const d={deposit_id:id('dep'),transaction_id:transactionId,required_amount_cents:amountCents,status:'REQUIRED',created_at:now()};fallback.deposits[transactionId]=d;mockEvent(transactionId,'DEPOSIT_REQUIRED',null,{deposit_id:d.deposit_id,amount_cents:amountCents});return d;}); },
    async getDeposit(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/deposit`),()=>fallback.deposits[transactionId]||null); },
    async simulateDepositReceipt(depositId){ return localOrMock(()=>request(`/deposits/${depositId}/simulate-receipt`,{method:'POST'}),()=>{const d=Object.values(fallback.deposits).find(x=>x.deposit_id===depositId);if(!d)throw Error('Deposit not found');d.status='HELD';d.provider_ref='DEMO-TRUST-'+Math.random().toString(36).slice(2,8).toUpperCase();d.received_at=now();d.held_at=d.received_at;mockEvent(d.transaction_id,'DEPOSIT_RECEIVED',null,{deposit_id:depositId,provider_ref:d.provider_ref,simulated:true});return d;}); },
    async simulateDepositRelease(depositId){ return localOrMock(()=>request(`/deposits/${depositId}/simulate-release`,{method:'POST'}),()=>{const d=Object.values(fallback.deposits).find(x=>x.deposit_id===depositId);if(!d||d.status!=='HELD')throw Error('Deposit must be held');d.status='RELEASED';d.released_at=now();mockEvent(d.transaction_id,'DEPOSIT_RELEASED',null,{deposit_id:depositId,simulated:true});return d;}); }
  };
})();

window.addEventListener('DOMContentLoaded',()=>TransactionOSAPI.ensureReady().catch(()=>{}));
