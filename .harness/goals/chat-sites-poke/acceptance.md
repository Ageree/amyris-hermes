# Acceptance criteria — chat-sites works like Poke

Each row is re-verified from scratch by the auditor. The probe harness is
`.harness/goals/chat-sites-poke/build_probe.py` — it runs ONE real heavy-lane
build (`hermes chat --quiet` in the operator HERMES_HOME, env sourced), cleans the
reply with the bridge's regexes, then checks deploy + cleanliness + (for apps)
data round-trip, printing a JSON verdict. `--keep` leaves the site; default
deletes the probe site + its Turso DB after checking.

| # | Criterion | How the auditor verifies | PASS condition |
|---|-----------|--------------------------|----------------|
| AC1 | Build requests route to the heavy lane; chat does not | `python3 lab/tests/test_fast_lane_build_routing.py` | exit 0 |
| AC2 | Static build-in-turn: deploy + clean reply | `python3 .harness/goals/chat-sites-poke/build_probe.py --kind static --prompt "<varied>"` for the 4 battery prompts | each: `ok:true`, reply has exactly one `/s/<handle>` URL, URL HTTP 200, html_bytes ≥ 2000, no chrome leak, built_in_turn:true |
| AC3 | App build-in-turn: Turso + data round-trip | `python3 .harness/goals/chat-sites-poke/build_probe.py --kind app --prompt "<guestbook/poll>"` for ≥2 app prompts | each: `ok:true`, page has `window.dbQuery`, data INSERT then SELECT returns the row (`data_roundtrip:true`) |
| AC4 | Output is genuinely good ("like Poke") | Independent judge fetches each built URL and rates the HTML | every static site ≥ 4/5 (real personalized content, layout, mobile-friendly, not broken/placeholder) |
| AC5 | Reliable across a battery | Run the full battery (≥6 builds: 4 static + 2 app) in one pass | ≥ 90% `ok:true` AND 0 chrome leaks AND 0 interrogation-only replies; a second pass is also green |
| AC6 | No regression | `python3 -m pytest lab/tests/test_fast_lane*.py lab/tests/test_worker_fast_lane.py lab/tests/test_create_site_seed.py -q` + `launchctl list | grep com.savedcontent.worker` (col2 == 0) | all tests pass; worker PID alive, last exit 0 |

## Verification commands (exact)
```bash
# AC1
/usr/bin/python3 lab/tests/test_fast_lane_build_routing.py

# AC2 / AC3 / AC5 — battery (probe sources ~/.hermes-savedlab/.env internally)
/usr/bin/python3 .harness/goals/chat-sites-poke/build_probe.py --kind static \
  --prompt "сделай лендинг для пекарни «Корица», тёплый уют, меню и контакты, на своё усмотрение"
/usr/bin/python3 .harness/goals/chat-sites-poke/build_probe.py --kind app \
  --prompt "сделай гостевую книгу для нашей команды, на своё усмотрение"

# AC6
/usr/bin/python3 -m pytest lab/tests/test_fast_lane.py lab/tests/test_fast_lane_build_routing.py \
  lab/tests/test_worker_fast_lane.py lab/tests/test_create_site_seed.py -q
launchctl list | grep com.savedcontent.worker
```

## Done means
AC1–AC6 all PASS in an isolated audit, with the battery green on TWO independent
passes (reliability, not luck). Probe junk cleaned up.
