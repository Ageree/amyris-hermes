"""Tests for placement.py — pure functions, no I/O."""
from __future__ import annotations

import pytest

from placement import choose_host, host_has_room, hosts_full


def _host(name: str, running: int = 0, capacity: int = 10, ram_used_pct: int = 50) -> dict:
    return {
        "host": name,
        "running": running,
        "capacity": capacity,
        "ram_used_pct": ram_used_pct,
    }


class TestHostHasRoom:
    def test_has_room_when_low_load(self):
        h = _host("h1", running=2, capacity=10, ram_used_pct=40)
        assert host_has_room(h, headroom_pct=30) is True

    def test_no_room_when_ram_too_high(self):
        h = _host("h1", running=2, capacity=10, ram_used_pct=80)
        # Only 20% free, need 30%
        assert host_has_room(h, headroom_pct=30) is False

    def test_no_room_when_capacity_full(self):
        h = _host("h1", running=10, capacity=10, ram_used_pct=20)
        assert host_has_room(h, headroom_pct=30) is False

    def test_no_room_when_capacity_zero(self):
        h = _host("h1", running=0, capacity=0, ram_used_pct=10)
        assert host_has_room(h, headroom_pct=30) is False

    def test_exactly_at_headroom_boundary(self):
        # 70% used → 30% free; headroom_pct=30 → exactly satisfies
        h = _host("h1", running=1, capacity=10, ram_used_pct=70)
        assert host_has_room(h, headroom_pct=30) is True

    def test_one_below_headroom_boundary(self):
        # 71% used → 29% free; headroom_pct=30 → not enough
        h = _host("h1", running=1, capacity=10, ram_used_pct=71)
        assert host_has_room(h, headroom_pct=30) is False

    def test_invalid_headroom_raises(self):
        h = _host("h1")
        with pytest.raises(ValueError):
            host_has_room(h, headroom_pct=150)


class TestChooseHost:
    def test_picks_least_loaded(self):
        hosts = [
            _host("h1", running=5),
            _host("h2", running=2),   # least loaded
            _host("h3", running=8),
        ]
        assert choose_host(hosts, headroom_pct=30) == "h2"

    def test_returns_none_when_all_full(self):
        hosts = [
            _host("h1", running=10, capacity=10),
            _host("h2", running=10, capacity=10),
        ]
        assert choose_host(hosts, headroom_pct=30) is None

    def test_returns_none_when_all_lack_ram(self):
        hosts = [
            _host("h1", running=1, capacity=10, ram_used_pct=80),
            _host("h2", running=1, capacity=10, ram_used_pct=75),
        ]
        assert choose_host(hosts, headroom_pct=30) is None

    def test_skips_hosts_without_ram_headroom(self):
        hosts = [
            _host("h1", running=1, capacity=10, ram_used_pct=80),  # no room
            _host("h2", running=3, capacity=10, ram_used_pct=40),  # ok
        ]
        assert choose_host(hosts, headroom_pct=30) == "h2"

    def test_empty_list_returns_none(self):
        assert choose_host([], headroom_pct=30) is None

    def test_deterministic_on_equal_load(self):
        hosts = [
            _host("b-host", running=2),
            _host("a-host", running=2),
        ]
        # Should pick "a-host" (alphabetically first as tiebreak)
        assert choose_host(hosts, headroom_pct=30) == "a-host"

    def test_single_host_with_room(self):
        hosts = [_host("only", running=0, capacity=10, ram_used_pct=20)]
        assert choose_host(hosts, headroom_pct=30) == "only"


class TestHostsFull:
    def test_all_full_returns_true(self):
        hosts = [
            _host("h1", running=10, capacity=10),
        ]
        assert hosts_full(hosts, headroom_pct=30) is True

    def test_not_all_full_returns_false(self):
        hosts = [
            _host("h1", running=10, capacity=10),
            _host("h2", running=1, capacity=10, ram_used_pct=20),
        ]
        assert hosts_full(hosts, headroom_pct=30) is False

    def test_empty_list_is_full(self):
        # No hosts = nowhere to place = "full"
        assert hosts_full([], headroom_pct=30) is True
