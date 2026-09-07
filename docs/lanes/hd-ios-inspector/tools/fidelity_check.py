#!/usr/bin/env python3
"""Stock-vs-lean semantic gate for the `ios_inspector` description surface.

Every identifier-shaped token in the STOCK surface must still appear in the
LEAN surface. "Surface" means the whole wire block a provider is shown --
the tool description *plus* every `input_schema` parameter description --
because a semantic moved from one into the other is not lost, it is relocated.

A token is identifier-shaped when it contains `_` or `.`, or is an ALL-CAPS
word longer than two characters. Those are the field names, config keys,
operation names, and emphasis markers that carry the contracts this lane must
not drop.

Usage:
    python fidelity_check.py <stock-checkout> <lean-checkout>

Exit 0 when nothing is absent; exit 1 and print every residual token otherwise.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from census import measure  # noqa: E402

_WORD = re.compile(r"[A-Za-z0-9_.\-/]+")

# English prose abbreviations that the `.` rule would otherwise mistake for
# identifiers. Named here rather than filtered silently: dropping "i.e" is a
# wording change, not a lost contract, and the DONE-NOTE says so.
PROSE_ABBREVIATIONS = frozenset({"i.e", "e.g", "vs", "etc"})


def tokens(text: str) -> set[str]:
    """Identifier-shaped tokens: anything with `_`/`.`, or ALL-CAPS > 2 chars."""
    out: set[str] = set()
    for raw in _WORD.findall(text):
        for piece in re.split(r"[/\-]", raw):
            piece = piece.strip(".,;:'\"()")
            if not piece or piece in PROSE_ABBREVIATIONS:
                continue
            if "_" in piece or "." in piece:
                out.add(piece)
            elif len(piece) > 2 and piece.isupper() and piece.isalpha():
                out.add(piece)
    return out


def surface(m: dict) -> str:
    """The whole billed surface: tool description + every parameter description."""
    return m["description"] + "\n" + "\n".join(m["params"].values())


def head(m: dict) -> str:
    """Everything this bundle puts in a session head: tool surface + awareness.

    Checked as one body because both are loaded together, so a semantic moved
    from the tool description into `context/ios-awareness.md` (or the other
    way) is relocated, not lost.
    """
    return surface(m) + "\n" + m["awareness"]


def _report(name: str, stock_text: str, lean_text: str, lean_head: str) -> int:
    """Report one surface. A token missing HERE but present elsewhere in the
    lean head is RELOCATED, not absent -- named, never silently forgiven.
    Only a token absent from the whole head fails."""
    s_tok, l_tok, h_tok = tokens(stock_text), tokens(lean_text), tokens(lean_head)
    missing = sorted(s_tok - l_tok)
    relocated = [t for t in missing if t in h_tok]
    absent = [t for t in missing if t not in h_tok]
    print(f"[{name}] stock tokens: {len(s_tok)}   lean tokens: {len(l_tok)}")
    if relocated:
        print(f"[{name}] RELOCATED (still in the head, different file): {relocated}")
    print(f"[{name}] ABSENT: {len(absent)}")
    for tok in absent:
        for line in stock_text.splitlines():
            if tok in line:
                print(f"  - {tok!r}\n      stock: {line.strip()[:160]}")
                break
        else:
            print(f"  - {tok!r}")
    return 1 if absent else 0


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__)
        return 2
    stock, lean = measure(argv[1]), measure(argv[2])
    lean_head = head(lean)
    rc = 0
    rc |= _report("tool surface", surface(stock), surface(lean), lean_head)
    rc |= _report("awareness", stock["awareness"], lean["awareness"], lean_head)
    rc |= _report("whole head", head(stock), lean_head, lean_head)
    print("PASS -- nothing absent from the head." if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
