"""Pure placement functions for the fleet controller.

No I/O — all functions are side-effect-free and fully unit-testable.

Host state schema (dict):
    {
        "host": str,            # hostname / IP
        "running": int,         # containers currently running
        "capacity": int,        # max containers supported
        "ram_used_pct": int,    # current RAM used (0-100)
    }
"""
from __future__ import annotations

from typing import Optional


def host_has_room(host_state: dict, headroom_pct: int) -> bool:
    """Return True if the host has enough RAM headroom and capacity.

    Parameters
    ----------
    host_state:   dict with keys 'running', 'capacity', 'ram_used_pct'.
    headroom_pct: minimum free RAM percentage required (0-100).
    """
    if not isinstance(headroom_pct, int) or not (0 <= headroom_pct <= 100):
        raise ValueError(f"headroom_pct must be 0-100, got {headroom_pct!r}")

    running = host_state.get("running", 0)
    capacity = host_state.get("capacity", 0)
    ram_used_pct = host_state.get("ram_used_pct", 100)

    # Must have unused capacity slots
    if capacity <= 0 or running >= capacity:
        return False

    # Must have enough free RAM
    ram_free_pct = 100 - ram_used_pct
    return ram_free_pct >= headroom_pct


def choose_host(
    hosts_state: list[dict],
    headroom_pct: int,
) -> Optional[str]:
    """Greedy least-loaded host selection.

    Picks the host with the lowest number of running containers among those
    that have sufficient RAM headroom. Returns None if no host qualifies.

    Parameters
    ----------
    hosts_state:  List of host state dicts (see module docstring).
    headroom_pct: Minimum free RAM % required (passed to host_has_room).
    """
    eligible = [h for h in hosts_state if host_has_room(h, headroom_pct)]
    if not eligible:
        return None

    # Greedy least-loaded: sort by (running, then host name for determinism)
    best = min(eligible, key=lambda h: (h.get("running", 0), h.get("host", "")))
    return best["host"]


def hosts_full(hosts_state: list[dict], headroom_pct: int) -> bool:
    """Return True when ALL hosts are at capacity or lack RAM headroom."""
    return choose_host(hosts_state, headroom_pct) is None
