-- Pilot tables. Applied once, when schema_migrations is empty.
CREATE TABLE IF NOT EXISTS customer_sessions (
    id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    customer_ref VARCHAR(128) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_customer_sessions_tenant_id ON customer_sessions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_customer_sessions_customer_ref ON customer_sessions (customer_ref);
CREATE INDEX IF NOT EXISTS ix_customer_sessions_expires_at ON customer_sessions (expires_at);
