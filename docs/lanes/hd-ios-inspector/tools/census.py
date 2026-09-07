#!/usr/bin/env python3
"""Description-surface census for the `ios_inspector` tool.

Measures, for any checkout of this repo:

* the tool description (chars)
* every `input_schema` parameter description (chars, per parameter)
* the serialized wire block `{name, description, input_schema}` -- the shape a
  provider actually bills, and the measure that reproduces the goal's 10,049
* `context/ios-awareness.md` (chars)

Usage:
    python census.py <checkout>                 # one checkout, JSON
    python census.py <stock> <lean>             # before/after markdown tables

Each checkout is measured in its own subprocess, so two copies of the same
package name never collide in `sys.modules`.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_EXTRACT = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from amplifier_module_tool_ios_inspector import IosInspectorTool
t = IosInspectorTool()
print(json.dumps({"name": t.name, "description": t.description,
                  "input_schema": t.input_schema}))
"""

AWARENESS = "context/ios-awareness.md"


def measure(checkout: str | Path) -> dict:
    """Return the full description surface of one checkout."""
    checkout = Path(checkout).resolve()
    pkg_root = checkout / "modules" / "tool-ios-inspector"
    out = subprocess.run(
        [sys.executable, "-c", _EXTRACT, str(pkg_root)],
        capture_output=True,
        text=True,
        check=True,
    )
    block = json.loads(out.stdout)
    props = block["input_schema"]["properties"]
    params = {k: v["description"] for k, v in props.items() if "description" in v}
    awareness = (checkout / AWARENESS).read_text(encoding="utf-8")
    return {
        "checkout": str(checkout),
        "name": block["name"],
        "description": block["description"],
        "params": params,
        "input_schema": block["input_schema"],
        "awareness": awareness,
        "totals": {
            "tool_description": len(block["description"]),
            "param_descriptions": sum(len(v) for v in params.values()),
            "all_descriptions": len(block["description"])
            + sum(len(v) for v in params.values()),
            "wire_block_json": len(json.dumps(block)),
            "wire_block_json_compact": len(
                json.dumps(block, separators=(",", ":"))
            ),
            "input_schema_json": len(json.dumps(block["input_schema"])),
            "awareness_chars": len(awareness),
            "awareness_bytes": len(awareness.encode("utf-8")),
        },
    }


def _row(label: str, a: int, b: int) -> str:
    delta = b - a
    if delta == 0:
        return f"| {label} | {a:,} | {b:,} | **0 (byte-identical)** |"
    pct = f" ({delta / a:+.1%})" if a else ""
    return f"| {label} | {a:,} | {b:,} | {delta:+,}{pct} |"


def compare(stock: dict, lean: dict) -> str:
    lines: list[str] = []
    lines.append("### Headline surface\n")
    lines.append("| surface | stock | lean | delta |")
    lines.append("|---|---:|---:|---|")
    for key, label in [
        ("tool_description", "`ios_inspector` tool description"),
        ("param_descriptions", "26 parameter descriptions (sum)"),
        ("all_descriptions", "all descriptions"),
        ("input_schema_json", "`input_schema` JSON (untouched)"),
        ("wire_block_json", "wire block `{name,description,input_schema}` JSON"),
        ("wire_block_json_compact", "same, compact separators"),
        ("awareness_chars", "`context/ios-awareness.md` chars"),
        ("awareness_bytes", "`context/ios-awareness.md` bytes"),
    ]:
        lines.append(_row(label, stock["totals"][key], lean["totals"][key]))

    lines.append("\n### Per-description before/after\n")
    lines.append("| description | stock | lean | delta | >600? |")
    lines.append("|---|---:|---:|---|---|")
    lines.append(
        _row("**tool description**", stock["totals"]["tool_description"],
             lean["totals"]["tool_description"])
        + (" yes |" if lean["totals"]["tool_description"] > 600 else " |")
    )
    identical = 0
    for key in sorted(set(stock["params"]) | set(lean["params"])):
        a, b = stock["params"].get(key, ""), lean["params"].get(key, "")
        same = a == b
        identical += same
        mark = "**0 (byte-identical)**" if same else f"{len(b) - len(a):+,}"
        over = "yes" if len(b) > 600 else ""
        lines.append(
            f"| `{key}` | {len(a):,} | {len(b):,} | {mark} | {over} |"
        )
    lines.append(
        f"\n**{identical} of {len(stock['params'])} parameter descriptions are "
        "byte-identical**, verified by string equality (`stock == lean`), not by "
        "length."
    )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) == 2:
        m = measure(argv[1])
        print(json.dumps(m["totals"], indent=2))
        return 0
    if len(argv) == 3:
        print(compare(measure(argv[1]), measure(argv[2])))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
