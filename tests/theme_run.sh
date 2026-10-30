#!/bin/sh
# X2-01: ui_theme.py under a dark desktop (app dark, and app set to light) and a loud coloured one.
# theme_run.sh [run_ui.sh|run_installed.sh]
HERE="$(cd "$(dirname "$0")" && pwd)"
RUN="${1:-run_ui.sh}"
S=ui_theme.py; [ "$RUN" = run_installed.sh ] && S="$HERE/ui_theme.py"
export REEL_TEST_HOME="$(mktemp -d)"
rc=0
for combo in dark:dark dark:light colour:light; do
  t=${combo%%:*}; f=${combo#*:}
  echo "-- theme $t ${f:+(app $f)}"
  GTK_THEME=$(HOME="$REEL_TEST_HOME" python3 -c "import sys; sys.path.insert(0, '$HERE'); import themecheck; print(themecheck.theme_env('$t')['GTK_THEME'])") \
    FOLIO_THEME=$f sh "$HERE/$RUN" $S || rc=1
done
exit $rc
