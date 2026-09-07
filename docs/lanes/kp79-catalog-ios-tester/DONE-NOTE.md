# DONE-NOTE — kp79-catalog-ios-tester

**Repo:** `microsoft/amplifier-bundle-ios-tester` · **Branch:** `lane/kp79-catalog-ios-tester`
**Merge-base:** `a1fe589cf66c633a98d34e4f55847bc8949340e6`
**Work item:** `model_performance-sovs` (per-repo child of `model_performance-slee`)
**Date:** 2026-09-07 · **Spend:** **$0.00 of $0.00** — text edits, three `validate-agents` recipe runs, two catalog renders. No API measurement, no DTU, no infrastructure created, nothing to tear down.

---

## OUTCOME: branch A — RESOLVED

Every deliverable is **DONE**. Nothing was recorded NOT-POSSIBLE; the $0 authority funded the whole
job because the job is text edits plus recipe runs, which the goal names as within it. The cap never
bound.

---

## 0. Why this lane claimed a different item id than the goal named

`work_claim(model_performance-kp79)` was **refused**: *"issue already claimed by
agent-spark-1-2776120"*. kp79 is a ~12-repo sweep that was launched into 4+ per-repo lanes started
within one second of each other; only one can hold a single-holder id. By the time this lane read it,
kp79 was **resolved** and its own successor item `model_performance-slee` carried the remaining 8
repos — including this one — and mandated the remedy verbatim:

> *"file ONE CHILD ITEM PER REPO under this item, so each lane claims its own id and can reach its own
> terminal state."*

So this lane filed `model_performance-sovs` (linked `relates-to` slee), claimed it, and resolved it.
That is the goal's Procedure 1 intent — a lane that holds an id and reaches a terminal state — reached
through the structure slee itself specifies. **No BLOCKED.md** was written: the outcome was reachable,
and it was reached.

---

## 1. Deliverable: every description meets the standard

| item | stock chars | lean chars | delta | `<example>` | `<commentary>` |
|---|---:|---:|---:|---:|---:|
| `agents/ios-debugger.md` | 2,515 | **601** | −1,914 (−76.1%) | 3 → **0** | 3 → **0** |
| `agents/ios-operator.md` | 2,507 | **636** | −1,871 (−74.6%) | 3 → **0** | 3 → **0** |
| `agents/ios-visual-tester.md` | 2,524 | **603** | −1,921 (−76.1%) | 3 → **0** | 3 → **0** |
| **agents subtotal** | **7,546** | **1,840** | **−5,706 (−75.6%)** | **9 → 0** | **9 → 0** |
| `skills/ios-headless-build-and-sign/SKILL.md` | 907 | **340** | −567 (−62.5%) | 0 | 0 |
| **repo total** | **8,453** | **2,180** | **−6,273 (−74.2%)** | **9 → 0** | **9 → 0** |

All three agent descriptions are trigger-first (`USE WHEN …`), carry an explicit **DO NOT USE**
naming both sibling agents *and* the platform boundary, and contain zero example/commentary blocks.
The skill description is trigger-first, one paragraph, 340 chars against a ~400 budget.

**Budget honesty:** `ios-operator` lands at **636 chars — ~6% over the "~600" soft budget.** That is
deliberate and it is the fidelity trade, stated rather than hidden: an earlier 600-char draft dropped
*"the Developer Mode security-downgrade round trip"*, and the stock validate-agents run flagged the
class of loss. Restoring it cost +36 bytes. A shorter description that lost a routing fact is not a
win. The other two land at 601 and 603.

**Nothing was edited to produce a diff.** Every one of the four items was genuinely non-compliant:
9 example blocks and 9 commentary tags across the three agents, and a 907-char skill description
whose second half is a table of contents for its own body.

---

## 2. Deliverable: FIDELITY TABLE

Audited fact by fact **including facts that existed only inside `<example>`/`<commentary>` blocks**.

### 2a. Facts found ABSENT in an intermediate lean draft and RESTORED, with byte delta

| agent | fact | where it lived in stock | byte delta |
|---|---|---|---|
| `ios-debugger` | **tool-error vs device-error discrimination** | `**Authoritative on:**` line | 599 → **601** (+2, after compensating trims) |
| `ios-visual-tester` | **device tier can SEE but not TAP**, and its element list has **no geometry** | ONLY inside the third `<commentary>` block | 600 → **603** (+3, after compensating trims) |
| `ios-operator` | **the Developer Mode security-downgrade round trip** | `**Authoritative on:**` line | 600 → **636** (+36) |

The `ios-visual-tester` one is the load-bearing case this gate exists for: it is the single fact in
this repo carried **exclusively** inside a `<commentary>` block. Deleting the examples without
restating it would have silently dropped a real routing constraint. It is now explicit in the lean
text: *"device-tier review (it sees, never taps; no geometry)"*.

