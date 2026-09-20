-- TransactionOS v2.3 core schema (illustrative/local prototype)
CREATE TABLE deposits (
  deposit_id TEXT PRIMARY KEY,
  transaction_id TEXT NOT NULL,
  required_amount_cents INTEGER NOT NULL,
  status TEXT NOT NULL,
  provider_ref TEXT,
  received_at TEXT,
  held_at TEXT,
  released_at TEXT,
  refunded_at TEXT,
  dispute_reason TEXT,
  created_at TEXT NOT NULL
);
