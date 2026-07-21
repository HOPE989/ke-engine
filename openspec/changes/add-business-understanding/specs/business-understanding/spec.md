## ADDED Requirements

### Requirement: Business Understanding returns one structured decision
The system SHALL evaluate the conversation history and current user input into one structured Business Understanding result containing `reasoning`, `route`, `intent`, `entities`, and `clarification_question`.

#### Scenario: Business result is internally consistent
- **WHEN** the model classifies a request with `route=BUSINESS`
- **THEN** `intent` SHALL contain one supported business intent
- **AND** `clarification_question` SHALL be null

#### Scenario: Non-business result is internally consistent
- **WHEN** the model classifies a request with `route=NON_BUSINESS`
- **THEN** `intent` SHALL be null
- **AND** `clarification_question` SHALL be null

#### Scenario: Clarification result is internally consistent
- **WHEN** the model classifies a request with `route=CLARIFY`
- **THEN** `clarification_question` SHALL contain one non-blank question
- **AND** `intent` MAY contain the already-known candidate business intent or be null

#### Scenario: Legacy related gate is absent
- **WHEN** the structured output schema is inspected
- **THEN** it MUST NOT contain a `related` boolean
- **AND** it MUST NOT contain a `BusinessDomain` or `confidence` field

### Requirement: V1 uses a fixed flat business intent taxonomy
The system SHALL constrain business intent to `POLICY_RULE_QA`, `TRANSPORT_OPERATION_QA`, `COAL_SALES_QA`, `PROFESSIONAL_KNOWLEDGE_QA`, `BUSINESS_DATA_QUERY`, or `OTHER_BUSINESS`.

#### Scenario: Policy or regulation question is classified
- **WHEN** a business user asks for a policy, enterprise rule, dispatch regulation, or formal operating requirement
- **THEN** the result SHALL use `intent=POLICY_RULE_QA`

#### Scenario: Transportation operation question is classified
- **WHEN** a business user asks about operating plans, loading, train formation, dispatch, shipment, arrival, or freight-document processes without requesting specific enterprise data
- **THEN** the result SHALL use `intent=TRANSPORT_OPERATION_QA`

#### Scenario: Coal sales question is classified
- **WHEN** a business user asks about coal purchasing, sales, customers, suppliers, contracts, quality settlement, pricing, or penalties
- **THEN** the result SHALL use `intent=COAL_SALES_QA`

#### Scenario: Professional knowledge question is classified
- **WHEN** a business user asks for a railway, coal, port, shipping, power, or chemical concept, principle, indicator meaning, or calculation method
- **THEN** the result SHALL use `intent=PROFESSIONAL_KNOWLEDGE_QA`

#### Scenario: Enterprise data request is classified
- **WHEN** a business user requests a specific plan, train, formation, contract, freight document, status, quantity, period statistic, or historical/actual/simulated comparison
- **THEN** the result SHALL use `intent=BUSINESS_DATA_QUERY`

#### Scenario: Unsupported business intent label is rejected
- **WHEN** structured model output contains an intent outside the fixed taxonomy
- **THEN** schema validation SHALL fail
- **AND** the system MUST NOT silently map the value to `OTHER_BUSINESS`

### Requirement: Route decisions use business meaning rather than keywords
The system SHALL distinguish enterprise railway and coal operations from public or general topics by considering the user's requested action and conversation context, not isolated keywords.

#### Scenario: Public passenger railway question is non-business
- **WHEN** the user asks how to refund or change a high-speed railway passenger ticket
- **THEN** the result SHALL use `route=NON_BUSINESS`

#### Scenario: Freight document knowledge is business
- **WHEN** the user asks what information a freight waybill should contain
- **THEN** the result SHALL use `route=BUSINESS`
- **AND** the intent SHALL describe transportation operation knowledge rather than a concrete data lookup

#### Scenario: Concrete freight document lookup is business data
- **WHEN** the user provides a freight document number and asks for its current status
- **THEN** the result SHALL use `route=BUSINESS`
- **AND** the result SHALL use `intent=BUSINESS_DATA_QUERY`

### Requirement: Conversation history resolves ellipsis before routing
The system SHALL provide the checkpointed Chat message history to Business Understanding so that an incomplete current utterance can inherit uniquely determined business context.

#### Scenario: Data version follows the prior query
- **WHEN** the previous user request asked for a station's simulated loading plan and the current input is “按实际版呢”
- **THEN** the result SHALL remain `route=BUSINESS`
- **AND** it SHALL retain the prior station, time range, and metric
- **AND** it SHALL set `data_version` to the actual version

#### Scenario: History does not justify invented context
- **WHEN** neither the current input nor conversation history identifies a business topic
- **THEN** the system MUST NOT invent a railway or coal entity merely to produce a business route

### Requirement: Business entities use railway and coal terminology
The system SHALL expose nullable entity fields for `operation_plan_no`, `train_no`, `formation_no`, `contract_no`, `document_type`, `document_no`, `customer`, `supplier`, `coal_type`, `departure_station`, `arrival_station`, `railway_section`, `time_range`, `data_version`, `metric_name`, and `exception_description`.

#### Scenario: Freight document type and number are separated
- **WHEN** the user supplies a waybill, cargo order, or freight ticket identifier
- **THEN** `document_type` SHALL identify the document kind
- **AND** `document_no` SHALL contain its identifier

#### Scenario: Missing entity remains null
- **WHEN** an entity is not stated or uniquely implied by conversation history
- **THEN** its value SHALL remain null
- **AND** the model MUST NOT fabricate a placeholder identifier

### Requirement: Clarification is requested only when necessary
The system SHALL choose `CLARIFY` when the business request or its required execution parameters cannot be determined from the current input and conversation history.

#### Scenario: Missing required document number triggers clarification
- **WHEN** the user asks to query “我的运单” and no waybill number is available in history
- **THEN** the result SHALL use `route=CLARIFY`
- **AND** the clarification question SHALL ask for the waybill number

#### Scenario: Optional entity does not trigger clarification
- **WHEN** a policy or professional knowledge question is answerable without a plan number, document number, time range, or data version
- **THEN** missing optional entities MUST NOT cause `route=CLARIFY`

#### Scenario: One clarification asks one focused question
- **WHEN** clarification is required
- **THEN** `clarification_question` SHALL ask for the smallest missing information needed to continue
- **AND** it MUST NOT present a questionnaire containing unrelated optional fields

### Requirement: Classification failure remains an execution failure
The system SHALL validate model output against the structured Business Understanding schema without automatically retrying or silently converting invalid output to a route.

#### Scenario: Structured output is invalid
- **WHEN** model output fails enum, field, or cross-field validation
- **THEN** the Business Understanding node SHALL fail
- **AND** the completion SHALL follow the existing error path
- **AND** no partial Business Understanding result SHALL enter checkpoint state

### Requirement: Business Understanding has a regression evaluation set
The system SHALL provide deterministic tests and an offline labeled dataset for route, intent, entity, clarification, multi-turn, and schema behavior.

#### Scenario: Representative boundary cases are covered
- **WHEN** the evaluation dataset is inspected
- **THEN** it SHALL include public-passenger negatives, freight-document knowledge versus lookup, policy versus professional knowledge, transportation versus coal sales, and missing-identifier clarification

#### Scenario: Evaluation reports separate dimensions
- **WHEN** old and new Prompt behavior is compared
- **THEN** route accuracy, intent accuracy, key-entity extraction, clarification behavior, unsupported labels, and schema validity SHALL be reported separately