### 2b. Facts present in stock and ABSENT in lean — deliberate, each with its reason

None of these is a trigger, a constraint, or a USE WHEN / DO NOT USE WHEN fact. Each is named rather
than hidden, and each has a home the reader already pays for.

| agent | not carried into lean | why not, and where it lives |
|---|---|---|
| `ios-operator` | `DEVELOPER_DIR` / `axe` prerequisites | Setup mechanism, not a routing condition. Body §"Prerequisites Self-Check — REQUIRED", and `context/ios-awareness.md` §Prerequisites, which is **always-on already** — duplicating it into the catalog pays for it twice. |
| `ios-operator` | the *count* "three capability tiers"; survey fields "model", "screenshot" | The constraint the count exists to convey ("the read-only device tier") is kept verbatim. The tier table is in `context/ios-awareness.md`; device screenshots are `ios-visual-tester`'s entry. |
| `ios-debugger` | "lands on the wrong screen"; 'the app "looks fine" but behaves wrong' | Sub-clauses folded into preserved triggers — "navigation silently fails" and the opening "iOS UI behaviour is wrong and why is unknown". |
| `ios-debugger` | re-seat the adapter / check `ioreg` for hubs | A *cause and fix*, not a trigger. The trigger ("a device vanished or never appeared") is preserved; the remedy is body §Phase 8 and §Root Cause Catalogue. |
| `ios-visual-tester` | "after a refactor"; "on a simulator or device"; "defect reports with exact geometry" | Two qualifiers on triggers that are themselves preserved, plus an output-format fact (body §Report Format). |
| `SKILL.md` | the 9-item "Covers …" list | It is a **table of contents for the body**, item-for-item: unsigned simulator leg §1 · Apple-Events GUI bridge §2 · signing-identity resolution §3 · free-tier device build §4 · App-ID-namespace failure §5 · xcodegen regeneration §6 · Info.plist on the BUILT bundle §7 · codesign verification §8 · sim/device Rust-slice split §9. The body is **pay-per-use**; the description is **pay-per-turn**. All **3** of the stock `Use when …` triggers are preserved. |
| all 3 agents | `Use PROACTIVELY` | Replaced by `USE WHEN`, per the standard. Every natural-language trigger phrase it introduced is preserved. |

**Routing facts dropped: 0. Restorations owed: 0.**

### 2c. Net gain — the lean text carries MORE routing information than stock

None of the three stock descriptions said when **not** to use the agent, across three genuinely
adjacent agents whose triggers collide ("confirm a fix landed" → operator *and* visual-tester;
"an interaction that stopped" → debugger *and* operator; screenshot capture → visual-tester *and*
operator). All three now carry an explicit `DO NOT USE` that routes **by name** to both siblings plus
the platform boundary (Android/web/TUI). The stock validate-agents run flagged exactly this collision
as a LOW suggestion; it is now closed.

---

## 3. Deliverable: the catalog rendered BEFORE and AFTER, with the control

The file diff is only the means; the **rendered catalog** is what is paid for on every turn.

Method (`docs/lanes/kp79-catalog-ios-tester/evidence/render-catalog.sh`, reproducible at $0, no LLM
call): a scratch bundle containing only this worktree's `bundle.md` plus `tool-delegate`, dumped via
`amplifier tool info delegate -b kp79-ios-scratch --format json`; the catalog is the
`Available agents:` block of the delegate tool's own description. The skills block is rendered by the
**shipped** `SkillsVisibilityHook._format_skills_list` over this repo's `skills/` dir.

**Both sides captured back-to-back via `git stash push` / render / `git stash pop` / render** — the
discipline slee mandates after the infographic-builder lane folded +49 B of a sibling lane's
concurrent edit into its delta on this same shared host.

| surface | BEFORE | AFTER | delta |
|---|---:|---:|---:|
| `ios-tester` slice of the agent catalog (3 entries) | 7,671 B | **1,935 B** | **−5,736 (−74.8%)** |
| — `ios-tester:ios-debugger` | 2,551 | 631 | −1,920 |
| — `ios-tester:ios-operator` | 2,549 | 666 | −1,883 |
| — `ios-tester:ios-visual-tester` | 2,571 | 638 | −1,933 |
| **CONTROL** — full agent catalog, **90 entries, every bundle** | 79,902 B | 74,166 B | **−5,736** |
| **CONTROL** — the whole `delegate` tool description | 80,860 B | 75,124 B | **−5,736** |
| `hooks-skills-visibility` block (1 skill) | 1,053 B | **488 B** | **−565 (−53.7%)** |
| **combined always-on, per turn** | | | **−6,301 B ≈ −1,373 tokens** |

