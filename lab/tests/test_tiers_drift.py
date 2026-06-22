"""Drift guard (WEB-31): the marketing-side tier catalog (web/lib/tiers.ts) is a
hand-maintained MIRROR of the control-plane source of truth
(control-plane/convex/billing/tiers.ts). They live in separate module trees
(Next.js vs Convex), so neither tsc nor next build catches a silent desync.

This hermetic, network-free test parses the tier values out of BOTH files and
asserts they agree field-by-field, so a future edit to one without the other
fails the existing `cd lab && pytest` gate instead of shipping mismatched
prices/quotas to users.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WEB = REPO / "web" / "lib" / "tiers.ts"
CP = REPO / "control-plane" / "convex" / "billing" / "tiers.ts"

TIER_NAMES = ("free", "pro", "max")


def _parse_tiers(text: str) -> dict[str, dict]:
    """Extract {tier_name: {label, priceUsd, msgQuota, channels}} from a tiers.ts.

    Both files declare each tier object as `name: "<x>"` first, then label/
    priceUsd/msgQuota/channels/blurb in the same order, so we slice the text into
    per-tier chunks at each `name: "<tier>"` and read the fields out of each chunk.
    """
    # Start offsets of each tier object, keyed by tier name.
    marks = [(m.start(), m.group(1)) for m in re.finditer(r'name:\s*"(free|pro|max)"', text)]
    out: dict[str, dict] = {}
    for i, (start, name) in enumerate(marks):
        end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
        chunk = text[start:end]
        label = re.search(r'label:\s*"([^"]*)"', chunk)
        price = re.search(r"priceUsd:\s*(-?\d+)", chunk)
        quota = re.search(r"msgQuota:\s*(-?\d+)", chunk)
        channels = re.search(r"channels:\s*\[([^\]]*)\]", chunk)
        assert label and price and quota and channels, f"could not parse tier {name} in chunk:\n{chunk}"
        chans = tuple(sorted(re.findall(r'"([^"]+)"', channels.group(1))))
        out[name] = {
            "label": label.group(1),
            "priceUsd": int(price.group(1)),
            "msgQuota": int(quota.group(1)),
            "channels": chans,
        }
    return out


def test_web_and_control_plane_tier_catalogs_agree():
    assert WEB.exists(), f"missing {WEB}"
    assert CP.exists(), f"missing {CP}"
    web = _parse_tiers(WEB.read_text())
    cp = _parse_tiers(CP.read_text())

    assert set(web) == set(TIER_NAMES), f"web tiers != {TIER_NAMES}: {sorted(web)}"
    assert set(cp) == set(TIER_NAMES), f"control-plane tiers != {TIER_NAMES}: {sorted(cp)}"

    for name in TIER_NAMES:
        assert web[name] == cp[name], (
            f"tier '{name}' DRIFTED between web/lib/tiers.ts and "
            f"control-plane/convex/billing/tiers.ts:\n  web={web[name]}\n  cp ={cp[name]}\n"
            "Update both (control-plane is the source of truth)."
        )


if __name__ == "__main__":
    test_web_and_control_plane_tier_catalogs_agree()
    print("OK: web and control-plane tier catalogs agree")
