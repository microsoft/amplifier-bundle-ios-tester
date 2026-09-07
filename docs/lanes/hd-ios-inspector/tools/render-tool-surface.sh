#!/usr/bin/env bash
# Render the tool-description surface as the OWNER's own session sees it.
#
#   ./render-tool-surface.sh <stock-checkout> <lean-checkout> <out-dir>
#
# Builds ONE fresh scratch AMPLIFIER_HOME per side by COPYING the owner's
# ~/.amplifier/settings.yaml (never moving it, never editing the original) and
# swapping only the single `ios-tester` app entry to a local `file://` path, so
# every other bundle in the owner's real app list is rendered identically on
# both sides and the delta is attributable to this repo alone.
#
# $0: no LLM call, no API key needed -- `amplifier tool list` mounts modules and
# prints schemas, it does not talk to a provider.
#
# SAFETY: `amplifier tool list` under a scratch AMPLIFIER_HOME has been observed
# to rewrite the SHARED uv-tool editable-install `.pth` files to point into the
# scratch cache. This script snapshots their md5s before and after and refuses
# to exit quietly if any changed.
set -euo pipefail

STOCK="$(cd "${1:?usage: render-tool-surface.sh <stock> <lean> <out>}" && pwd)"
LEAN="$(cd "${2:?usage: render-tool-surface.sh <stock> <lean> <out>}" && pwd)"
OUT="${3:?usage: render-tool-surface.sh <stock> <lean> <out>}"; mkdir -p "$OUT"

OWNER_SETTINGS="${AMPLIFIER_OWNER_SETTINGS:-$HOME/.amplifier/settings.yaml}"
SITE_PACKAGES="$(ls -d "$HOME"/.local/share/uv/tools/amplifier/lib/python*/site-packages | head -1)"

owner_md5() { md5sum "$OWNER_SETTINGS" | awk '{print $1}'; }
pth_md5() { (cd "$SITE_PACKAGES" && md5sum ./*.pth 2>/dev/null | sort); }

OWNER_BEFORE="$(owner_md5)"
pth_md5 > "$OUT/pth-before.md5"

render() {  # render <label> <checkout>
  local label="$1" checkout="$2"
  local home="$OUT/scratch-home-$label"
  rm -rf "$home"; mkdir -p "$home"
  python3 - "$OWNER_SETTINGS" "$home/settings.yaml" "$checkout" <<'PY'
import sys, pathlib
src, dst, checkout = sys.argv[1], sys.argv[2], sys.argv[3]
text = pathlib.Path(src).read_text()
out, swapped = [], 0
for line in text.splitlines(keepends=True):
    if "amplifier-bundle-ios-tester" in line and line.lstrip().startswith("- "):
        indent = line[: len(line) - len(line.lstrip())]
        out.append(f"{indent}- file://{checkout}/behaviors/ios-tester.yaml\n")
        swapped += 1
    else:
        out.append(line)
assert swapped == 1, f"expected exactly 1 ios-tester app entry, found {swapped}"
pathlib.Path(dst).write_text("".join(out))
PY
  AMPLIFIER_HOME="$home" amplifier tool list --format json 2>/dev/null \
    | sed -n '/^[[{]/,$p' > "$OUT/tool-list-$label.json"
  AMPLIFIER_HOME="$home" amplifier tool info ios_inspector --format json 2>/dev/null \
    | sed -n '/^{/,$p' > "$OUT/ios-inspector-$label.json"
}

render stock "$STOCK"
render lean "$LEAN"

python3 - "$OUT" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])


def load(label):
    data = json.loads((out / f"tool-list-{label}.json").read_text())
    tools = data["tools"] if isinstance(data, dict) and "tools" in data else data
    return {
        t["name"]: (t.get("config_summary", {}).get("description") or "")
        for t in tools
    }


rows = []
for label in ("stock", "lean"):
    d = load(label)
    total = sum(len(v.encode()) for v in d.values())
    ios = len(d.get("ios_inspector", "").encode())
    rows.append((label, len(d), total, ios))
    print(f"{label:<6} tools={len(d):<4} all-description bytes={total:<8} ios_inspector={ios}")

(_, n0, t0, i0), (_, n1, t1, i1) = rows
assert n0 == n1, f"tool count changed between sides: {n0} vs {n1}"
print(f"\nios_inspector description : {i0} -> {i1}  ({i1 - i0:+d}, {(i1 - i0) / i0:+.1%})")
print(f"owner's whole tool surface: {t0} -> {t1}  ({t1 - t0:+d}, {(t1 - t0) / t0:+.1%})")
print(f"this repo's share of it   : {i0 / t0:.2%} -> {i1 / t1:.2%}")
(out / "summary.json").write_text(json.dumps({
    "tools_mounted": n0,
    "all_tool_descriptions_bytes": {"stock": t0, "lean": t1, "delta": t1 - t0},
    "ios_inspector_description_bytes": {"stock": i0, "lean": i1, "delta": i1 - i0},
}, indent=2))
PY

# --- safety: the owner's settings and the shared .pth files must be untouched -
pth_md5 > "$OUT/pth-after.md5"
[ "$OWNER_BEFORE" = "$(owner_md5)" ] || { echo "FAIL: owner settings.yaml changed"; exit 1; }
if ! diff -q "$OUT/pth-before.md5" "$OUT/pth-after.md5" >/dev/null; then
  echo "FAIL: shared uv-tool .pth files were rewritten -- restore from backup"
  diff "$OUT/pth-before.md5" "$OUT/pth-after.md5" || true
  exit 1
fi
echo "SAFETY OK: owner settings.yaml md5 unchanged; $(wc -l < "$OUT/pth-after.md5") .pth files unchanged."
