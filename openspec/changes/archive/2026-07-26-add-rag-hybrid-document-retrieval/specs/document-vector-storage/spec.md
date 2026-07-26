## MODIFIED Requirements

### Requirement: Elasticsearch vector store configuration
The system SHALL write vector documents to a configured Elasticsearch index whose mapping supports vector retrieval, full-text retrieval, and exact metadata filtering.

#### Scenario: Elasticsearch settings are available
- **WHEN** backend settings are loaded
- **THEN** `Settings.elasticsearch_url` SHALL be available
- **AND** `Settings.elasticsearch_index` SHALL be available
- **AND** `Settings.embedding_dimensions` SHALL be available

#### Scenario: Elasticsearch index defaults are stable
- **WHEN** no explicit Elasticsearch index is configured
- **THEN** the system SHALL use `ke-engine-vector` as the vector index name

#### Scenario: Elasticsearch vector mapping matches embedding dimensions
- **WHEN** the vector-storage infrastructure prepares or validates the target index
- **THEN** the vector field dimensions SHALL equal `Settings.embedding_dimensions`

#### Scenario: Elasticsearch retrieval fields are mapped
- **WHEN** the vector-storage infrastructure prepares or validates the target index
- **THEN** `text` SHALL support BM25 full-text search
- **AND** `vector` SHALL support Dense vector search
- **AND** `metadata.docId`, `metadata.chunkId`, and `metadata.accessibleBy` SHALL support exact filtering

#### Scenario: Incompatible retrieval mapping is rejected
- **WHEN** an existing index cannot support the required full-text, vector, or exact-filter fields
- **THEN** infrastructure assembly SHALL fail with a stable mapping compatibility error
- **AND** retrieval MUST NOT continue without the required access filter

#### Scenario: Vector store dependency is available
- **WHEN** backend dependencies are installed
- **THEN** the `langchain-elasticsearch` Python package SHALL be available for Elasticsearch vector storage and retrieval
