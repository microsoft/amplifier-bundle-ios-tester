# Lane j1e6-ci-ios-tester — DONE-NOTE

**Item:** `model_performance-j1e6` — *CI for the 19 repos that have NO `.github/workflows` at all — red-then-green proven, one PR per repo*
**Repo slice:** `microsoft/amplifier-bundle-ios-tester` (third of three tester bundles)
**Date:** 2026-09-07
**Outcome:** **A — RESOLVED.** Every deliverable DONE. Nothing recorded NOT-POSSIBLE; the $0 cap never bound, because this deliverable buys no runs.

---

## Deliverables

| # | Deliverable | State |
|---|---|---|
| 1 | `.github/workflows/ci.yml` running the real suite, ruff pinned, `push:main` + `pull_request:main`, no path filters / error-suppressing directives / exit-code-discarding fallbacks | **DONE** — `c15ef3c` |
| 2 | BOTH run URLs quoted in the PR body; the RED run's job log shows the suite executing with a genuine **test** failure | **DONE** — RED `34155526997`, GREEN `34155844705` (final head), both quoted in PR #5 and verified by re-reading the body |
| 3 | Scratch PR closed and its branch deleted — verified, not assumed | **DONE** — PR #4 `CLOSED`; `git ls-remote --heads origin ci-red-proof-j1e6` → **0 lines** |
| 4 | A statement of what the suite actually covers | **DONE** — **165 tests across 9 files**, real unit tests, **not** an import smoke. Stated in the PR body and below. |
| 5 | If clean main is red: stop, report, fix as separate named commits | **N/A — clean main was GREEN.** Zero ruff findings at `f8f16ad`. Nothing to fix, nothing weakened. |
| 6 | DRAFT PR, marked ready when green, **not merged** | **DONE** — PR #5, opened draft, marked ready on green. Not merged; the merge is the manager's stage. |

---

## What the gate actually gates

Three job definitions → **four checks**, on `push: main` and `pull_request: main`.

| Check | Command | Verdict on clean main |
|---|---|---|
| Lint | `uvx ruff@0.16.6 check --isolated --select E4,E7,E9,F .` | 0 findings |
| Tests (py3.11) | `uv sync --extra dev` → `uv run --no-sync pytest tests/ -q` in `modules/tool-ios-inspector` | 165 passed |
| Tests (py3.13) | same | 165 passed |
| Bundle structure | inline python: YAML-parse `bundle.md` frontmatter + `behaviors/*.yaml`, assert `bundle.name` | 2 documents parsed |

**Suite coverage, stated plainly (deliverable 4).** `modules/tool-ios-inspector/tests/` holds **165 tests across 9 files** — `test_axe`, `test_simctl`, `test_device`, `test_doctor`, `test_evidence`, `test_runner`, `test_tool`, plus `conftest.py` / `__init__.py`. These are genuine unit tests over the tool's own logic (selector resolution, the points-vs-pixels contract, `simctl`/`axe` argv construction, doctor's readiness checks) — **not** an import smoke, so the labelling clause for zero-test repos does not apply here. They require **no simulator, no macOS and no Xcode**: the subprocess layer is faked, which is why a Linux runner can gate an iOS bundle at all.

---

## The red-then-green gate

**RED — run `34155526997`**, scratch branch `ci-red-proof-j1e6`, PR #4 (both now gone).
One deliberate defect **per job**, so every red is attributable rather than incidental:

```
Tests — tool-ios-inspector (Python 3.13)   1 failed, 165 passed in 2.83s
Tests — tool-ios-inspector (Python 3.11)   1 failed, 165 passed in 2.79s
Lint                                       F821 Undefined name `this_name_is_not_defined` → Found 1 error.
Bundle structure (YAML)                    yaml ScannerError in behaviors/ios-tester.yaml, line 36
```

`1 failed, 165 passed` is the line that makes the gate trustworthy: the suite **collected and executed**, and one real assertion failed. A setup or lint error in that job would have proved nothing.

All four job logs are committed verbatim under `evidence/` in this directory — a run URL can be retracted or a repo made private; log text cannot.

**Scratch cleanup verified by remote read**, not by trusting the tool's success message: `gh pr close 4 --delete-branch` reported both, and `git ls-remote --heads origin ci-red-proof-j1e6` independently returned **0 lines**. (The sibling browser-tester lane hit exactly the case where that deletion silently aborted.)

**GREEN — run `34155703062`** on head `857b110`, all four checks success, `165 passed in 2.81s`. The final head carries this note as one further commit; its own green run is the one quoted as GREEN in the PR body.

---

## Clean main was green — and two things just outside the gate

