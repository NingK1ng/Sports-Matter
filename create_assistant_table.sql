CREATE TABLE IF NOT EXISTS assistant_query_log (
    id BIGSERIAL PRIMARY KEY,
    query TEXT NOT NULL,
    sports_gate BOOLEAN NOT NULL,
    use_agent BOOLEAN NOT NULL,
    top_k INTEGER NOT NULL,
    lang VARCHAR(10) NOT NULL,
    literature_recall_count INTEGER DEFAULT 0,
    journals_recall_count INTEGER DEFAULT 0,
    pubmed_agent_count INTEGER DEFAULT 0,
    pmid_valid_count INTEGER DEFAULT 0,
    final_candidate_count INTEGER DEFAULT 0,
    search_duration_ms INTEGER,
    generation_duration_ms INTEGER,
    total_duration_ms INTEGER,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    estimated_cost_cny NUMERIC(8, 4),
    agent_steps JSONB,
    agent_fallback BOOLEAN DEFAULT FALSE,
    status VARCHAR(20) NOT NULL,
    error_code VARCHAR(30),
    error_message TEXT,
    citation_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assistant_created_at ON assistant_query_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_assistant_status ON assistant_query_log(status, created_at);

SELECT 'Table created successfully' AS status;
