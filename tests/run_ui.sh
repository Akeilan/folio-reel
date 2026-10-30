#!/bin/sh
# Run a UI test script inside Folio Reel on an X display (Xvfb): run_ui.sh script.py [project]
HERE="$(cd "$(dirname "$0")" && pwd)"
export FOLIO_TEST_SCRIPT="$HERE/$1" FOLIO_REEL_SHARE="${FOLIO_REEL_SHARE:-$HERE/../share}"
export XDG_CONFIG_HOME="$(mktemp -d)" FOLIO_TEST_DELAY=1500 UI_OUT="${UI_OUT:-/tmp/ui_out_reel}"
export FOLIO_REEL_AUDIOSINK="${FOLIO_REEL_AUDIOSINK:-fakesink}" HOME="${REEL_TEST_HOME:-$(mktemp -d)}"
cd "$HERE/../app"
if [ -n "$2" ]; then exec timeout ${UI_TIMEOUT:-400} python3 -m folio_reel "$2"; fi
exec timeout ${UI_TIMEOUT:-400} python3 -m folio_reel