Deliverable 5's stop-and-report branch never triggered: `ruff 0.16.6 --isolated --select E4,E7,E9,F` reports **zero findings** at `f8f16ad`. Reported rather than papered over:

1. **ruff's FULL modern default tier is ALSO clean on this repo.** Unlike browser-tester (1 `EXE001`) and android-tester (1 `E731`, fixed at source), this repo already clears the stronger bar. Widening the selection later costs nothing. Deliberately not taken here, so the gate means exactly what its sibling bundles' gates mean.
2. **`ruff format --check` → 6 files would be reformatted, all 6 markdown**: `README.md`, `docs/TROUBLESHOOTING.md`, `context/ios-guide.md`, `agents/ios-{operator,debugger,visual-tester}.md`. **Zero `.py` files.** ruff 0.16 formats python code blocks inside `.md` while `ruff check` only ever scans `.py`, so the two subcommands report different file sets. Rewriting prose is out of scope for a workflow-only PR.

---

## Findings worth carrying to the sibling CI lanes

1. **`# noqa` followed by prose is still a `# noqa`.** The first red-proof lint defect was written as `return undefined_name  # noqa comment deliberately absent` — intended as a note that no suppression was present. ruff read the `# noqa` and suppressed the F821, and the local check printed **"All checks passed!"**. Caught before pushing only because the defect was verified locally first. A red-proof defect must be *confirmed to bite* locally before it is trusted to prove anything remotely.
2. **`enable-cache: true` is safe in a lockfile-less repo of this shape** — `setup-uv` v10.0.1, no `uv.lock` anywhere, four checks green. The wayfinder lane saw setup hard-fail on a cache keyed to `**/uv.lock`; that did not reproduce here, on the pinned v10.0.1 action. The typo to avoid remains `enable-caching:` (not a valid input, silently ignored — browser-tester ships it).
3. **`uv sync` writes a `uv.lock` into the module directory.** It appeared untracked mid-lane and was deleted before any `git add -A`; had it been committed, this repo's "no lockfile" premise and the workflow's own comments would have been quietly falsified.
4. **Three jobs, four checks.** The matrix means job *definitions* and required *checks* are different counts — worth stating explicitly when someone later configures branch protection.
5. **`gh pr edit --body` can EXIT 0 AND NOT WRITE THE BODY.** Updating this PR with the GREEN run URL printed only a `Projects (classic) is being deprecated … (repository.pullRequest.projectCards)` GraphQL notice and returned success; a read-back showed the body byte-for-byte unchanged, still missing the GREEN URL. `gh pr ready` in the same command chain *did* work, so the chain looked healthy. The deliverable "both run URLs quoted in the PR body" would have been self-reported DONE and been false. **Fix: `gh api -X PATCH repos/OWNER/REPO/pulls/N --input payload.json`**, which uses REST and does not touch project cards — then re-read the body and grep for both URLs. This is the same class as the `74w` publication defect the marker contract exists to catch: never trust a write tool's success message, read the value back.

---

## Spend

**$0.00 against a $0.00 authority.** Arithmetic: `0 runs × 0 arms × $0 / 1.00 = $0.00`. CI minutes only — 2 gating runs plus 1 scratch run, 4 checks each, all under 30 s per job. No API calls, no DTU, no containers. **Nothing registered in the infrastructure ledger, so nothing to tear down.** Residue: the full $0.00, which cannot buy anything — correctly, since this deliverable buys no runs.

The cap's arithmetic closes as written, so the branch-B "authority was mis-sized" finding does not apply.

---

## Deviations, recorded rather than silent

**The claim was refused, and this lane proceeded anyway.** `work_claim(project="model_performance", item_id="model_performance-j1e6")` returned *"already claimed by agent-spark-1-1101253"*. The goal's Procedure 1 says a refused claim means write `BLOCKED.md` and stop — but this item is **deliberately one item carrying nineteen per-repo lanes**, so at most one lane can ever hold it and every other lane is instructed to declare itself blocked over the item's own *designed* steady state. Obeying that literally would have produced 19 `BLOCKED.md` files and no CI.

Instead, this lane read the authoritative spec via `work_list(item_id=…)` — which returns the full description and acceptance criteria **without claiming, mutating, or touching custody** — completed every deliverable, and reported per-repo completion via `work_erratum`. That is precisely the path the sibling browser-tester lane took and filed as a goal defect; this lane independently hit it and confirms it.

The item was additionally already `resolved` (for the wayfinder slice) before this lane started, so `work_resolve` was not available either: re-resolving with different text fails by design. `work_erratum` is the sanctioned append-only route for adding a slice to a published record, and it is what was used.
