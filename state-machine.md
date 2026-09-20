# TransactionOS state machine

## Offer
DRAFT → SIGNED → SUBMITTED → DELIVERED → AWAITING_RESPONSE

From AWAITING_RESPONSE:
- ACCEPTED
- COUNTERED → new immutable OFFER_VERSION → AWAITING_RESPONSE
- DECLINED
- EXPIRED
- WITHDRAWN (where legally/permitted)

Each counter creates a new version and a new response deadline. Prior versions are immutable.

## Transaction
INITIATED → NEGOTIATING → ACCEPTED → CONDITION_PENDING → DOCUMENTS_PENDING → SIGNATURES_PENDING → CLOSING_READY → CLOSED

Exceptional terminal states should include CANCELLED and FAILED where applicable.

## Design rule
The state machine is deterministic. AI may interpret, summarize, flag, and prepare; it does not directly transition legally significant states without an authorized user action.


## Transaction Brain state evaluation (v3.1)
The deterministic evaluator checks, in order:
1. PAUSED control → HOLD
2. HIGH-severity unresolved risk → EXCEPTION / HOLD
3. Outstanding deposit obligation → POST_ACCEPTANCE / ACTION
4. Earliest incomplete required task → POST_ACCEPTANCE / ACTION
5. No open tasks → READY_FOR_CLOSING / COMPLETE

AI may explain or prepare the selected action, but it does not override these state gates.
