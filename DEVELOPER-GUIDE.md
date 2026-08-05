# Developer Guide — Ingestion Framework

## Daily workflow

Develop on a branch, let CI validate the change, and merge through pull requests.
Do not commit directly to `main` for normal feature work.

```bash
git checkout main
git pull
git checkout -b feature/your-feature-name
```

Useful branch prefixes:

| Prefix | When to use | Example |
|---|---|---|
| `feature/` | New functionality | `feature/add-source-template-import` |
| `fix/` | Bug fix | `fix/redact-audit-errors` |
| `develop` | Optional integration branch | — |
| `main` | Stable, regression-checked branch | — |

## Project layout

```text
ingestion_framework/                 Python package
ingestion_framework/connectors/      Source access logic
ingestion_framework/processors/      Bronze ingestion orchestration per source type
ingestion_framework/writers/         Storage and file-format writers
configs/sources/                     Source YAML metadata
configs/storage*.yaml                Target storage metadata
deploy/single-node-airflow/          Docker Compose Airflow/MinIO/Postgres deployment
tools/generate_airflow_dags.py       Metadata-driven Airflow DAG generator
tests/                               Unit and integration-style tests
```

## Local validation

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m pytest
```

## Push and CI/CD

```bash
git add .
git commit -m "Describe the change"
git push origin feature/your-feature-name
```

The Azure DevOps pipeline in `azure-pipelines.yml` runs on:

- `main`
- `develop`
- `feature/*`
- `fix/*`
- pull requests into `main` or `develop`

The pipeline:

1. Prints branch/commit information.
2. Creates a Python virtualenv and runs `pytest`.
3. Validates the Docker Compose configuration.
4. For non-PR builds, rebuilds and restarts the single-node Airflow stack.
5. Waits for the Airflow health endpoint.

## First-time setup on the Ubuntu VM

Do this once before the deployment steps can work.

### 1. Register the Azure DevOps agent

Create a self-hosted Linux agent on the Ubuntu VM and place it in the pool named
in `azure-pipelines.yml`:

```yaml
pool:
  name: single-node-airflow-agents
```

If your Azure DevOps pool has a different name, update the pipeline file.

### 2. Bootstrap the single-node platform

On the Ubuntu VM:

```bash
cd /path/to/ingestion-framework/deploy/single-node-airflow
python3 install_platform.py --yes --skip-docker-install
docker compose --env-file .env up -d --build
```

The stack runs its own OpenBao and provisions it automatically: the
`openbao-bootstrap` service initializes the server, applies a read-only policy,
issues the token Airflow uses, and seeds the MinIO and audit secrets from `.env`.

Two files it creates need backing up, both under `/mnt/fast_data/openbao/`:

```text
init.json    OpenBao root token and recovery keys
unseal.env   static seal key; losing it makes OpenBao storage unreadable
```

Confirm the credentials resolve before relying on a scheduled run:

```bash
docker compose exec airflow-scheduler ingest-object check-secrets \
  --storage configs/storage_minio.yaml \
  --audit-db env:INGESTION_AUDIT_DB_URL
```

See `deploy/single-node-airflow/README.md` for seeding additional source
credentials and for the manual-unseal option.

## If the pipeline fails

1. Open the failed Azure DevOps pipeline run.
2. Click the failed step and read the logs.
3. If Airflow health fails, inspect the printed `airflow-webserver` logs.
4. Fix the code or deployment config and push again.

Common causes:

- `deploy/single-node-airflow/.env` does not exist on the self-hosted agent VM.
- `OPENBAO_TOKEN_FILE_PATH` points to a missing token file.
- Microsoft ODBC package repositories are unavailable during Docker build. If
  needed, set `INSTALL_MSSQL_ODBC=false` temporarily in `.env`.
- Port `8080`, `9000`, `9001`, or `5432` is already used by another stack.
