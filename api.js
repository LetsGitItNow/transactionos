// TransactionOS v2.4 API client. The browser talks to the local HTTP API when available.
var TransactionOSAPI = (() => {
  const BASE = '/api';
  let token = localStorage.getItem('transactionos_token') || '';
  const fallback = { properties: {}, transactions: {}, offers: {}, events: [], deposits: {}, tasks: [], identity: {}, signatures: {}, communications: {}, risks: {} };
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
    return false;
  }

  async function login(email,password){
    const r=await request('/auth/login',{method:'POST',body:JSON.stringify({email,password})});
    token=r.access_token; localStorage.setItem('transactionos_token',token);
    return await request('/auth/me');
  }

  async function register(email,password){
    const r=await request('/auth/register',{method:'POST',body:JSON.stringify({email,password})});
    return r;
  }

  async function logout(){
    token=''; localStorage.removeItem('transactionos_token');
  }


  async function localOrMock(fn, mockFn){
    try { if(await ensureDemoAuth()) return await fn(); } catch(e) { console.warn('TransactionOS API fallback:',e.message); }
    return mockFn();
  }

  return {
    async ensureReady(){ return ensureDemoAuth(); },
    async login(email,password){ return login(email,password); },
    async register(email,password){ return register(email,password); },
    async logout(){ return logout(); },
    async getCurrentUser(){ try { if(!token) return null; return await request('/auth/me'); } catch { token=''; localStorage.removeItem('transactionos_token'); return null; } },
    isAuthenticated(){ return !!token; },
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
    async getOffer(offerId){ return localOrMock(()=>request(`/offers/${offerId}`),()=>fallback.offers[offerId]||null); },
    async acceptOffer(offerId){ return localOrMock(()=>request(`/offers/${offerId}/accept`,{method:'POST'}),()=>{const o=fallback.offers[offerId];const v=o?.versions.find(x=>x.version_id===o.current_version_id);if(!v)throw Error('No current version');v.status='ACCEPTED';v.accepted_at=now();o.status='ACCEPTED';return mockEvent(o.transaction_id,'OFFER_ACCEPTED',null,{offer_version_id:v.version_id,accepted_at:v.accepted_at});}); },
    async listOfferVersions(offerId){ return localOrMock(()=>request(`/offers/${offerId}/versions`),()=>fallback.offers[offerId]?.versions||[]); },
    async listEvents(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/events`),()=>fallback.events.filter(e=>e.transaction_id===transactionId)); },
    async listTasks(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/tasks`),()=>fallback.tasks.filter(t=>t.transaction_id===transactionId)); },
    async completeTask(taskId){ return localOrMock(()=>request(`/tasks/${taskId}/complete`,{method:'POST'}),()=>{ const t=fallback.tasks.find(x=>x.task_id===taskId); if(!t) throw Error('Task not found'); t.status='COMPLETED'; t.completed_at=now(); return t; }); },
    async verifyBuyerIdentity(input){ return localOrMock(()=>request('/identity/verify',{method:'POST',body:JSON.stringify(input)}),()=>{const r={verification_id:id('idv'),transaction_id:input.transaction_id,status:'VERIFIED',legal_name:input.legal_name,verified_at:now()};fallback.identity[input.transaction_id]=r;return r;}); },
    async getBuyerIdentity(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/identity`),()=>fallback.identity?.[transactionId]||null); },
    async getOverview(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/overview`),()=>({transaction_id:transactionId,tasks:fallback.tasks.filter(t=>t.transaction_id===transactionId),risks:Object.values(fallback.risks).filter(r=>r.transaction_id===transactionId),communications:Object.values(fallback.communications).filter(r=>r.transaction_id===transactionId),paused:false,next_action:null})); },
    async addRisk(transactionId,input){ return localOrMock(()=>request(`/transactions/${transactionId}/risks`,{method:'POST',body:JSON.stringify(input)}),()=>{const r={risk_id:id('risk'),transaction_id:transactionId,status:'OPEN',created_at:now(),...input};fallback.risks[r.risk_id]=r;return r;}); },
    async verifySellerAuthority(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/seller-verify`,{method:'POST'}),()=>({transaction_id:transactionId,status:'VERIFIED',authority_status:'VERIFIED',prototype:true})); },
    async aiOrchestrate(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/ai-orchestrate`,{method:'POST'}),()=>({transaction_id:transactionId,automated_items:[],escalations:[],next_action:null,message:'AI review complete.'})); },
    async withdrawOffer(offerId){ return localOrMock(()=>request(`/offers/${offerId}/withdraw`,{method:'POST'}),()=>({offer_id:offerId,status:'WITHDRAWN'})); },
    async expireOffer(offerId){ return localOrMock(()=>request(`/offers/${offerId}/expire`,{method:'POST'}),()=>({offer_id:offerId,status:'EXPIRED'})); },
    async addCommunication(transactionId,input){ return localOrMock(()=>request(`/transactions/${transactionId}/communications`,{method:'POST',body:JSON.stringify(input)}),()=>{const r={communication_id:id('com'),transaction_id:transactionId,status:'RECORDED',created_at:now(),...input};fallback.communications[r.communication_id]=r;mockEvent(transactionId,'COMMUNICATION_RECORDED',null,{communication_id:r.communication_id});return r;}); },
    async pauseTransaction(transactionId,reason){ return localOrMock(()=>request(`/transactions/${transactionId}/pause`,{method:'POST',body:JSON.stringify({reason})}),()=>({transaction_id:transactionId,paused:true,reason})); },
    async resumeTransaction(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/resume`,{method:'POST'}),()=>({transaction_id:transactionId,paused:false})); },
    async createSignature(input){ return localOrMock(()=>request('/signatures',{method:'POST',body:JSON.stringify(input)}),()=>({signature_id:id('sig'),transaction_id:input.transaction_id,status:'SIGNED',signed_at:now(),evidence:{method:input.method,legal_name:input.legal_name,prototype:true}})); },
    async listSignatures(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/signatures`),()=>[]); },
    async aiNextAction(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/ai-next-action`,{method:'POST'}),()=>({transaction_id:transactionId,automated_items:[],next_action:null,message:'AI review complete.'})); },
    async brainEvaluate(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/brain/evaluate`,{method:'POST'}),()=>({transaction_id:transactionId,state:'READY_FOR_CLOSING',priority:'COMPLETE',automated_items:[],escalations:[],next_action:null,reason:'No open workflow task remains.'})); },
    async brainHistory(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/brain/history`),()=>[]); },
    async createDeposit(transactionId, amountCents){ return localOrMock(()=>request(`/transactions/${transactionId}/deposit`,{method:'POST',body:JSON.stringify({amount_cents:amountCents})}),()=>{const d={deposit_id:id('dep'),transaction_id:transactionId,required_amount_cents:amountCents,status:'REQUIRED',created_at:now()};fallback.deposits[transactionId]=d;mockEvent(transactionId,'DEPOSIT_REQUIRED',null,{deposit_id:d.deposit_id,amount_cents:amountCents});return d;}); },
    async getDeposit(transactionId){ return localOrMock(()=>request(`/transactions/${transactionId}/deposit`),()=>fallback.deposits[transactionId]||null); },
    async simulateDepositReceipt(depositId){ return localOrMock(()=>request(`/deposits/${depositId}/simulate-receipt`,{method:'POST'}),()=>{const d=Object.values(fallback.deposits).find(x=>x.deposit_id===depositId);if(!d)throw Error('Deposit not found');d.status='HELD';d.provider_ref='DEMO-TRUST-'+Math.random().toString(36).slice(2,8).toUpperCase();d.received_at=now();d.held_at=d.received_at;mockEvent(d.transaction_id,'DEPOSIT_RECEIVED',null,{deposit_id:depositId,provider_ref:d.provider_ref,simulated:true});return d;}); },
    async simulateDepositRelease(depositId){ return localOrMock(()=>request(`/deposits/${depositId}/simulate-release`,{method:'POST'}),()=>{const d=Object.values(fallback.deposits).find(x=>x.deposit_id===depositId);if(!d||d.status!=='HELD')throw Error('Deposit must be held');d.status='RELEASED';d.released_at=now();mockEvent(d.transaction_id,'DEPOSIT_RELEASED',null,{deposit_id:depositId,simulated:true});return d;}); }
  };
})();

// Expose the API client to the inline application code.
// Without this, ES-style top-level const is not a window property in browsers.
window.TransactionOSAPI = TransactionOSAPI;

window.addEventListener('DOMContentLoaded',()=>TransactionOSAPI.ensureReady().catch(()=>{}));
