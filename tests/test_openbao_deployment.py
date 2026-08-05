"""Checks on the generated OpenBao deployment artifacts.

These guard the wiring between install_platform.py and docker-compose.yml:
a name or path that drifts on one side breaks the stack only at deploy time,
which is expensive to discover on the target VM.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
import yaml

DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy" / "single-node-airflow"
COMPOSE_PATH = DEPLOY_DIR / "docker-compose.yml"


@pytest.fixture(scope="module")
def install_platform():
    spec = importlib.util.spec_from_file_location(
        "install_platform", DEPLOY_DIR / "install_platform.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load(COMPOSE_PATH.read_text())


@pytest.fixture
def env_values(install_platform):
    values = dict(install_platform.DEFAULTS)
    values["AIRFLOW_UID"] = "50000"
    values["OPENBAO_UNSEAL_KEY_ID"] = "ingestion-framework-1"
    return values


def generated_config(install_platform, env_values, tmp_path) -> str:
    install_platform.write_openbao_config(tmp_path, env_values)
    return (tmp_path / "openbao.hcl").read_text()


def test_config_uses_raft_storage_at_the_mounted_path(install_platform, env_values, tmp_path):
    config = generated_config(install_platform, env_values, tmp_path)

    assert 'storage "raft"' in config
    assert 'path    = "/openbao/data"' in config


def test_config_requires_cluster_addr_for_raft(install_platform, env_values, tmp_path):
    # OpenBao refuses to start with raft storage unless cluster_addr is set.
    config = generated_config(install_platform, env_values, tmp_path)

    assert "cluster_addr" in config


def test_config_omits_unsupported_disable_mlock(install_platform, env_values, tmp_path):
    # OpenBao 2.6 warns on this key; it is unnecessary given the IPC_LOCK capability.
    config = generated_config(install_platform, env_values, tmp_path)

    assert "disable_mlock" not in config


def test_static_seal_reads_the_key_from_the_environment(install_platform, env_values, tmp_path):
    config = generated_config(install_platform, env_values, tmp_path)

    assert 'seal "static"' in config
    assert 'current_key    = "env://OPENBAO_UNSEAL_KEY"' in config
    assert 'current_key_id = "ingestion-framework-1"' in config


def test_generated_config_contains_no_secret_material(install_platform, env_values, tmp_path):
    # The server reads this file after dropping to the unprivileged openbao
    # user, so it cannot be locked down and must stay free of secrets.
    config = generated_config(install_platform, env_values, tmp_path)

    assert "OPENBAO_UNSEAL_KEY=" not in config
    assert not re.search(r'current_key\s*=\s*"[A-Za-z0-9+/]{40,}={0,2}"', config)


def test_shamir_mode_omits_the_seal_stanza(install_platform, env_values, tmp_path):
    env_values["OPENBAO_SEAL_MODE"] = "shamir"

    config = generated_config(install_platform, env_values, tmp_path)

    assert "seal " not in config
    assert 'storage "raft"' in config


def test_unseal_key_is_a_base64_aes_256_key(install_platform):
    import base64

    key = install_platform.unseal_key()

    assert len(base64.b64decode(key)) == 32


def test_unseal_keys_are_not_reused(install_platform):
    assert install_platform.unseal_key() != install_platform.unseal_key()


def test_bootstrap_script_is_executable_and_idempotent(install_platform, tmp_path):
    install_platform.write_openbao_bootstrap(tmp_path)
    script = tmp_path / "openbao-bootstrap.sh"
    body = script.read_text()

    assert script.stat().st_mode & 0o111
    assert body.startswith("#!/bin/sh")
    # Re-running `docker compose up` re-runs one-shot services, so each step
    # has to check before acting.
    assert "already initialized" in body
    assert "already enabled" in body
    assert "Secret already present, leaving unchanged" in body
    assert "Existing ingestion token is still valid" in body


def test_bootstrap_grants_only_read_access_to_the_framework_prefix(install_platform, tmp_path):
    install_platform.write_openbao_bootstrap(tmp_path)
    body = (tmp_path / "openbao-bootstrap.sh").read_text()

    assert 'capabilities = ["read"]' in body
    assert 'path "$OPENBAO_KV_MOUNT/data/$OPENBAO_SECRET_PREFIX/*"' in body
    assert '"create"' not in body
    assert '"update"' not in body
    assert '"sudo"' not in body


def test_bootstrap_seeds_the_secrets_the_stack_reads(install_platform, tmp_path):
    install_platform.write_openbao_bootstrap(tmp_path)
    body = (tmp_path / "openbao-bootstrap.sh").read_text()

    assert '"$OPENBAO_SECRET_PREFIX/minio"' in body
    assert '"$OPENBAO_SECRET_PREFIX/audit"' in body
    assert "postgresql+psycopg2://" in body


def test_bootstrap_writes_the_token_in_place(install_platform, tmp_path):
    install_platform.write_openbao_bootstrap(tmp_path)
    body = (tmp_path / "openbao-bootstrap.sh").read_text()

    # Replacing the file would detach it from the bind mount, so it must be
    # truncated in place with a redirect rather than moved over.
    assert 'printf \'%s\\n\' "$issued" > "$TOKEN_FILE"' in body
    assert "mv " not in body


def test_compose_openbao_service_matches_the_configured_address(compose, env_values):
    # OPENBAO_ADDR defaults to http://openbao:8200, so the service must be
    # named `openbao` for Airflow to resolve it on the compose network.
    assert "openbao" in compose["services"]
    assert env_values["OPENBAO_ADDR"] == "http://openbao:8200"


def test_compose_openbao_mounts_the_generated_config_and_data(compose):
    volumes = compose["services"]["openbao"]["volumes"]

    assert "./generated/openbao.hcl:/openbao/config/openbao.hcl:ro" in volumes
    assert any(volume.endswith(":/openbao/data") for volume in volumes)


def test_compose_openbao_supplies_the_unseal_key_by_env_file(compose):
    service = compose["services"]["openbao"]

    assert service["env_file"] == ["${OPENBAO_UNSEAL_ENV_FILE}"]
    assert "IPC_LOCK" in service["cap_add"]


def test_compose_openbao_port_is_bound_to_loopback_by_default(compose, env_values):
    ports = compose["services"]["openbao"]["ports"]

    assert ports == ["${OPENBAO_HOST_BIND:-127.0.0.1}:${OPENBAO_HOST_PORT:-8200}:8200"]
    assert env_values["OPENBAO_HOST_BIND"] == "127.0.0.1"


def test_compose_healthcheck_accepts_a_sealed_server(compose):
    # The bootstrap cannot initialize a server that must already be unsealed,
    # so the healthcheck has to treat `sealed` (exit 2) as reachable.
    test = compose["services"]["openbao"]["healthcheck"]["test"]

    assert "-eq 2" in test[-1]


def test_compose_bootstrap_waits_for_the_server(compose):
    depends = compose["services"]["openbao-bootstrap"]["depends_on"]

    assert depends["openbao"]["condition"] == "service_healthy"


def test_compose_airflow_waits_for_the_bootstrap(compose):
    # Airflow bind-mounts the token file, so it must not start before the
    # bootstrap has written a valid token into it.
    depends = compose["services"]["airflow-init"]["depends_on"]

    assert depends["openbao-bootstrap"]["condition"] == "service_completed_successfully"


def test_compose_bootstrap_mounts_token_and_init_files(compose):
    volumes = compose["services"]["openbao-bootstrap"]["volumes"]

    assert "${OPENBAO_TOKEN_FILE_PATH}:/run/openbao/ingestion.token" in volumes
    assert "${OPENBAO_INIT_FILE_PATH}:/run/openbao/init.json" in volumes


def test_every_service_using_a_locally_built_image_can_build_it(compose):
    """Guard against Compose trying to pull an image that is only built here.

    vt-airflow-ingestion is never pushed to a registry. A service that names it
    without a build config makes Compose resolve it by pulling, which fails with
    "pull access denied for vt-airflow-ingestion".
    """
    services = compose["services"]
    locally_built = {
        service["image"] for service in services.values() if "build" in service
    }

    pullers = [
        name
        for name, service in services.items()
        if service.get("image") in locally_built and "build" not in service
    ]

    assert pullers == []


def test_all_airflow_services_share_one_build_definition(compose):
    # Differing build configs for one tag would make Compose build it more than
    # once, and the services could end up on different images.
    services = compose["services"]
    builds = [
        services[name]["build"]
        for name in ("airflow-init", "airflow-scheduler", "airflow-webserver")
    ]

    assert builds[0] == builds[1] == builds[2]
    assert builds[0]["dockerfile"] == "deploy/single-node-airflow/Dockerfile.airflow"


def test_compose_variables_are_all_produced_by_the_installer(install_platform):
    raw = COMPOSE_PATH.read_text()
    produced = (
        set(install_platform.DEFAULTS)
        | set(install_platform.SECRET_KEYS)
        | {"AIRFLOW_UID", "AIRFLOW_FERNET_KEY", "OPENBAO_UNSEAL_KEY_ID"}
    )

    missing = set()
    # `$${VAR}` is escaped for the container shell, not substituted by compose.
    for match in re.finditer(r"(?<!\$)\$\{([A-Z0-9_]+)(:-[^}]*)?\}", raw):
        name, has_default = match.group(1), match.group(2) is not None
        if not has_default and name not in produced:
            missing.add(name)

    assert missing == set()


def test_installer_defaults_keep_the_unseal_key_out_of_env(install_platform):
    # .env is written for docker compose interpolation; the unseal key lives in
    # its own 0600 file so it is never interpolated or echoed alongside it.
    assert "OPENBAO_UNSEAL_KEY" not in install_platform.DEFAULTS
    assert "OPENBAO_UNSEAL_KEY" not in install_platform.SECRET_KEYS
    assert "OPENBAO_UNSEAL_ENV_FILE" in install_platform.DEFAULTS


def test_audit_reference_default_points_at_the_seeded_secret(install_platform):
    assert (
        install_platform.DEFAULTS["INGESTION_AUDIT_DB_URL_REF"]
        == "openbao:secret/data/ingestion-framework/audit#url"
    )
