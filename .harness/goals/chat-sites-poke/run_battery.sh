#!/usr/bin/env bash
# Run the chat-sites build battery IN PARALLEL through the real heavy-lane probe.
# Each prompt -> one background `build_probe.py`; collect JSON verdicts; summarize.
# Usage: run_battery.sh <out-dir>   (defaults to a tmp dir under the harness)
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="${1:-$HERE/battery-$(date +%s)}"
mkdir -p "$OUT"
PROBE="$HERE/build_probe.py"
PY=/usr/bin/python3

# id|kind|prompt
BATTERY=(
"s1|static|сделай лендинг для маленькой пекарни «Корица»: тёплый уют, секции о нас / меню / контакты, приятные тёплые цвета. на своё усмотрение. опубликуй и пришли ссылку."
"s2|static|сделай мне страничку-портфолио для веб-дизайнера Артёма: пара проектов, блок обо мне, контакт-кнопка. сам придумай детали. опубликуй и пришли ссылку."
"s3|static|make me a link-in-bio page for a musician named Kai: links to spotify, youtube, instagram, a short bio. your call on the design. publish it and send the link."
"s4|static|сделай лендинг для кофейни у моря «Бриз»: hero с названием, меню-хайлайты, часы работы, атмосфера. на своё усмотрение. пришли ссылку."
"a1|app|сделай гостевую книгу для нашей вечеринки: форма имя + сообщение и список оставленных записей снизу. на своё усмотрение. опубликуй и пришли ссылку."
"a2|app|сделай голосовалку-счётчик: кошки против собак, две кнопки, показывай количество голосов и проценты, данные сохраняются для всех. сам реши как. пришли ссылку."
)

# Run in WAVES of MAXCONC (macOS bash 3.2 has no `wait -n`): concurrent model
# load past ~3 slows every build and risks the timeout. Waves keep it sane.
MAXCONC="${MAXCONC:-3}"
i=0
while [ $i -lt ${#BATTERY[@]} ]; do
  pids=()
  for ((j=0; j<MAXCONC && i<${#BATTERY[@]}; j++, i++)); do
    row="${BATTERY[$i]}"
    id="${row%%|*}"; rest="${row#*|}"; kind="${rest%%|*}"; prompt="${rest#*|}"
    ( $PY "$PROBE" --kind "$kind" --label "$id" --prompt "$prompt" \
        >"$OUT/$id.json" 2>"$OUT/$id.err"; echo "$?" >"$OUT/$id.exit" ) &
    pids+=("$!")
    echo "launched $id ($kind) pid=$!"
  done
  echo "waiting for wave (${#pids[@]} builds)..."
  for p in "${pids[@]}"; do wait "$p"; done
done

echo "=== SUMMARY ($OUT) ==="
$PY - "$OUT" <<'PY'
import json, glob, os, sys
out = sys.argv[1]
ok = tot = 0
for f in sorted(glob.glob(os.path.join(out, "*.json"))):
    tot += 1
    try:
        d = json.load(open(f))
    except Exception:
        print(f"PARSE_FAIL {os.path.basename(f)}"); continue
    ok += 1 if d.get("ok") else 0
    print(f"{d.get('label'):>3} {d.get('kind'):6} ok={str(d.get('ok')):5} "
          f"inturn={str(d.get('built_in_turn')):5} 200={str(d.get('http_200')):5} "
          f"clean={str(d.get('clean')):5} bytes={d.get('html_bytes')} "
          f"db={d.get('has_db_runtime')} rt={d.get('data_roundtrip')} "
          f"tabs={d.get('agent_tables')} {d.get('elapsed')}s {d.get('error','')} {d.get('url','')}")
print(f"\nPASS {ok} / {tot}")
PY
echo "OUTDIR=$OUT"