**The control holds to the byte.** All three catalog deltas are identical (−5,736), and
`diff(before, after)` over the full 90-entry catalog contains **exactly ONE hunk** (`746,893c746,771`)
with **zero** changed entry lines outside `ios-tester:` — every other bundle's rows moved **0 bytes**.
Raw renders and the diff are committed under `evidence/{before,after}/` and `evidence/catalog-diff.txt`.

The BEFORE render reproduces a real session: the installed cache copy
(`~/.amplifier/cache/amplifier-bundle-ios-tester-51d73bc192827e8e/agents/`) was verified
**byte-identical** to merge-base HEAD for all three agents before measuring.

**~1,373 tokens come off the head of EVERY turn of EVERY session that composes this bundle**, whether
or not any iOS agent is ever delegated to.

---

## 4. Deliverable: `validate-agents` on the branch, with the honest transition

Both runs: **v1.7.0**, foundation `@v2.1.2` (`a27d5824517d078097b60d84779dd3eae80202cd`).

| | STOCK (merge-base worktree) | BRANCH |
|---|---|---|
| run id | `run-8cb72a91588c` | `run-09409491f14b` |
| **verdict** | **❌ FAIL** | **⚠️ PASS WITH WARNINGS** |
| agents discovered | 3 across 1 location | 3 across 1 location |
| structural summary | `errors 6, passed 0, warnings 3` | `errors 0, passed 3, warnings 3` |
| quality | 0 good / 0 polish / 0 needs_work / **3 critical** | 0 good / 0 polish / **3 needs_work** / 0 critical |
| `example_count` | 3 / 3 / 3 | **0 / 0 / 0** |
| `commentary_count` | 3 / 3 / 3 | **0 / 0 / 0** |

**The transition is FAIL → PASS WITH WARNINGS — not "PASS held".** Stock carried 3
`EXAMPLE_BLOCK_PRESENT` + 3 `COMMENTARY_TAG_PRESENT` structural **ERRORs**, which made it `critical`.
This is the fourth independent confirmation of the sweep's cross-cutting finding #3: wherever stock
carries examples, a "must stay PASS" gate has a false premise.

**The 3 residual `NO_TOOLS_SECTION` warnings are pre-existing and deliberately untouched.** They are
identical on stock and branch. Evidence for leaving them: the tool *is* explicitly declared, with its
config, at `behaviors/ios-tester.yaml:10` — the same file that includes these three agents; all three
bodies reference `ios_inspector` exclusively (15 / 14 / 18 times) and no other tool; and **0 of 12**
agents across the four tester bundles (android, browser, terminal, ios) declare agent-level `tools:`,
two of which are already merged in this sweep (`863afa1`, `9260481`). Adding a `tools:` block is an
allow-list with runtime consequences, not description hygiene — out of scope for a frontmatter-only
lane, and it would move **0 bytes** of the thing being paid for.

This is a **fifth data point** for the sweep's cross-cutting finding #2 (`validate-agents` measures
presence of the `tools:` key in agent frontmatter only, not validity or location): here it is a
**false negative**, flagging a valid behavior-level declaration as missing — the same polarity
infographic-builder recorded.

---

## 5. Deliverable: bodies byte-identical (frontmatter-only change)

md5 of everything after the closing `---`, verified identical to merge-base:

| file | body md5 | body bytes |
|---|---|---:|
| `agents/ios-debugger.md` | `ad068071ecb1567d74f0d26582b1734e` | 26,479 |
| `agents/ios-operator.md` | `b86a9aebde92853fce7b9ec5926fa71f` | 19,087 |
| `agents/ios-visual-tester.md` | `a7558beb95a8444abf8e45ee74070adf` | 17,485 |
| `skills/ios-headless-build-and-sign/SKILL.md` | `a12b79d52a1de1a0bfd985510dc13b96` | 7,557 |

Within the frontmatter, only the `description` value changed: `meta.name`, `model_role`, the skill's
`name` and `version` are byte-identical.

---

## 6. Deliverable: tests and CI

- **Tests:** `modules/tool-ios-inspector` — **165 passed** on the branch, **165 passed** on a
  merge-base worktree. Identical; the change is test-neutral. No test in this repo references any
  description.
- **CI — corrected, and the correction matters.** An earlier revision of this note said flatly "this
  repo has NONE". That is true of **repo-owned workflows** — `.github/` does not exist, `git ls-files`
  matches 0 paths under `.github/`, and `gh run list` returns no workflow runs — but it was **wrong
  about the PR's checks**. PR #3 carries one **org-level** check, `license/cla`
  (`microsoft-github-policy-service`), and it reports **`conclusion: SUCCESS`, `status: COMPLETED`**
  at 2026-09-07T18:03:57Z, with `mergeable: MERGEABLE`. So the deliverable's condition — *"marked
  ready when its own CI is green"* — **is satisfied**: there is a check, it is green, and nothing is
  pending. The `165 passed` figures above remain local runs, not CI results.
