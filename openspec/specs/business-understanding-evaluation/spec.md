# business-understanding-evaluation Specification

## Purpose
TBD - created by archiving change add-langfuse-observability. Update Purpose after archive.
## Requirements
### Requirement: Repository cases synchronize to a Langfuse Dataset
The system SHALL map all 18 repository business-understanding evaluation cases to the `ke-engine/business-understanding-v1` Langfuse Dataset using stable project-level item identifiers.

#### Scenario: Dataset is synchronized repeatedly
- **WHEN** the evaluation command runs more than once against the same Langfuse project
- **THEN** it SHALL upsert the same 18 Dataset items rather than create duplicate items
- **AND** each item SHALL preserve the complete messages, expected route, expected intent, expected key entities, clarification expectation, case ID, category and Prompt version

### Requirement: Experiment executes the real business-understanding node
The evaluation command SHALL use the configured real Chat model and the current production business-understanding node for every Dataset item.

#### Scenario: Live experiment runs
- **WHEN** the developer executes the business-understanding Langfuse evaluation command with valid Langfuse and model configuration
- **THEN** the system SHALL run the 18 Dataset items with `max_concurrency=1`
- **AND** it SHALL mark run metadata with the model, Prompt version, application version and `live_model=true`
- **AND** it SHALL print the formatted result and Dataset Run URL

#### Scenario: Required evaluation service is unavailable
- **WHEN** Langfuse configuration, authentication, Dataset synchronization or Experiment creation fails
- **THEN** the explicit evaluation command SHALL exit with a non-zero status
- **AND** it MUST NOT report that a Dataset Run was created

### Requirement: Experiment uses five deterministic scores
The evaluation command SHALL reuse the repository scorer and attach numeric route accuracy, intent accuracy, key entity recall, clarification accuracy and schema validity Scores to each successful item result.

#### Scenario: Structured result is scored
- **WHEN** the business-understanding node returns a valid structured result
- **THEN** each of the five Scores SHALL have a value from zero through one
- **AND** each Score SHALL retain its numerator and denominator in an explanatory comment or metadata

#### Scenario: Model task fails
- **WHEN** the model call or structured-output parsing fails for one Dataset item
- **THEN** the Experiment runner SHALL record that item failure without fabricating a successful structured output
- **AND** remaining items SHALL still be eligible to run
