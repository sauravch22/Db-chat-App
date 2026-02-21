-- Initialize PostgreSQL metadata database for DbChat

-- Connections table
CREATE TABLE IF NOT EXISTS connections (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL UNIQUE,
    host VARCHAR(255) NOT NULL,
    port INT NOT NULL,
    username VARCHAR(255) NOT NULL,
    password TEXT NOT NULL,
    password_encrypted TEXT,
    database VARCHAR(255) NOT NULL,
    database_type VARCHAR(50) NOT NULL,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Databases table
CREATE TABLE IF NOT EXISTS databases (
    id SERIAL PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    row_count INT DEFAULT 0,
    last_indexed TIMESTAMP,
    last_indexed_at TIMESTAMP,
    schema_hash VARCHAR(64),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(connection_id, name)
);

-- Tables table
CREATE TABLE IF NOT EXISTS tables (
    id SERIAL PRIMARY KEY,
    database_id INT NOT NULL REFERENCES databases(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    context TEXT,
    embedding_id VARCHAR(255),
    sample_count INT DEFAULT 0,
    is_indexed BOOLEAN DEFAULT false,
    last_indexed_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(database_id, name)
);

-- Columns table
CREATE TABLE IF NOT EXISTS columns (
    id SERIAL PRIMARY KEY,
    table_id INT NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    data_type VARCHAR(100) NOT NULL,
    is_nullable BOOLEAN DEFAULT true,
    context TEXT,
    embedding_id VARCHAR(255),
    sample_values TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_id, name)
);

-- Samples table
CREATE TABLE IF NOT EXISTS samples (
    id SERIAL PRIMARY KEY,
    table_id INT NOT NULL REFERENCES tables(id) ON DELETE CASCADE,
    sample_data JSONB NOT NULL,
    embedding_id VARCHAR(255),
    generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Query audit log table
CREATE TABLE IF NOT EXISTS queries (
    id SERIAL PRIMARY KEY,
    connection_id INT NOT NULL REFERENCES connections(id),
    user_prompt TEXT NOT NULL,
    generated_sql TEXT,
    result_status VARCHAR(50),
    error_message TEXT,
    execution_time_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_connections_name ON connections(name);
CREATE INDEX IF NOT EXISTS idx_connections_is_active ON connections(is_active);
CREATE INDEX IF NOT EXISTS idx_databases_connection_id ON databases(connection_id);
CREATE INDEX IF NOT EXISTS idx_databases_last_indexed_at ON databases(last_indexed_at);
CREATE INDEX IF NOT EXISTS idx_tables_database_id ON tables(database_id);
CREATE INDEX IF NOT EXISTS idx_tables_is_indexed ON tables(is_indexed);
CREATE INDEX IF NOT EXISTS idx_columns_table_id ON columns(table_id);
CREATE INDEX IF NOT EXISTS idx_samples_table_id ON samples(table_id);
CREATE INDEX IF NOT EXISTS idx_queries_connection_id ON queries(connection_id);
CREATE INDEX IF NOT EXISTS idx_queries_created_at ON queries(created_at);
