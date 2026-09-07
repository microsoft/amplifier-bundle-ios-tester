#!/usr/bin/env python3
"""Run foundation's `validate-agents` gate deterministically, for $0.

`recipes/validate-agents.yaml` has six phases. The first four --
`environment-check`, `agent-discovery`, `structural-validation`,
`quality-classification` -- are plain `bash` steps whose bodies are Python;
they are where the pass/fail gate is actually decided (structural ERRORs,
`<example>`/`<commentary>` blocks, the >600-token description ceiling, the
`model_role` vocabulary). Only the later report/approval phases call a model.

This runner executes those four steps VERBATIM out of the shipped recipe --
it does not reimplement them -- substituting the `{{repo_path}}`,
`{{discovery_results}}` and `{{structural_results}}` template variables the
recipe engine would. No API calls, no spend.

Usage:
    python run_validate_agents.py <recipe.yaml> <repo-path>
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

DETERMINISTIC_STEPS = (
    "environment-check",
    "agent-discovery",
    "structural-validation",
    "quality-classification",
)


def run_step(command: str, substitutions: dict[str, str]) -> str:
    for key, value in substitutions.items():
        command = command.replace("{{" + key + "}}", value)
    proc = subprocess.run(
        ["bash", "-c", command], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise SystemExit(f"step failed ({proc.returncode}):\n{proc.stderr}")
    return proc.stdout.strip()


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    recipe = yaml.safe_load(Path(argv[1]).read_text())
    repo = str(Path(argv[2]).resolve())
    steps = {s["id"]: s for s in recipe["steps"] if s.get("id")}

    subs = {"repo_path": repo}
    outputs: dict[str, str] = {}
    for step_id in DETERMINISTIC_STEPS:
        out = run_step(steps[step_id]["command"], subs)
        outputs[step_id] = out
        name = steps[step_id].get("output")
        if name:
            subs[name] = out

    structural = json.loads(outputs["structural-validation"])
    quality = json.loads(outputs["quality-classification"])

    print(f"recipe: {recipe['name']} v{recipe.get('version')}")
    print(f"repo:   {repo}")
    print(
        "agents: {total} | passed structural: {passed} | ERRORs: {errors} | "
        "WARNINGs: {warnings}".format(**structural["summary"])
    )
    for agent in structural["agents"]:
        codes = [e["code"] for e in agent.get("errors", [])]
        warns = [w["code"] for w in agent.get("warnings", [])]
        print(
            f"  - {agent['name']:<20} desc={agent.get('description_length', 0):>5}c "
            f"examples={agent.get('example_count', 0)} "
            f"commentary={agent.get('commentary_count', 0)} "
            f"ERRORS={codes or '-'} WARNINGS={warns or '-'}"
        )
    print(json.dumps(quality, indent=2)[:2000])

    verdict = quality.get("overall_status") or quality.get("status")
    failed = structural["summary"]["errors"] > 0
    print(f"\nVERDICT: {'FAIL' if failed else 'PASS'}   (quality gate: {verdict})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
