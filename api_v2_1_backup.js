// TransactionOS v2 mock API. These functions intentionally mirror future HTTP contracts.
const TransactionOSAPI = (() => {
  const db = { properties: {}, transactions: {}, offers: {}, events: [] };
  const now = () => new Date().toISOString();
  const id = p => `${p}_${Math.random().toString(36).slice(2,10)}`;
  function event(transactionId, type, actorPartyId, metadata={}) {
    const e={event_id:id('evt'),transaction_id:transactionId,type,actor_party_id:actorPartyId,occurred_at:now(),metadata};
    db.events.push(e); return e;
  }
  return {
    async createProperty(input){ const p={property_id:id('prop'),...input}; db.properties[p.property_id]=p; return p; },
    async getProperty(propertyId){ return db.properties[propertyId] || null; },
    async createTransaction(input){ const t={transaction_id:id('txn'),status:'INITIATED',created_at:now(),...input}; db.transactions[t.transaction_id]=t; event(t.transaction_id,'TRANSACTION_CREATED',input.actor_party_id||null); return t; },
    async getTransaction(transactionId){ return db.transactions[transactionId] || null; },
    async createOffer(input){ const offer={offer_id:id('offer'),status:'DRAFT',current_version_id:null,versions:[],...input}; db.offers[offer.offer_id]=offer; event(input.transaction_id,'OFFER_CREATED',input.actor_party_id||null); return offer; },
    async getOffer(offerId){ return db.offers[offerId] || null; },
    async addOfferVersion(offerId,input){ const o=db.offers[offerId]; if(!o) throw Error('Offer not found'); const v={version_id:id('ver'),offer_id:offerId,version_number:o.versions.length+1,status:'SUBMITTED',submitted_at:now(),...input}; o.versions.push(v); o.current_version_id=v.version_id; o.status='AWAITING_RESPONSE'; event(o.transaction_id,'OFFER_VERSION_SUBMITTED',input.actor_party_id||null,{version_id:v.version_id}); return v; },
    async acceptOffer(offerId,actorPartyId){ const o=db.offers[offerId]; const v=o?.versions.find(x=>x.version_id===o.current_version_id); if(!v) throw Error('No current version'); v.status='ACCEPTED'; v.accepted_at=now(); o.status='ACCEPTED'; const t=db.transactions[o.transaction_id]; if(t) t.status='ACCEPTED'; return event(o.transaction_id,'OFFER_ACCEPTED',actorPartyId,{offer_version_id:v.version_id,accepted_at:v.accepted_at}); },
    async listEvents(transactionId){ return db.events.filter(e=>e.transaction_id===transactionId); }
  };
})();
