#!/usr/bin/env bash
# Run the Snake CodeChallenge bot (OOP refactor): connects over websocket
# and auto-plays challenges.
#
# Usage: ./start.sh <auth_token> [extra args, e.g. --board]
#   <auth_token> is your Bot token from the web app (auth_app Bot.token).
set -euo pipefail
cd "$(dirname "$0")"

# Provision the venv on first run (only dependency is websockets).
if [ ! -d .venv ]; then
    echo "Creating .venv and installing dependencies..." >&2
    python3 -m venv .venv
    ./.venv/bin/pip install -q -r requirements.txt
fi
# shellcheck disable=SC1091
source .venv/bin/activate

if [ "$#" -lt 1 ]; then
    echo "Usage: ./start.sh <auth_token> [extra args]" >&2
    echo "  Get the token from the web app (your Bot's token)." >&2
    echo "  https://codechallenge.up.railway.app/mybots " >&2
    exit 1
fi

TOKEN="$1"
shift  # remaining args (e.g. --board, --local) get forwarded through

python -m snake.main "$TOKEN" "$@"