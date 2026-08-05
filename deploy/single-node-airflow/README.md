# Single-Node Airflow Deployment

This deployment layer bootstraps the single-node data lake platform for the ingestion framework:

- OpenBao holding the runtime credentials the ingestion jobs read
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

### Docker prerequisites

The installer provisions what is missing and leaves what is already present
alone. It checks three things separately, because a host can have any subset:

- **Docker Engine** — installed from `download.docker.com` if absent.
- **Compose v2 plugin** — installed even when the engine is already there. This stack invokes `docker compose`, so the older `docker-compose` v1 script does not satisfy it.
- **A running daemon the invoking user can reach** — the daemon is enabled and started, and the user is added to the `docker` group if needed.

Group membership only applies to a new login session, so the installer uses
sudo for the rest of its own run and tells you to log out and back in, or run
`newgrp docker`, before using `docker compose` directly.

To manage Docker yourself, for example from an internal mirror:

```bash
python3 install_platform.py --skip-docker-install
```

That flag now fails fast, listing what is missing, rather than proceeding into
a broken deployment.

## Choosing the storage target

The stack ships with MinIO, and generated DAGs point at `configs/storage_minio.yaml`
by default. To write to Azure Data Lake Storage Gen2 instead, fill in
`configs/storage_adls.yaml`, seed the service principal secret in OpenBao, and
regenerate the DAGs with the Azure profile:

```bash
python3 tools/generate_airflow_dags.py --profile single-node-airflow-adls --validate
cd deploy/single-node-airflow && python3 install_platform.py --sync-dags-only
```

MinIO stays in the stack either way, since the smoke-test DAG uses it.

## OpenBao runtime secrets

OpenBao runs as part of this stack. `docker compose up` starts the `openbao`
server and then a one-shot `openbao-bootstrap` that provisions it, so no manual
`bao operator init` or `bao kv put` is needed for a first deployment.

Generated ingestion DAGs read their runtime credentials from OpenBao:

- `configs/storage_minio.yaml` stores `access_key_ref` and `secret_key_ref`, not raw MinIO keys.
- API templates can use `api_key_secret_ref`.
- Database templates can use `username_secret_ref` and `password_secret_ref`.
- `INGESTION_AUDIT_DB_URL` is set to `INGESTION_AUDIT_DB_URL_REF`, which defaults to `openbao:secret/data/ingestion-framework/audit#url`.

The Airflow containers receive:

```text
OPENBAO_ADDR
OPENBAO_TOKEN_FILE=/run/secrets/openbao_token
```

### What the bootstrap does

On first start it initializes OpenBao, then on every start it re-checks each
step, so `docker compose up` is safe to repeat:

1. Runs `bao operator init` and writes the root token and recovery keys to `OPENBAO_INIT_FILE_PATH`.
2. Enables the KV v2 engine at `secret/`.
3. Applies an `ingestion-framework` policy granting **read only** on `secret/data/ingestion-framework/*`.
4. Issues a periodic token with that policy to `OPENBAO_TOKEN_FILE_PATH`, owned by the Airflow UID.
5. Seeds the MinIO and audit secrets from the values in `.env`, **only if they do not already exist**.
6. Verifies the issued token can read what it seeded.

Because step 5 never overwrites an existing secret, values you change later with
`bao kv put` survive subsequent restarts.

`airflow-init` waits for the bootstrap to finish, so Airflow never starts
against a missing or stale token.

### Back up the init file

```text
/mnt/fast_data/openbao/init.json
```

This holds the OpenBao root token and recovery keys. Copy it somewhere safe and
restrict access to it. Without it you cannot administer OpenBao, and the
bootstrap cannot reconfigure the server on a later run.

### Unseal keys

By default OpenBao uses a static seal so it unseals itself after a reboot,
which matters here because the ingestion DAGs are unattended. The key lives in
its own file, not in `.env` and not in the generated config:

```text
/mnt/fast_data/openbao/unseal.env   (mode 600)
```

Back this file up too. **Losing it makes the OpenBao data directory
unreadable**, and rotating it has the same effect on existing data.

To require a manual unseal after every restart instead:

```bash
python3 install_platform.py --openbao-shamir
```

In that mode the stack stays sealed until you run:

```bash
docker compose exec openbao bao operator unseal
docker compose up openbao-bootstrap
```

### Seeding additional secrets

Source credentials beyond MinIO and audit are still added by hand. Use the
`ingestion-framework/` prefix so the policy covers them:

```bash
docker compose exec openbao bao kv put -mount=secret ingestion-framework/api/pjm \
  subscription_key='<pjm-key>'

docker compose exec openbao bao kv put -mount=secret ingestion-framework/database/itron_mv90_sqlserver_readonly \
  username='<readonly-user>' \
  password='<readonly-password>'
```

If you target Azure Data Lake, seed the service principal secret the same way:

```bash
docker compose exec openbao bao kv put -mount=secret ingestion-framework/adls \
  client_secret='<service-principal-secret>'
```

Authenticate with the root token from the init file first.

### Verifying the wiring

Confirm a config's secrets resolve before trusting a scheduled run. This prints
pass or fail per reference and never prints a secret value:

```bash
docker compose exec airflow-scheduler ingest-object check-secrets \
  --config configs/sources/api_generated/pjm_load_forecast.yaml \
  --storage configs/storage_minio.yaml \
  --audit-db env:INGESTION_AUDIT_DB_URL
```

It exits non-zero if any reference fails to resolve.

### Access and TLS

The OpenBao port is published to `127.0.0.1:8200` only, and the listener runs
without TLS because traffic stays on the Compose network. If you expose it
beyond the host, terminate TLS and point the framework at the CA with
`OPENBAO_CACERT`.

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

That flag also rotates the OpenBao unseal key, which makes the existing OpenBao
data directory unreadable. To rotate platform passwords while keeping OpenBao
storage intact, restore the previous `unseal.env` afterwards. Note that rotating
`MINIO_ROOT_PASSWORD` does not update the copy already stored in OpenBao, since
the bootstrap does not overwrite existing secrets; update it explicitly:

```bash
docker compose exec openbao bao kv put -mount=secret ingestion-framework/minio \
  access_key='<minio-user>' \
  secret_key='<new-minio-password>'
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

## Troubleshooting

### `pull access denied for vt-airflow-ingestion`

The Airflow image is built from this repository and never pushed to a registry,
so Compose can only obtain it by building. All three Airflow services declare
the same `build:` config for that reason. If you see this error, the image was
not built, usually because the build itself failed earlier in the output.

Build on its own to see the real error:

```bash
docker compose --env-file .env build
```

The build needs to reach `raw.githubusercontent.com` for the Airflow constraints
file, PyPI, and, unless disabled, the Microsoft ODBC package repository. If your
network blocks the Microsoft repository, turn that part off in `.env` and
rebuild:

```bash
INSTALL_MSSQL_ODBC=false
```

Confirm the image exists before starting the stack:

```bash
docker images vt-airflow-ingestion
```

### Airflow containers cannot read the OpenBao token

Check that the bootstrap finished:

```bash
docker compose logs openbao-bootstrap
```

A successful run ends with `Bootstrap complete.` If the token path is a
directory rather than a file, Docker created it from a missing bind mount;
remove it and re-run `python3 install_platform.py`.

## Smoke test

After the stack is running, open Airflow and trigger:

```text
ingestion_framework_smoke_test
```

It imports the framework package inside Airflow and writes a small object to the MinIO bronze bucket.
