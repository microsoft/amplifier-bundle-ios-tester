#!/usr/bin/env bash
# Reproduce this lane's always-on surface measurement. $0, no LLM call, no network beyond
# the git+ module sources the scratch bundle pins.
#
#   ./render-catalog.sh <path-to-amplifier-bundle-ios-tester-checkout> <out-dir>
#
# Renders the two always-on surfaces this repo contributes to EVERY turn of EVERY session:
#   1. the delegate tool's own description -- the "Available agents:" catalog
#   2. the hooks-skills-visibility block -- the "Available skills" index
# from a scratch bundle containing ONLY the given checkout plus tool-delegate and tool-skills.
set -euo pipefail
REPO="$(cd "${1:?usage: render-catalog.sh <repo-checkout> <out-dir>}" && pwd)"
OUT="${2:?usage: render-catalog.sh <repo-checkout> <out-dir>}"; mkdir -p "$OUT"
WORK="$(mktemp -d)"
trap 'amplifier bundle remove kp79-ios-scratch >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT
cat > "$WORK/bundle.md" <<YAML
---
bundle:
  name: kp79-ios-scratch
  version: 0.0.1
  description: Scratch session for rendering the delegate agent catalog.
includes:
  - bundle: $REPO/bundle.md
session:
  raw: true
  orchestrator:
    module: loop-streaming
    source: git+https://github.com/microsoft/amplifier-module-loop-streaming@main
  context:
    module: context-simple
    source: git+https://github.com/microsoft/amplifier-module-context-simple@main
tools:
  - module: tool-delegate
    source: git+https://github.com/microsoft/amplifier-foundation@main#subdirectory=modules/tool-delegate
---
YAML
amplifier bundle add "file://$WORK" --name kp79-ios-scratch >/dev/null
amplifier tool info delegate -b kp79-ios-scratch --format json 2>/dev/null \
  | sed -n '/^{/,$p' > "$OUT/delegate-tool-info.json"

python3 - "$OUT" <<'PY'
import json, re, sys, pathlib
out = pathlib.Path(sys.argv[1])
d = json.loads((out / "delegate-tool-info.json").read_text())["config_summary"]["description"]
(out / "delegate-description.txt").write_text(d)
marker = "Available agents:\n"
cat = d[d.index(marker) + len(marker):]
(out / "agent-catalog-FULL.txt").write_text(cat)
starts = [m.start() for m in re.finditer(r"(?m)^  - [A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+: ", cat)]
slice_txt, tot = [], 0
for i, s in enumerate(starts):
    blk = cat[s:(starts[i + 1] if i + 1 < len(starts) else len(cat))]
    if blk.startswith("  - ios-tester:"):
        tot += len(blk.encode()); slice_txt.append(blk)
        print(f"{blk.split(':')[1]:<24}{len(blk.encode()):>7}")
(out / "agent-catalog-ios-tester-slice.txt").write_text("".join(slice_txt))
print(f"{'-'*31}\nios-tester catalog slice{tot:>7} bytes")
print(f"full agent catalog{len(cat.encode()):>13} bytes ({len(starts)} entries)")
print(f"delegate description{len(d.encode()):>11} bytes")
PY

# --- the hooks-skills-visibility block, rendered by the shipped hook itself ---
python3 - "$REPO" "$OUT" <<'PY'
import glob, sys, pathlib, importlib.util
repo, out = sys.argv[1], pathlib.Path(sys.argv[2])
pkg = sorted(glob.glob(str(pathlib.Path.home() /
      ".amplifier/cache/*/amplifier-bundle-skills-*/modules/tool-skills")) +
      glob.glob(str(pathlib.Path.home() /
      ".amplifier/cache/amplifier-bundle-skills-*/modules/tool-skills")))
if not pkg:
    print("tool-skills not found in cache; skills block NOT rendered"); raise SystemExit(0)
sys.path.insert(0, pkg[-1])
from amplifier_module_tool_skills.discovery import discover_skills
from amplifier_module_tool_skills.hooks import SkillsVisibilityHook
skills = discover_skills(pathlib.Path(repo) / "skills")
hook = SkillsVisibilityHook(skills=skills, config={})
block = hook._format_skills_list(skills)
(out / "skills-visibility.txt").write_text(block)
print(f"skills-visibility block{len(block.encode()):>8} bytes ({len(skills)} skills)")
PY
