"""Runnable self-check for features.web_search — issues a REAL Exa query and
asserts we get back at least one result with a URL. Prints the top 3.

Run:  python3 features/web_search/self_check.py
Exit code 0 on success, 1 on failure. No test framework, no fixtures.
"""
import os
import sys

# Allow running as a loose script (python3 features/web_search/self_check.py)
# by putting the repo root (…/features/..) on sys.path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from features.web_search import answer, web_search  # noqa: E402


def main() -> int:
    query = "latest SpaceX launch"
    print(f"[self-check] web_search({query!r}) ...")
    results = web_search(query, num_results=5)

    # Hard assertions: the whole point of the module.
    assert isinstance(results, list), f"expected list, got {type(results)}"
    assert len(results) >= 1, "expected >=1 result"
    top = results[0]
    assert top.get("url"), f"top result has no url: {top!r}"
    assert top["url"].startswith("http"), f"url not http(s): {top['url']!r}"

    print(f"[self-check] got {len(results)} results. Top 3:")
    for i, r in enumerate(results[:3], 1):
        snip = (r.get("snippet") or "")[:120].replace("\n", " ")
        pub = r.get("published") or "n/a"
        print(f"  {i}. {r['title']}")
        print(f"     url: {r['url']}")
        print(f"     published: {pub}")
        print(f"     snippet: {snip}")

    # Exercise answer() too (it has a synthesis fallback, so it must return a string).
    ans = answer(query)
    assert isinstance(ans, str) and ans.strip(), "answer() returned empty"
    print(f"[self-check] answer() -> {len(ans)} chars; first line: {ans.splitlines()[0][:120]}")

    print("[self-check] PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as e:
        print(f"[self-check] FAIL: {e}", file=sys.stderr)
        raise SystemExit(1)
