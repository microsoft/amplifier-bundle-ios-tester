#!/bin/bash
# Run a command in the Mac's GUI (Aqua) session and return its output.
#
#   ./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
#   GUIRUN_TIMEOUT=1800 ./scripts/guirun.sh '/abs/path/to/scripts/build-device.sh'
#
# WHY: codesign needs the login keychain's PRIVATE KEY, and an ssh session
# cannot reach it. securityd will not release the key to a session that
# cannot present UI ("User interaction is not allowed"). Neither sudo
# (password-gated) nor `launchctl asuser` (needs root) bridges that gap.
# Apple Events DO reach the GUI session from ssh, so Terminal.app can be
# asked to run the command where the keychain is live. Output is
# round-tripped through a file; the exit code is preserved.
set -u

SCRIPT="$1"
STAMP="$$-$(date +%s)"
OUT="/tmp/guirun.out.$STAMP"
DONE="/tmp/guirun.done.$STAMP"
CMD="/tmp/guirun.cmd.$STAMP"
TIMEOUT="${GUIRUN_TIMEOUT:-120}"

rm -f "$OUT" "$DONE" "$CMD"
cat > "$CMD" <<EOF
{ $SCRIPT ; } > "$OUT" 2>&1
echo \$? > "$DONE"
EOF

osascript -e "tell application \"Terminal\" to do script \"bash $CMD ; exit\"" >/dev/null 2>&1

for _ in $(seq 1 "$TIMEOUT"); do
  [ -f "$DONE" ] && break
  sleep 1
done

if [ ! -f "$DONE" ]; then
  echo "!! guirun timed out after ${TIMEOUT}s (partial output below)" >&2
  [ -f "$OUT" ] && cat "$OUT"
  exit 124
fi

cat "$OUT"
RC="$(cat "$DONE")"
rm -f "$OUT" "$DONE" "$CMD"
echo "--- guirun exit=$RC ---"
exit "$RC"
