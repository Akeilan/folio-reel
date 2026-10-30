#!/bin/bash
# Folio Reel release checks: engine, render and UI tests, desktop themes and the command walk (source,
# on 22.04), the .deb, then the installed package on 22.04, the second 22.04 machine and 24.04, and a
# Wayland pass on 24.04.   XD=<X display> tools/release.sh
set -u
R=/home/claude/folio-reel
XD=${XD:-95}
V=$(sed -n 's/^Version: //p' $R/packaging/DEBIAN/control)
/home/claude/mounts.sh >/dev/null 2>&1
pgrep -x Xvfb -a | grep -q ":$XD " || { rm -f /tmp/.X$XD-lock /tmp/.X11-unix/X$XD; setsid -f Xvfb :$XD -screen 0 1600x1000x24 -nolisten tcp </dev/null >/dev/null 2>&1; sleep 1; }
UI=${UI_TESTS:-ui_basic.py ui_record.py}
MIC="FOLIO_REEL_AUDIOSRC='audiotestsrc is-live=true freq=500'"
mkdir -p /srv/jammy/src/reel && rsync -a --delete --exclude .git $R/ /srv/jammy/src/reel/
if [ -z "${INSTALLED_ONLY:-}" ]; then
echo "== engine"
chroot /srv/jammy bash -c "cd /src/reel; python3 tests/test_engine.py; python3 tests/test_cli.py" 2>&1 | grep -E '^FAIL|checks|FAILED|Traceback'
echo "== ui (source)"
for u in $UI; do
  echo $u
  chroot /srv/jammy bash -c "cd /src/reel; export $MIC; DISPLAY=:$XD UI_TIMEOUT=500 sh tests/run_ui.sh $u 2>&1 | grep -E '^FAIL|checks|Traceback'"
done
echo "== desktop themes"
chroot /srv/jammy bash -c "cd /src/reel; DISPLAY=:$XD UI_TIMEOUT=400 sh tests/theme_run.sh 2>&1 | grep -E '^--|^FAIL|checks|Traceback'"
echo "== walk"
chroot /srv/jammy bash -c "cd /src/reel; DISPLAY=:$XD UI_TIMEOUT=1500 sh tests/run_ui.sh command_walk.py 2>&1 | grep -E '^ok|^FAIL|checks|Traceback'"
fi
echo "== deb"
sh $R/build-deb.sh /home/claude/out && ls -la /home/claude/out/folio-reel_${V}_all.deb
for m in ${MACHINES:-/srv/jammy /srv/nolo /srv/noble}; do
  cp /home/claude/out/folio-reel_${V}_all.deb $m/tmp/
  flock /home/claude/.dpkg.lock chroot $m bash -c "DEBIAN_FRONTEND=noninteractive apt-get install -y -q /tmp/folio-reel_${V}_all.deb >/tmp/reel-install.log 2>&1 || tail -5 /tmp/reel-install.log; dpkg -l folio-reel | tail -1 | awk '{print \$1, \$3}'; folio-reel --version"
  rm -rf $m/tmp/reeltests; mkdir -p $m/tmp/reeltests; cp -r $R/tests/* $m/tmp/reeltests/
  echo "== installed in $m"
  chroot $m bash -c "cd /tmp/reeltests; export PYTHONPATH=/usr/lib/folio-reel; python3 test_engine.py 2>&1 | grep -E '^FAIL|checks'; REEL_CMD=/usr/bin/folio-reel python3 test_cli.py 2>&1 | grep -E '^FAIL|checks'"
  for u in $UI; do
    chroot $m bash -c "cd /tmp/reeltests; export $MIC; DISPLAY=:$XD UI_TIMEOUT=500 sh run_installed.sh /tmp/reeltests/$u 2>&1 | grep -E '^FAIL|checks|Traceback'"
  done
  chroot $m bash -c "cd /tmp/reeltests; DISPLAY=:$XD UI_TIMEOUT=400 sh theme_run.sh run_installed.sh 2>&1 | grep -E '^--|^FAIL|checks|Traceback'"
done
echo "== Wayland (Weston) on 24.04"
cp /home/claude/folio-suite/tests/wl.sh /srv/noble/tmp/wl.sh
chroot /srv/noble bash -c "cd /tmp/reeltests; DISPLAY=:$XD UI_TIMEOUT=600 /tmp/wl.sh sh -c 'sh run_installed.sh /tmp/reeltests/ui_basic.py; sh theme_run.sh run_installed.sh' 2>&1 | grep -E '^-- |^FAIL|checks|Traceback'"
exit 0
