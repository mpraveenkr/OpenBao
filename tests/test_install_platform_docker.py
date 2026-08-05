"""Checks on the installer's Docker provisioning.

The stack needs three separate things: the Docker Engine, the Compose v2
plugin, and a reachable daemon. A host can have any subset, so each is
detected and installed independently.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

DEPLOY_DIR = Path(__file__).resolve().parents[1] / "deploy" / "single-node-airflow"


@pytest.fixture
def installer():
    spec = importlib.util.spec_from_file_location(
        "install_platform_docker_under_test", DEPLOY_DIR / "install_platform.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeShell:
    """Records commands and answers them from a configurable rule set."""

    def __init__(self, present_commands: set[str], returncodes: dict[str, int]) -> None:
        self.present_commands = present_commands
        self.returncodes = returncodes
        self.commands: list[list[str]] = []

    def which(self, name: str):
        return f"/usr/bin/{name}" if name in self.present_commands else None

    def run_cmd(self, command, *, sudo=False, check=True, cwd=None):
        self.commands.append(command)
        key = " ".join(command[:3])
        returncode = self.returncodes.get(key, 0)
        if check and returncode != 0:
            raise SystemExit(returncode)
        return subprocess.CompletedProcess(command, returncode, stdout="amd64\n", stderr="")

    def ran(self, fragment: str) -> bool:
        return any(fragment in " ".join(command) for command in self.commands)


def wire(installer, monkeypatch, present_commands, returncodes=None):
    shell = FakeShell(present_commands, returncodes or {})
    monkeypatch.setattr(installer.shutil, "which", shell.which)
    monkeypatch.setattr(installer, "run_cmd", shell.run_cmd)
    return shell


def test_compose_v2_is_detected_independently_of_the_engine(installer, monkeypatch):
    wire(installer, monkeypatch, {"docker"}, {"docker compose version": 0})

    assert installer.docker_engine_installed() is True
    assert installer.docker_compose_v2_installed() is True


def test_engine_without_the_compose_plugin_is_reported_missing(installer, monkeypatch):
    # The case the plain `which docker` check got wrong: the engine is present,
    # so installation was skipped, and `docker compose up` then failed.
    wire(installer, monkeypatch, {"docker"}, {"docker compose version": 1})

    assert installer.docker_engine_installed() is True
    assert installer.docker_compose_v2_installed() is False


def test_compose_v2_is_absent_when_the_engine_is(installer, monkeypatch):
    wire(installer, monkeypatch, set())

    assert installer.docker_compose_v2_installed() is False


def test_nothing_is_installed_when_everything_is_present(installer, monkeypatch):
    shell = wire(
        installer,
        monkeypatch,
        {"docker"},
        {"docker compose version": 0, "docker info": 0},
    )

    installer.install_docker(False)

    assert not shell.ran("apt-get install")
    assert not shell.ran("usermod")


def test_missing_compose_plugin_is_installed(installer, monkeypatch):
    calls = {"docker compose version": 1}

    shell = wire(installer, monkeypatch, {"docker", "apt-get", "curl", "gpg"}, calls)

    # The plugin becomes available once the package is installed.
    def compose_after_install():
        return shell.ran("apt-get install")

    monkeypatch.setattr(installer, "docker_compose_v2_installed", compose_after_install)
    monkeypatch.setattr(installer, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(installer, "docker_accessible_without_sudo", lambda: True)

    installer.install_docker(False)

    assert shell.ran("docker-compose-plugin")


def test_full_install_includes_engine_and_buildx(installer, monkeypatch):
    shell = wire(installer, monkeypatch, {"apt-get", "curl", "gpg"})
    monkeypatch.setattr(installer, "docker_compose_v2_installed", lambda: True)
    monkeypatch.setattr(installer, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(installer, "docker_accessible_without_sudo", lambda: True)

    installer.install_docker(False)

    assert shell.ran("docker-ce")
    assert shell.ran("docker-compose-plugin")
    # `docker compose build` relies on buildx on current Docker releases.
    assert shell.ran("docker-buildx-plugin")


def test_skip_install_fails_loudly_when_components_are_missing(installer, monkeypatch):
    wire(installer, monkeypatch, set())

    with pytest.raises(SystemExit):
        installer.install_docker(True)


def test_skip_install_passes_when_everything_is_present(installer, monkeypatch):
    wire(
        installer,
        monkeypatch,
        {"docker"},
        {"docker compose version": 0, "docker info": 0},
    )

    installer.install_docker(True)


def test_non_apt_host_is_rejected_with_guidance(installer, monkeypatch):
    wire(installer, monkeypatch, set())

    with pytest.raises(SystemExit):
        installer.require_apt()


def test_unreachable_docker_signing_key_fails_clearly(installer, monkeypatch):
    wire(
        installer,
        monkeypatch,
        {"apt-get", "curl", "gpg"},
        {"bash -c curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg": 1},
    )

    with pytest.raises(SystemExit):
        installer.configure_docker_apt_repository()


def test_user_is_added_to_the_docker_group_when_it_cannot_reach_the_daemon(
    installer, monkeypatch
):
    shell = wire(installer, monkeypatch, {"docker"}, {"docker info": 1})

    installer.ensure_docker_group_membership()

    assert shell.ran("usermod -aG docker")


def test_user_already_in_the_docker_group_is_left_alone(installer, monkeypatch):
    shell = wire(installer, monkeypatch, {"docker"}, {"docker info": 0})

    installer.ensure_docker_group_membership()

    assert not shell.ran("usermod")


def test_daemon_is_started_when_not_running(installer, monkeypatch):
    shell = wire(installer, monkeypatch, {"docker"})
    states = iter([False, True])
    monkeypatch.setattr(installer, "docker_daemon_running", lambda: next(states))

    installer.ensure_docker_daemon()

    assert shell.ran("systemctl enable --now docker")


def test_daemon_that_never_starts_fails(installer, monkeypatch):
    wire(installer, monkeypatch, {"docker"})
    monkeypatch.setattr(installer, "docker_daemon_running", lambda: False)

    with pytest.raises(SystemExit):
        installer.ensure_docker_daemon()


def test_compose_validation_uses_sudo_before_the_group_takes_effect(installer, monkeypatch):
    # A newly added docker group does not apply to the current session, so
    # validating the compose file has to fall back to sudo.
    recorded = {}

    def fake_run(command, *, sudo=False, check=True, cwd=None):
        recorded["sudo"] = sudo
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(installer, "run_cmd", fake_run)
    monkeypatch.setattr(installer, "docker_accessible_without_sudo", lambda: False)

    installer.compose_config()

    assert recorded["sudo"] is True


def test_compose_validation_skips_sudo_when_it_is_not_needed(installer, monkeypatch):
    recorded = {}

    def fake_run(command, *, sudo=False, check=True, cwd=None):
        recorded["sudo"] = sudo
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(installer, "run_cmd", fake_run)
    monkeypatch.setattr(installer, "docker_accessible_without_sudo", lambda: True)

    installer.compose_config()

    assert recorded["sudo"] is False


def test_invoking_user_prefers_the_sudo_caller(installer, monkeypatch):
    monkeypatch.setenv("SUDO_USER", "vt_user")
    monkeypatch.setenv("USER", "root")

    assert installer.invoking_user() == "vt_user"
