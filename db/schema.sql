-- One row per store cycle. Killed stores stay (status='killed') for learning.
CREATE TABLE IF NOT EXISTS stores (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    niche           TEXT NOT NULL,
    region          TEXT DEFAULT 'SG',
    shopify_domain  TEXT,
    status          TEXT DEFAULT 'planning',     -- planning|live|scaling|killed
    budget_cap_sgd  REAL,
    spent_sgd       REAL DEFAULT 0,
    launched_at     TEXT,
    deadline_at     TEXT,
    killed_at       TEXT,
    kill_reason     TEXT,
    created_at      TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Products inside a store. A niche store has many. status='hero' marks the winner.
CREATE TABLE IF NOT EXISTS products (
    id                    INTEGER PRIMARY KEY,
    store_id              INTEGER NOT NULL REFERENCES stores(id),
    name                  TEXT NOT NULL,
    sku                   TEXT,
    selling_price         REAL NOT NULL,
    cogs                  REAL NOT NULL,
    fulfillment_shipping  REAL DEFAULT 0,
    payment_fee           REAL DEFAULT 0,
    platform_fee          REAL DEFAULT 0,
    score                 REAL,
    status                TEXT DEFAULT 'backlog',  -- backlog|testing|killed|hero
    shopify_product_id    TEXT,
    shopify_variant_id    TEXT,
    meta_campaign_id      TEXT,                    -- set after launching Meta campaign
    meta_adset_id         TEXT,                    -- set after creating Meta adset (needed for raise_budget)
    tiktok_campaign_id    TEXT,                    -- set after launching TikTok campaign (v2)
    source                TEXT,                    -- cj_dropshipping|spocket|manual
    created_at            TEXT DEFAULT CURRENT_TIMESTAMP
);

-- One row per product per channel per day.
CREATE TABLE IF NOT EXISTS daily_metrics (
    id            INTEGER PRIMARY KEY,
    product_id    INTEGER NOT NULL REFERENCES products(id),
    channel       TEXT NOT NULL,                   -- meta|tiktok|carousell|organic
    day           INTEGER NOT NULL,                -- day index from store launch
    date          TEXT NOT NULL,                   -- YYYY-MM-DD
    ad_spend      REAL DEFAULT 0,
    impressions   INTEGER DEFAULT 0,
    clicks        INTEGER DEFAULT 0,
    sessions      INTEGER DEFAULT 0,
    add_to_carts  INTEGER DEFAULT 0,
    orders        INTEGER DEFAULT 0,
    revenue       REAL DEFAULT 0,
    logged_at     TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(product_id, channel, date)
);

-- All verdicts archived. Both product-level (KILL/ITERATE/KEEP/SCALE)
-- and store-level (DUMP/SCALE_STORE/KEEP_TESTING/ITERATE_STORE).
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY,
    store_id      INTEGER REFERENCES stores(id),
    product_id    INTEGER REFERENCES products(id),
    level         TEXT NOT NULL,                   -- product|store
    day           INTEGER,
    verdict       TEXT NOT NULL,
    reason        TEXT,
    metrics_json  TEXT,
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Human approval queue. Telegram bot reads pending rows, writes back resolutions.
-- Nothing money-touching executes without resolved_at IS NOT NULL AND status='approved'.
CREATE TABLE IF NOT EXISTS approvals (
    id            INTEGER PRIMARY KEY,
    store_id      INTEGER REFERENCES stores(id),
    product_id    INTEGER REFERENCES products(id),
    action        TEXT NOT NULL,                   -- launch_store|launch_product|raise_budget|kill_product|dump_store|update_creative
    payload_json  TEXT,
    status        TEXT DEFAULT 'pending',          -- pending|approved|rejected|executed
    created_at    TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_at   TEXT,
    resolved_by   TEXT
);

CREATE INDEX IF NOT EXISTS idx_metrics_product_day ON daily_metrics(product_id, day);
CREATE INDEX IF NOT EXISTS idx_decisions_store ON decisions(store_id, created_at);
CREATE INDEX IF NOT EXISTS idx_approvals_pending ON approvals(status);
