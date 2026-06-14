"""fake_controller.py — no-op stub controller for the local harness.

The real fleet controller lives in fleet/controller/ and manages GCP container
lifecycle, tenant provisioning, and quota enforcement. For the local two-tenant
smoke harness we don't need any of that — workers talk directly to mock_outbound
and the harness is self-contained.

This stub exists so that:
  (a) docker-compose can reference it as a service if the compose file evolves
      to include a controller dependency.
  (b) imports of fleet.controller patterns don't crash in test environments that
      include this directory on sys.path.

All methods are no-ops that log their arguments and return sensible defaults.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

log = logging.getLogger("fake_controller")


class FakeController:
    """No-op fleet controller stub.

    Exposes the minimal surface that the local harness and future tests may call:
      - provision_tenant(user_id) -> {"status": "ok"}
      - deprovision_tenant(user_id) -> {"status": "ok"}
      - get_tenant_status(user_id) -> {"status": "running", "user_id": user_id}
      - health() -> {"ok": True}
    """

    def provision_tenant(self, user_id: str, **kwargs: Any) -> Dict[str, Any]:
        log.info("fake_controller.provision_tenant user_id=%s kwargs=%s", user_id, kwargs)
        return {"status": "ok", "user_id": user_id}

    def deprovision_tenant(self, user_id: str) -> Dict[str, Any]:
        log.info("fake_controller.deprovision_tenant user_id=%s", user_id)
        return {"status": "ok", "user_id": user_id}

    def get_tenant_status(self, user_id: str) -> Dict[str, Any]:
        log.info("fake_controller.get_tenant_status user_id=%s", user_id)
        return {"status": "running", "user_id": user_id}

    def health(self) -> Dict[str, Any]:
        return {"ok": True}


# Convenience singleton — compose/tests can import `from fake_controller import controller`
controller = FakeController()


def main() -> None:
    """Entrypoint: print health and exit. Used as the compose CMD when included."""
    import json
    logging.basicConfig(level=logging.INFO)
    log.info("fake_controller starting (no-op stub)")
    print(json.dumps(controller.health()))


if __name__ == "__main__":
    main()
