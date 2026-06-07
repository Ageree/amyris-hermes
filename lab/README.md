# Phase 0 Lab

Personal lab: Hermes agent + saved-content skill.
- skills/saved-content/ — the skill (symlinked into ~/.hermes/skills/)
- golden/ — 20 real bookmarks + ratings (golden set, SC-001)
- tests/ — pytest for the skill's scripts

Setup: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
Run tests: cd lab && pytest
