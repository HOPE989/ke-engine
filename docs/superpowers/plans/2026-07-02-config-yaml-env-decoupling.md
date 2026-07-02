# Config YAML Env Decoupling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move non-sensitive backend runtime defaults from `backend/.env.example` into `backend/config.yaml`, while keeping user-required and secret-bearing values in `.env`.

**Architecture:** `Settings` remains the single runtime configuration object. Pydantic settings sources load values in this order: explicit init values, process environment, `.env`, `config.yaml`, then secrets/defaults. `backend/config.yaml` documents local defaults for non-sensitive options; `backend/.env.example` documents required per-user values and credentials.

**Tech Stack:** Python 3.11, FastAPI, pydantic-settings `YamlConfigSettingsSource`, pytest.

---

### Task 1: Add YAML Settings Source Tests

**Files:**
- Modify: `backend/tests/test_document_config.py`

- [ ] **Step 1: Write failing tests**

Add tests that create a temporary YAML file with non-sensitive settings and a temporary env file with user-required settings:

```python
settings = config.create_settings(env_file=env_file, config_file=config_file)
assert settings.database_url == "postgresql+asyncpg://user:pass@db.example:5432/app"
assert settings.max_upload_size_mb == 25
```

Also add a test that process environment values override YAML values:

```python
monkeypatch.setenv("MAX_UPLOAD_SIZE_MB", "99")
settings = config.create_settings(config_file=config_file)
assert settings.max_upload_size_mb == 99
```

- [ ] **Step 2: Run targeted tests and confirm failure**

Run: `uv run python -m pytest tests/test_document_config.py -q`

Expected: FAIL because `create_settings` does not accept `config_file` and YAML is not loaded.

### Task 2: Implement Config YAML Loading

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/config.yaml`

- [ ] **Step 1: Add default config path and YAML source**

Use `YamlConfigSettingsSource` in `Settings.settings_customise_sources` after dotenv:

```python
return init_settings, env_settings, dotenv_settings, YamlConfigSettingsSource(settings_cls), file_secret_settings
```

- [ ] **Step 2: Add `config_file` parameter**

Update `create_settings` to accept a YAML config path:

```python
def create_settings(env_file: Path | None = None, config_file: Path | None = None) -> Settings:
    return Settings(
        _env_file=env_file or DEFAULT_ENV_FILE,
        _config_file=config_file or DEFAULT_CONFIG_FILE,
    )
```

- [ ] **Step 3: Add `backend/config.yaml`**

Move non-sensitive defaults such as upload limits, MinIO endpoint/bucket/public URL, MinerU provider/base URL/model/timeouts, Redis URL, Kafka bootstrap servers, lock expiry, and Snowflake worker id into YAML.

- [ ] **Step 4: Run targeted tests**

Run: `uv run python -m pytest tests/test_document_config.py -q`

Expected: PASS.

### Task 3: Update Env Example Contract

**Files:**
- Modify: `backend/.env.example`
- Modify: `backend/tests/test_document_config.py`
- Modify: `backend/tests/test_chat_settings.py`

- [ ] **Step 1: Update `.env.example`**

Keep only values users must configure or credentials/secrets:

```dotenv
DATABASE_URL=postgresql+asyncpg://ke_engine:ke_engine@127.0.0.1:5432/ke_engine
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINERU_API_KEY=
OPENAI_API_KEY=
OPENAI_BASE_URL=
OPENAI_MODEL=
```

- [ ] **Step 2: Update tests**

Make `.env.example` tests assert required env keys are present and non-sensitive YAML keys are absent from `.env.example` but present in `backend/config.yaml`.

- [ ] **Step 3: Run full backend tests**

Run: `uv run python -m pytest`

Expected: PASS.
