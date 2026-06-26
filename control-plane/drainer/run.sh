#!/bin/bash
# Eve drainer launcher (runs from ~/.eve-drainer, a TCC-safe dotfolder under launchd).
# Sources the shared worker env (Convex/Sendblue/Telegram creds) + the Eve ingress env,
# then execs the Node drainer. launchd does NOT inherit a shell PATH, so node is resolved
# by absolute path with a fallback.
set -a
[ -f /Users/saveliy/.hermes-savedlab/.env ] && source /Users/saveliy/.hermes-savedlab/.env
[ -f /Users/saveliy/.eve-drainer/eve.env ] && source /Users/saveliy/.eve-drainer/eve.env
set +a
NODE=/Users/saveliy/.nvm/versions/node/v24.18.0/bin/node
[ -x "$NODE" ] || NODE=/Users/saveliy/.hermes/node/bin/node
exec "$NODE" /Users/saveliy/.eve-drainer/drainer.mjs
