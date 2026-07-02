from __future__ import annotations

import json
import subprocess

from gce_driver import GceVmConfig, GceVmDriver


def _cfg() -> GceVmConfig:
    return GceVmConfig(
        project="p",
        zone="europe-west4-a",
        machine_type="e2-standard-2",
        boot_disk_size="40GB",
        service_account="sa@p.iam.gserviceaccount.com",
        network="",
        subnetwork="",
        scopes="cloud-platform",
        tags=("hermes-tenant",),
        labels=("app=hermes",),
    )


def _cp(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def test_create_with_container_command_shape() -> None:
    calls: list[list[str]] = []

    def run(cmd, **kwargs):  # noqa: ARG001
        calls.append(cmd)
        if "describe" in cmd:
            return _cp(returncode=1)
        return _cp()

    driver = GceVmDriver(_cfg(), run_cmd=run)
    out = driver.run(
        "img",
        "hermes-u1",
        {"USER_ID": "u1", "CONVEX_URL": "https://x"},
        ["/data/tenants/u1:/data/tenants/u1"],
    )
    assert out == "hermes-u1"
    create = calls[-1]
    assert create[:4] == ["gcloud", "compute", "instances", "create-with-container"]
    assert "hermes-u1" in create
    assert "--container-image" in create and "img" in create
    assert "--container-env" in create and "USER_ID=u1" in create
    assert "--project" in create and "p" in create
    assert "--zone" in create and "europe-west4-a" in create
    assert any("mount-path=/data/tenants/u1" in arg for arg in create)


def test_existing_stopped_vm_is_started_not_recreated() -> None:
    calls: list[list[str]] = []

    def run(cmd, **kwargs):  # noqa: ARG001
        calls.append(cmd)
        if "describe" in cmd:
            return _cp(json.dumps({"name": "hermes-u1", "status": "TERMINATED"}))
        return _cp()

    driver = GceVmDriver(_cfg(), run_cmd=run)
    assert driver.run("img", "hermes-u1", {}, []) == "hermes-u1"
    assert any("start" in c for c in calls[-1])
    assert not any("create-with-container" in c for call in calls for c in call)
