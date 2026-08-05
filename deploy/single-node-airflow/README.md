# Single-Node Airflow Deployment

This deployment layer bootstraps the single-node data lake platform for the ingestion framework:

- Postgres for Airflow metadata and ingestion framework metadata
- MinIO object storage with bronze, landing, silver, gold, and quarantine buckets
- Airflow running a custom image that installs this repository as a Python package
- Airflow connections and variables for MinIO and the ingestion metadata database
- A smoke-test DAG plus generated ingestion DAGs for the default source objects

## Generate ingestion DAGs

From the repository root, generate the safe default subset:

```bash
python3 tools/generate_airflow_dags.py --validate
```

This writes four DAGs to `deploy/single-node-airflow/dags/generated/`, compiles them,
and uses the default `single-node-airflow` profile:

- project root inside Airflow: `/opt/ingestion-framework`
- storage config: `configs/storage_minio.yaml`
- audit/watermark backend: `env:INGESTION_AUDIT_DB_URL`

Filters can be repeated:

```bash
python3 tools/generate_airflow_dags.py \
  --source-type api \
  --source-system open_meteo \
  --object-id weather_forecast
```

`--scan-all` discovers all regular source YAMLs but deliberately excludes
`configs/sources/database_compact_generated/`. Generating all compact database
DAGs requires both `--scan-all --include-all-databases`; a single database YAML
can instead be selected safely with `--config`.

Generated DAGs default to `max_active_runs=1` to avoid concurrent incremental
runs racing against the same watermark.

Lawson full-load database objects are treated as `one_time` loads unless their
source YAML explicitly overrides `orchestration.load_type`. Other sources are
treated as `ongoing` by default. Use `--load-type` to select one class:

```bash
python3 tools/generate_airflow_dags.py \
  --scan-all \
  --load-type ongoing \
  --validate
```

After regenerating DAGs on the Ubuntu VM, sync only DAG files without rerunning
the full platform bootstrap:

```bash
cd deploy/single-node-airflow
python3 install_platform.py --sync-dags-only
```

## Why this lives in the framework repository

For this deployment, the deployment belongs with the ingestion framework because the Airflow runtime is built directly from this source tree. That keeps framework dependency changes, DAG changes, and platform bootstrap changes together.

Split this into a separate platform repository later if the same MinIO/Airflow/Postgres platform needs to host multiple independent frameworks or product teams.

## Ubuntu VM usage

From the repository root on the Ubuntu VM:

```bash
cd deploy/single-node-airflow
python3 install_platform.py
docker compose --env-file .env up -d --build
```

Use `--yes` for non-interactive bootstrap prompts:

```bash
python3 install_platform.py --yes
```

The installer validates that `/mnt/fast_data` and `/mnt/data_lake` are mounted filesystems before creating platform directories.

## OpenBao runtime secrets

Generated ingestion DAGs run the framework inside Airflow. Those jobs now expect
runtime credentials to live in OpenBao:

- `configs/storage_minio.yaml` stores `access_key_ref` and `secret_key_ref`, not raw MinIO keys.
- API templates can use `api_key_secret_ref`.
- Database templates can use `username_secret_ref` and `password_secret_ref`.
- `INGESTION_AUDIT_DB_URL` is set to `INGESTION_AUDIT_DB_URL_REF`, which defaults to `openbao:secret/data/ingestion-framework/audit#url`.

The Airflow containers receive:

```text
OPENBAO_ADDR
OPENBAO_TOKEN_FILE=/run/secrets/openbao_token
```

The token file is mounted from `OPENBAO_TOKEN_FILE_PATH`, which defaults to:

```text
/mnt/fast_data/openbao/ingestion-framework.token
```

Create that token outside this repository using your OpenBao operational
process, and grant it read access only to the ingestion framework paths it needs.

Example seed values:

```bash
bao kv put -mount=secret ingestion-framework/minio \
  access_key='<minio-user>' \
  secret_key='<minio-password>'

bao kv put -mount=secret ingestion-framework/audit \
  url='postgresql+psycopg2://ingestion_app:<password>@postgres:5432/ingestion_metadata'

bao kv put -mount=secret ingestion-framework/api/pjm \
  subscription_key='<pjm-key>'

bao kv put -mount=secret ingestion-framework/database/itron_mv90_sqlserver_readonly \
  username='<readonly-user>' \
  password='<readonly-password>'
```

## Generated secrets

The installer writes `deploy/single-node-airflow/.env` and preserves existing values on re-run. Ingestion job credentials should be OpenBao references, not secret values in `.env`.

The single-node Compose stack still has local platform bootstrap secrets for
Postgres, MinIO, and Airflow service startup. For a hardened production
deployment, move those platform bootstrap secrets behind your infrastructure
secret-injection mechanism as well, such as OpenBao Agent-rendered secret files
or an orchestrator-native secret store.

The installer only rotates generated platform bootstrap secrets when explicitly called with:

```bash
python3 install_platform.py --rotate-secrets
```

The generated Postgres users are:

- `postgres`: admin/bootstrap user
- `airflow`: Airflow metadata database owner
- `ingestion_app`: ingestion framework metadata database owner

The ingestion framework should use only `ingestion_app` for its own durable pipeline state.

## SQL Server drivers

The Airflow image installs Python SQL Server support. Microsoft ODBC Driver installation defaults to enabled because SQL Server is a primary production source type.

If your build environment cannot reach Microsoft package repositories, you can temporarily disable the driver install in `.env` before building:

```bash
INSTALL_MSSQL_ODBC=false
```

## Smoke test

After the stack is running, open Airflow and trigger:

```text
ingestion_framework_smoke_test
```

It imports the framework package inside Airflow and writes a small object to the MinIO bronze bucket.