- **Cross-cutting finding #1 ("CHECK THE TESTS FIRST") does NOT hold here.** dot-graph shipped 11
  tests asserting `<example>` blocks must be PRESENT, which is how it drifted. Checked: this repo has
  **zero** such assertions (the only `example` matches in `tests/` are the hostname
  `user@mac.example.com`). No test inversion was needed, and none was invented. The warning is still
  right to generalise — but it must be checked, not assumed.

---

## 7. Scope measured, not assumed

- **3 agents** — the count `validate-agents` itself discovered (`candidates_scanned: 3`,
  `non_agent_count: 0`), not an eyeball count.
- **1 skill** — `find -name SKILL.md` → 1.
- **3 tracked files containing `<example>`** — `git grep -l '<example>' -- ':!docs'`, all three of
  them agents. Matches the goal's pre-launch measurement exactly (3 agents, 1 skill, 3 files).
- `docs/` is excluded from the count throughout: documentation renders into no catalog and costs 0
  bytes/turn.

---

## 8. Decisions recorded (no human was waited on)

1. **Claimed a per-repo child id instead of kp79.** kp79 was already resolved and held; slee mandates
   one child per repo. §0.
2. **`ios-operator` left at 636 chars, ~6% over the soft budget**, to keep the Developer Mode
   security-downgrade round trip. Fidelity beats length; the overage is stated, not hidden. §1.
3. **`NO_TOOLS_SECTION` × 3 accepted, not remediated.** Out of scope, moves 0 catalog bytes, and
   would make this bundle the sole outlier among four sibling tester bundles. §4.
4. **Skill description trimmed rather than left alone.** At 907 chars it was over the ~400 budget and
   its second half duplicated its own body's table of contents. §2b.

## 9. Observations worth their own item (found, not fixed)

1. **`ios-visual-tester` has an undeclared image-consumption dependency.** Its entire method
   reconciles the accessibility dump (points) against the rendered PNG (pixels), but `screenshot`
   returns *a path, never inline bytes*
   (`modules/tool-ios-inspector/amplifier_module_tool_ios_inspector/__init__.py:334`). The file-load
   path is declared nowhere — not in the agent, not in `behaviors/ios-tester.yaml`.
   `model_role: [vision, …]` supplies a capable model, not a way to load the file. **Affects
   `android-tester` identically** (same path-not-inline contract), so it belongs in a cross-bundle
   item, not a single-repo edit.
2. **`validate-agents`' tools check false-negatives on behavior-level declarations** — third instance
   ecosystem-wide, second of this polarity. §4.

---

## 10. Publication

PR #3 was **created as a draft** (`gh pr create --draft`, satisfying branch A and Procedure 4 on
first execution) and then **marked ready for review** once its check was confirmed green — which is
the deliverable's own instruction: *"DRAFT PR, marked ready when its own CI is green. DO NOT MERGE —
the manager merges."*

**Why this reverses an earlier decision in this lane, recorded rather than quietly changed:** the
first pass left the PR draft on the belief that this repo has no CI at all, so the ready-condition's
precondition could never fire. That belief was **wrong** — see §6. `gh pr view --json
statusCheckRollup` shows `license/cla` COMPLETED/SUCCESS on this PR. With a green check in hand the
condition is met, so the PR is marked ready. **It is NOT merged** — the manager merges.

`gh pr ready` changes none of publication/v1's required marker fields (it does not touch
`headRefOid`), so the readback was re-run after the transition and `DONE.json` carries the post-ready
values.

Readback values are in `DONE.json` at the lane root (outside this repo, by instruction), produced by
`publication_readback.sh` reading `git ls-remote` + `gh pr list`.

## 11. Evidence index

```
docs/lanes/kp79-catalog-ios-tester/
├── DONE-NOTE.md                        (this file)
└── evidence/
    ├── render-catalog.sh               reproduce the whole measurement at $0
    ├── before/  after/                 delegate-tool-info.json, delegate-description.txt,
    │                                   agent-catalog-FULL.txt, agent-catalog-ios-tester-slice.txt,
    │                                   skills-visibility.txt
    ├── catalog-diff.txt                the control: ONE hunk, all of it ios-tester
    ├── skills-diff.txt                 the skills-visibility block diff
    ├── validate-agents-STOCK-main.txt  FAIL, 6 errors
    ├── validate-agents-BRANCH.txt      PASS WITH WARNINGS, 0 errors
    └── measurement-summary.json        every number above, machine-readable
```
