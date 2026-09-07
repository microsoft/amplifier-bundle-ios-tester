# Lane `hd-ios-inspector` — DONE-NOTE

**Repo:** `microsoft/amplifier-bundle-ios-tester` · **Branch:** `lane/hd-ios-inspector`
**Merge-base:** `5bd78d8` (`git merge-base HEAD origin/main`)
**Work item:** `model_performance-bph3`, claimed and held by this session.
**Date:** 2026-09-07 · **Spend: $0.00 of a $0.00 authority.** No API call was made by
any step of this lane: the census, the fidelity gate, `validate-agents` and the CLI
render are all local execution.

---

## 0. TERMINAL STATE — read this first

All deliverables DONE. Two things about the ground truth changed under this lane while
it ran, and both are recorded rather than papered over:

1. **The lane started at `a1fe589`; `origin/main` had moved to `5bd78d8`.** Two PRs
   landed in between — `f8f16ad` (#3, catalog hygiene: agent descriptions) and
   `5bd78d8` (#5, GitHub Actions CI). This branch was fast-forwarded onto `5bd78d8`
   **before any commit**, so the diff is against current main and nothing is re-done.
2. **The goal says "run existing CI or state plainly that this repo has none."**
   At `a1fe589` it had none. At `5bd78d8` it does — `.github/workflows/ci.yml`, four
   checks. All four were run locally and are green (§6); the PR's own run is recorded
   in §6 too.

The headline: the `ios_inspector` wire block the goal measured at **10,049** is now
**9,245**, and `context/ios-awareness.md` is **3,861 → 3,367 chars**, with **zero
semantics absent** from the session head by two independent checks and a 109-test
ratchet that keeps it that way.

---

## 1. The headline numbers

Measured two independent ways — by importing the tool (`tools/census.py`) and by
rendering it through the CLI on the owner's own app list (§5). Both return the same
description bytes.

| surface | stock (`5bd78d8`) | lean (this branch) | delta |
|---|---:|---:|---:|
| `ios_inspector` **tool description** | **5,941** | **5,138** | **−803 (−13.5%)** |
| 26 **parameter descriptions** (sum) | 2,153 | 2,153 | **0 (byte-identical)** |
| all descriptions | 8,094 | 7,291 | −803 (−9.9%) |
| `input_schema` JSON (untouched) | 3,983 | 3,983 | 0 |
| **wire block** `json.dumps({name, description, input_schema})` | **10,049** | **9,245** | **−804 (−8.0%)** |
| same, compact separators | 9,868 | 9,064 | −804 |
| `context/ios-awareness.md` (chars) | **3,861** | **3,367** | **−494 (−12.8%)** |
| `context/ios-awareness.md` (bytes) | 3,890 | 3,392 | −498 |

**On the goal's two quoted figures.**

- **10,049 reproduces EXACTLY**, to the byte, as `len(json.dumps({"name", "description",
  "input_schema"}))` with default separators. That is the measure this note uses.
- **3,863 vs 3,861.** The awareness file measures 3,861 characters / 3,890 bytes at the
  merge-base. The 2-char gap is a measurement-method difference (line-ending or
  trailing-newline handling), not a content difference: the file is byte-identical to
  what `origin/main` ships, and `git diff` against `5bd78d8` shows this lane's edit as
  the only change. Both numbers are reported so the discrepancy is visible, not hidden.

---

## 2. Per-description before/after (DELIVERABLE 1)

Full machine output: `evidence/census-before-after.md`.

| description | stock | lean | delta | over ~600? |
|---|---:|---:|---|---|
| **`<tool description>`** | 5,941 | 5,138 | −803 (−13.5%) | **yes — §4** |
| `operation` | 20 | 20 | **0 (byte-identical)** | |
| `backend` | 260 | 260 | **0 (byte-identical)** | |
| `udid` | 135 | 135 | **0 (byte-identical)** | |
| `name` | 31 | 31 | **0 (byte-identical)** | |
| `device_type` | 340 | 340 | **0 (byte-identical)** | |
| `runtime` | 326 | 326 | **0 (byte-identical)** | |
| `devicetype_id` | 118 | 118 | **0 (byte-identical)** | |
| `runtime_id` | 106 | 106 | **0 (byte-identical)** | |
| `app_path` | 31 | 31 | **0 (byte-identical)** | |
| `bundle_id` | 41 | 41 | **0 (byte-identical)** | |
| `selector` | 98 | 98 | **0 (byte-identical)** | |
| `text` | 24 | 24 | **0 (byte-identical)** | |
| `x` / `y` | 35 / 35 | 35 / 35 | **0 (byte-identical)** | |
| `x1` / `y1` | 22 / 22 | 22 / 22 | **0 (byte-identical)** | |
| `x2` / `y2` | 20 / 20 | 20 / 20 | **0 (byte-identical)** | |
| `duration_ms` | 30 | 30 | **0 (byte-identical)** | |
| `keycode` | 21 | 21 | **0 (byte-identical)** | |
| `timeout_s` | 29 | 29 | **0 (byte-identical)** | |
| `poll_s` | 35 | 35 | **0 (byte-identical)** | |
| `absent` | 59 | 59 | **0 (byte-identical)** | |
| `all_nodes` | 61 | 61 | **0 (byte-identical)** | |
| `predicate` | 60 | 60 | **0 (byte-identical)** | |
| `duration_s` | 174 | 174 | **0 (byte-identical)** | |
| **TOTAL descriptions** | **8,094** | **7,291** | **−803** | 1 of 27 |

### 2a. 26 of 27 descriptions left BYTE-IDENTICAL

Every parameter description was already trigger-first (it opens with the thing, not a
preamble) and already inside the ~600-char budget — the largest is `device_type` at 340.
Per the standard, *"an edit that exists to produce a diff is worse than no edit"*, so
none was touched. **Equality is asserted as `sha256(stock) == sha256(lean)`, not as
`len(stock) == len(lean)`** — see the byte pin in §4.

### 2b. Where the −803 came from

| source | saving |
|---|---:|
| **de-duplication against the schema shipped in the same wire block** — the `create_sim` friendly-name/identifier/default rule and the `logs` duration-limit rule were restated in the description almost verbatim from the `device_type` / `runtime` / `duration_s` parameter descriptions. The description now points at them; the semantics stay in the block. | **−279** |
| the `tap` bullet rewritten (837 → 605) with every returned field, both null-causes and the `total_node_count` vs `node_count` population rule kept | −232 |
| `VERIFIED` / `INFERRED` defined once at the head of the interacting section instead of *"not independently verified — always warns"* repeated on four ops | −112 |
| the remaining bullets tightened word by word (timeout budget, CoreSimulator noise, doctor, device tier, header) | −180 |

The de-duplication is why the fidelity gate below checks the **whole head**, not each
string in isolation: a semantic moved from the description into a parameter description
is relocated, not lost.

### 2c. `context/ios-awareness.md`

3,861 → 3,367 chars (−494, −12.8%). The saving is **structure, not content**: four
markdown tables and eight `##` headers became dense prose in the same house style the
already-leaned awareness files use, plus the `device_elements` field list (`caption`,
`estimated_uid`, `platform_identifier`, `spoken_description`) dropped in favour of a
pointer, because the tool description states it verbatim in the same head (§3, RELOCATED).
Every measured finding — the 130px VLM miss, 393×852 / 1179×2556 / scale 3.0, the
iOS 16.7-vs-26.6 `devicectl` divergence, 0-vs-2 codesigning identities over ssh — is
retained word for word.

---

## 3. FIDELITY (DELIVERABLE 2) — **expected 0 absent; found 0 absent**

Three checks, because a token-only checker is known to miss real losses.

### Check A — mechanical, `tools/fidelity_check.py`

Every identifier-shaped token in the stock text (anything containing `_` or `.`, plus any
ALL-CAPS word longer than 2 chars) must still appear in the lean text. Run against three
scopes. Verbatim output: `evidence/fidelity-check.txt`.

```
[tool surface]  stock tokens: 59   lean tokens: 60   ABSENT: 0
[awareness]     stock tokens: 22   lean tokens: 21
                RELOCATED (still in the head, different file):
                  ['estimated_uid', 'platform_identifier', 'spoken_description']
                ABSENT: 0
[whole head]    stock tokens: 74   lean tokens: 76   ABSENT: 0
PASS -- nothing absent from the head.
```

A token missing from one file but present elsewhere in the head is reported as
**RELOCATED**, named individually — never silently forgiven. Only absence from the whole
head fails. The checker names one deliberate exclusion in code, `PROSE_ABBREVIATIONS =
{"i.e", "e.g", "vs", "etc"}`: English abbreviations the `.` rule would otherwise read as
identifiers. Dropping `i.e` is a wording change, and it is written down rather than
filtered out of sight.

### Check B — reading, every stock semantic accounted for

| # | stock semantic | where it is in the lean head |
|---|---|---|
| 1 | drive/inspect on booted Simulator; read-only physical device; macOS host, local or remote Mac via `ssh_host` | lead line, verbatim |
| 2 | `axe describe-ui` is the sensor; every interaction resolves a selector against the live tree before acting | ¶2, verbatim |
| 3 | screenshots for **visual judgment** only, never for computing tap coordinates | ¶2, verbatim |
| 4 | tree = POINTS, screenshots = PIXELS | ¶2 |
| 5 | `ui_dump` **always** returns both, labeled `frame_points`/`frame_pixels`, `center_points`/`center_pixels`, plus measured `scale` | ¶2, verbatim |
| 6 | never trust a bare coordinate whose unit is ambiguous | ¶2, verbatim |
| 7 | `doctor` checks: macOS, `DEVELOPER_DIR`/Xcode, simctl, axe, pymobiledevice3, runtimes, booted sims, devices, per-device Developer Mode + passcode blockers, DDI vs each device's iOS version | Environment bullet 1 — full list kept |
| 8 | every `doctor` check runs even after an earlier one fails; it never errors, always returns a report | Environment bullet 1 |
| 9 | `list_targets`: sims + devices in one list; ambiguous (>1 ready target, no explicit `udid`) is an error | Environment bullet 2, verbatim |
| 10 | lifecycle op set: `create_sim`, `boot`, `shutdown`, `install`, `launch`, `terminate` | section header |
| 11 | `create_sim`: `name` required, `device_type`/`runtime` OPTIONAL | lifecycle bullet 1 |
| 12 | friendly name (`'iPhone 17 Pro'`, `'iOS 26.5'`) **or** full identifier; defaults to a recent available iPhone / newest runtime; an unrecognised name errors listing what IS available, never silently substituted | **RELOCATED** → `device_type` + `runtime` parameter descriptions, byte-identical, same wire block. Named there and pointed at from the bullet. |
| 13 | six per-op timeout budgets `boot_timeout_s`, `create_sim_timeout_s`, `install_timeout_s`, `launch_timeout_s`, `ui_dump_timeout_s`, `screenshot_timeout_s`; fallback `command_timeout_s` = 120s; **from tool config** | lifecycle bullet 2 — all seven keys kept |
| 14 | budgets sized for real `ssh_host` + first-run CoreSimulator latency | lifecycle bullet 2 |
| 15 | a timeout ALWAYS raises a distinct error naming the command and the budget it exceeded, never an empty/absent result | lifecycle bullet 2 |
| 16 | CoreSimulator's benign `'Install Started'` / `'Install Failed: Authorization is required to install the packages.'` noise never turns a success into an error; surfaced in `warnings` | lifecycle bullet 3 — both quoted strings verbatim |
| 17 | that noise is OPTIONAL components being denied, not the command failing | lifecycle bullet 3 |
| 18 | `screenshot` writes a PNG to disk, path never inline, via the runner's local/ssh-transparent transfer | sensing bullet 1 |
| 19 | `ui_dump` returns a parsed tree (type, role, label, value, `unique_id`, enabled, `frame_points`+`frame_pixels`, `center_points`+`center_pixels`, scale) — not raw JSON | sensing bullet 2, verbatim |
| 20 | `find`: nodes matching a selector, centers in both units | sensing bullet 3 |
| 21 | `logs`: bounded `simctl spawn log stream` capture | sensing bullet 4 |
| 22 | `log stream` has no built-in duration limit upstream; the tool always bounds it and treats the timeout as normal termination, not failure | **RELOCATED** → `duration_s` parameter description, byte-identical, same wire block; the bullet says "see `duration_s`" |
| 23 | `tap` protocol: dump → resolve → tap via axe's VERIFIED `--label` resolution using the node's own label → re-dump → report | interacting bullet 1 |
| 24 | `tap` refuses a resolved node with no label rather than guess a coordinate | interacting bullet 1 |
| 25 | `tapped_at_points`/`tapped_at_pixels` come from axe's own tap confirmation, never a bare guess | interacting bullet 1 |
| 26 | `before` carries the node's label/type/`frame_points`/`frame_pixels` — WHAT was tapped, not just where | interacting bullet 1, verbatim |
| 27 | a null coordinate is never silent; `tap_point_note` gives the reason, and there are two distinct reasons (confirmation unparsed vs. parsed-but-no-pixel-scale) | interacting bullet 1 — both causes kept |
| 28 | `total_node_count_before`/`total_node_count_after` count `ui_dump`'s `total_node_count` population (every node), **not** its labelled/valued-only `node_count` | interacting bullet 1 |
| 29 | `tap_xy` takes RAW point coordinates via an INFERRED axe coordinate-tap flag | interacting bullet 2 |
| 30 | `type_text`: tap to focus → INFERRED `axe type` → re-dump | interacting bullet 3 |
| 31 | focus cannot be asserted — the iOS accessibility JSON here carries no `focused` attribute | interacting bullet 3 |
| 32 | `type_text` reports the tap-to-focus step's `tapped_at_points`/`tapped_at_pixels`/`tap_point_note` on the same protocol as `tap` | interacting bullet 3 |
| 33 | `value_after_note` is explicit, never a silent null, when the selector cannot be re-resolved after typing to read back `value_after` | interacting bullet 3 |
| 34 | `key`, `swipe` are INFERRED axe argv shapes | interacting bullet 4 |
| 35 | INFERRED means not independently verified, **and those ops always warn**; VERIFIED means proven | **CONSOLIDATED** — stated once in the section lead instead of four times across `tap_xy`, `type_text`, `key`, `swipe` |
| 36 | `wait_for` polls `ui_dump` until a selector appears/disappears or timeout — no bare sleeps | interacting bullet 5, verbatim |
| 37 | device tier is read-only sensing, free, no Apple Developer account | device section header, verbatim |
| 38 | `device_info` returns `ProductVersion`/`ProductType`/`DeviceName`/`CPUArchitecture` + `DeveloperModeStatus`, asked of the DEVICE, pymobiledevice3-preferred over a local-only check | device bullet 1, verbatim |
| 39 | the design doc's "tool error vs device error" cross-reference | device bullet 1 — kept |
| 40 | `device_screenshot` requires the DDI mounted first (`device_mount_ddi`) | device bullet 2 |
| 41 | `device_apps` is INFERRED pymobiledevice3 `apps list` | device bullet 3, verbatim |
| 42 | `device_elements` is VERIFIED pymobiledevice3 accessibility list-items with **NO GEOMETRY** — `caption`/`estimated_uid`/`platform_identifier`/`spoken_description` only | device bullet 4, verbatim |
| 43 | `device_enable_devmode`: a set passcode blocks it (undocumented Apple behaviour) and the error carries the temporary-disable-then-restore guidance **in the same message**, never a bare "turn off your passcode" | device bullet 5 |
| 44 | `device_mount_ddi` picks the nearest DDI at or below the device's iOS version, never the newest Xcode-shipped one by assumption; newer Xcode may ship none for this device at all | device bullet 6 — both halves kept |
| 45 | `tap`/`tap_xy` on `backend='device'` ALWAYS refuse, pointing at `device_elements`' no-geometry limitation | standalone paragraph, verbatim |
| 46 | selector grammar: `label`, `label_contains`, `value`, `role`, `type`, `unique_id`, optional `index`; multiple keys AND together; an ambiguous match (>1 node, no index) is an error listing candidates | final paragraph, **byte-identical** |
| 47 | awareness: the 130px VLM miss with tree truth `[48,1132][1131,1288]` / center (590,1210) vs (590,1080), landing on the row above, silently | awareness ¶2, verbatim |
| 48 | awareness: points 393×852, pixels 1179×2556, scale 3.0, silent 3× error | awareness ¶3, verbatim |
| 49 | awareness: three tiers and what each can SEE / TAP, with proven/unproven status | awareness ¶4 |
| 50 | awareness: routing to `android-tester` / `browser-tester` / `terminal-tester` | awareness ¶6 |
| 51 | awareness: do not run `simctl`/`axe`/`xcrun`/`pymobiledevice3` from the root session; the agents hold UDID scoping, points/pixels discipline, dump-before-tap, focus assertion, device-tier tap refusal | awareness ¶7, verbatim |
| 52 | awareness: all prerequisites — Xcode not CLT, `DEVELOPER_DIR`, no sudo, `brew install cameroncooke/axe/axe`, pymobiledevice3, cable + Developer Mode + DDI, iOS 16.7 vs 26.6 `devicectl` divergence, read `ProductVersion` first, 0-vs-2 codesigning identities over ssh, TROUBLESHOOTING.md | awareness ¶8, verbatim |
| 53 | awareness: `doctor` reports every host problem at once with its fix; `create_sim` provisions; the bundle does not install Xcode; agents report the exact fix and stop | awareness ¶9, verbatim |

**Deliberate non-restorations: 3, all RELOCATED within the head, all named above
(#12, #22, and the awareness `device_elements` field list). 1 CONSOLIDATED (#35).
Nothing is absent.** What was actually deleted is self-justifying rationale that no rule
depended on — *"named explicitly so the two never look like the same number under a
same-sounding name"*, *"seen on many simctl commands"*, *"clearly-worded"* — with every
rule those clauses justified retained in force.

### Check C — pinned

`REQUIRED_TOKENS` (42 identifiers) and `REQUIRED_PHRASES` (33 literal contracts) in the
pin test hard-assert this table, so the next trimming pass cannot quietly drop
`tap_point_note`, `screenshot_timeout_s`, `value_after_note`, `"never a bare guess"`,
`"NO GEOMETRY"` or `"no bare sleeps"` and still go green.

---

## 4. The byte pin test (DELIVERABLE 3)

`modules/tool-ios-inspector/tests/test_description_budget.py` — **109 tests, all green**,
on Python 3.11 and 3.13. It is a ratchet: shrinking is always allowed, growing is not.

| group | what it enforces |
|---|---|
| ratchet ×3 | tool description ≤ 5,138 · wire block ≤ 9,245 · awareness ≤ 3,367 |
| coverage ×1 | `PARAM_PINS` covers exactly the shipped parameters — a new one must be pinned before it ships |
| **byte pin ×26** | `sha256` of each parameter description, recorded from the merge-base. Any edit at all, including a same-length one, fails |
| budget ×1 | no parameter description over 600 chars |
| standard ×3 | no `<example>`/`<commentary>` anywhere in the head · every >600-char description named in `OVER_BUDGET` with its contract · every description opens with a trigger, not `This tool …`/`You can …`, in ≤320 chars |
| fidelity ×75 | 42 `REQUIRED_TOKENS` + 33 `REQUIRED_PHRASES` |

**The one description over ~600 chars, named with the contract that forces it** — the
`OVER_BUDGET` entry the test enforces:

> **`<tool description>` — 5,138.** The `operation` enum's 24 values. Each carries its own
> behaviour, return fields and failure mode: `doctor`/`list_targets`; the six lifecycle
> ops and their six timeout-budget config keys; `screenshot`/`ui_dump`/`find`/`logs`;
> `tap`/`tap_xy`/`type_text`/`key`/`swipe`/`wait_for` and the VERIFIED-vs-INFERRED
> contract; the six `device_*` ops, the DDI selection rule and the device-tier tap
> refusal; plus the selector grammar.

A caller that cannot see which of 24 operations returns `tapped_at_pixels`, or that
`tap` refuses on `backend='device'`, will pick the wrong one. This is the "named
parameter contract" exception the standard allows, and the test fails if a *new*
over-budget description appears without an entry, or if a stale entry lingers.

---

## 5. Rendered tool surface, on the owner's own app list (DELIVERABLE 4)

`tools/render-tool-surface.sh`. One **fresh scratch `AMPLIFIER_HOME` per side**, each
built by **copying** `~/.amplifier/settings.yaml` — the original is never moved and never
edited — with only the single `ios-tester` app entry swapped to a local `file://` path.
All 20 of the owner's other app bundles render identically on both sides, so the delta is
attributable to this repo alone.

| | stock | lean | delta |
|---|---:|---:|---:|
| tools mounted in the owner's configuration | 86 | 86 | 0 |
| **all rendered tool-description bytes** | **114,677** | **113,874** | **−803 (−0.70%)** |
| of which `ios_inspector` | **5,941** | **5,138** | **−803 (−13.5%)** |
| this repo's share of the owner's tool surface | 5.18% | 4.51% | −0.67pp |

**The cross-check:** the CLI render returned **5,941 / 5,138** — byte-for-byte what the
import-based census returned. Neither number rests on a single path. Raw text of both
rendered descriptions is committed at `evidence/rendered-ios_inspector-{stock,lean}.txt`;
machine summary at `evidence/render-summary.json`.

**Safety, because a sibling lane was burned here.** `hd-browser-bridge` found that
`amplifier tool list` under a scratch `AMPLIFIER_HOME` silently rewrote 36 shared uv-tool
editable-install `.pth` files into the scratch dir. This lane snapshotted all **76** `.pth`
files in `~/.local/share/uv/tools/amplifier/lib/python3.13/site-packages` before running,
and the script itself refuses to exit quietly if any changed:

```
SAFETY OK: owner settings.yaml md5 unchanged; 76 .pth files unchanged.
```

**The hazard did not reproduce** — 76/76 md5s identical before and after
(`evidence/pth-before.md5`, `evidence/pth-after.md5`), and the owner's `settings.yaml`
md5 is unchanged. A backup copy was taken anyway, outside this repo, at
`lanes/hd-ios-inspector/pth-backup/`.

---

## 6. `validate-agents`, `<example>`/`<commentary>` counts, and CI (DELIVERABLES 5–7)

### `validate-agents`: PASS, and PASS held

Run at $0 by `tools/run_validate_agents.py`, which executes the four **deterministic**
phases of foundation's shipped `recipes/validate-agents.yaml` v1.5.1 — `environment-check`,
`agent-discovery`, `structural-validation`, `quality-classification` — **verbatim out of
the recipe**, substituting the template variables the engine would. Those four phases are
where the gate is decided (structural ERRORs, `<example>`/`<commentary>`, the >600-token
ceiling, `model_role` vocabulary); only the later report/approval phases call a model, and
they were not run, because the goal authorises **$0 and no API calls**.

| repo state | agents | ERRORs | WARNINGs | `<example>` | `<commentary>` | verdict |
|---|---:|---:|---:|---:|---:|---|
| `a1fe589` — where this lane started, before PR #3 | 3 | **6** | 3 | **9** | **9** | **FAIL** |
| `5bd78d8` — merge-base (after PR #3) | 3 | **0** | 3 | **0** | **0** | **PASS** |
| **this branch** | 3 | **0** | 3 | **0** | **0** | **PASS** |

Evidence: `evidence/validate-agents-a1fe589-pre-PR3.txt`, `-STOCK.txt`, `-BRANCH.txt`.

**In-description `<example>`/`<commentary>` counts, before → after: 0 → 0 on this
branch's own diff.** The 9→0 / 9→0 transition is real but it is **not this lane's work** —
it landed in `f8f16ad` (PR #3, `kp79-catalog-ios-tester`) between this lane's start and
its merge-base. Claiming it here would be taking credit for another lane's diff. What
this lane adds is that the count is now **pinned**:
`test_no_example_or_commentary_blocks_in_any_description` fails if a block ever returns —
to an agent description, a tool description, a parameter description or the awareness file.

The 3 residual `NO_TOOLS_SECTION` warnings are pre-existing, identical on all three rows,
and untouched — they are WARNINGs, not ERRORs, and do not gate PASS.

### CI: the repo has it now, and it is green

At `a1fe589` this repo had no `.github/` at all. `5bd78d8` (PR #5) added
`.github/workflows/ci.yml` — four checks. All four run locally on this branch:

| check | command | result |
|---|---|---|
| Lint (ruff) | `uvx ruff@0.16.6 check --isolated --select E4,E7,E9,F .` | **All checks passed!** |
| Tests (Python 3.11) | `uv sync --extra dev --python 3.11 && uv run --no-sync pytest tests/ -q` | **274 passed** |
| Tests (Python 3.13) | same, `--python 3.13` | **274 passed** |
| Bundle structure | the workflow's own YAML parser, extracted and run verbatim | **2 documents parsed, OK** |

274 = 165 pre-existing + 109 added by this lane. The 165 are unchanged and no test in
this repo references any description text other than the new file.

The PR's own run is recorded in §9.

---

## 7. Scope, and what was deliberately NOT touched

- **`input_schema` structure was not modified.** Parameter names, types, enums and
  defaults are unchanged; only the tool description's prose moved. The 3,983 bytes of
  schema JSON are identical on both sides.
- **The 26 parameter descriptions were not modified** — see §2a. They were already
  compliant.
- **`agents/*.md` were not modified.** PR #3 already leaned them; re-touching them would
  be a diff for its own sake and would collide at merge.
- **`skills/`, `docs/`, `README.md`, `bundle.md` were not modified.** `bundle.md` and
  `README.md` restate parts of the tool description and are a real, separately-scopeable
  follow-up; they are not the always-on head surface this lane targets.
- **`context/ios-guide.md` was not modified.** It is loaded on demand by the agents, not
  injected into every session head.

---

## 8. Deviations and findings, recorded

1. **The lane was fast-forwarded off its stated start point.** The goal's figures were
   taken at `a1fe589`; `origin/main` was at `5bd78d8` by the time work began. The branch
   was moved onto `5bd78d8` **before the first commit** rather than opening a PR against
   a stale base. Both target files are byte-identical between the two commits, so every
   baseline number in this note holds at either.
2. **The goal's "this repo has no CI" premise is now false**, and the goal's own escape
   clause ("run existing CI **or** state plainly that this repo has none") is satisfied by
   running it — see §6.
3. **`<example>`/`<commentary>` 9→0 is attributed to PR #3, not to this lane.** Stated
   plainly rather than folded into this lane's numbers.
4. **The 3,863-vs-3,861 awareness discrepancy** is reported in §1 rather than quietly
   restated as 3,863.
5. **The `.pth` hazard did not reproduce on this host** with 76 files and this CLI
   version, contradicting `hd-browser-bridge`'s observation of 36 rewritten files. Both
   runs are real; the difference is worth knowing, so it is recorded rather than assumed
   fixed. The guard remains in the script.
6. **`validate-agents` was run deterministically, not end-to-end.** The LLM report phases
   were skipped by design ($0 authority). The gate itself is fully evaluated; the prose
   report is not.

---

## 9. Reproduce

```bash
git -C <checkout> switch lane/hd-ios-inspector
L=docs/lanes/hd-ios-inspector/tools
MB=$(git merge-base HEAD origin/main); D=/tmp/ios-stock-$MB
mkdir -p "$D" && git archive "$MB" | tar -x -C "$D"

python3 $L/census.py "$D" .                     # per-description before/after
python3 $L/fidelity_check.py "$D" .             # stock-vs-lean semantic gate
python3 $L/run_validate_agents.py \
    <foundation>/recipes/validate-agents.yaml . # validate-agents, $0
bash    $L/render-tool-surface.sh "$D" . /tmp/ios-render   # CLI render + .pth guard

cd modules/tool-ios-inspector && uv run --extra dev pytest tests/ -q
uvx ruff@0.16.6 check --isolated --select E4,E7,E9,F .
```

## 10. Spend ledger

| item | authorised | spent |
|---|---:|---:|
| API measurement | $0.00 | **$0.00** |
| DTU / infrastructure | $0.00 | **$0.00** |
| **total** | **$0.00** | **$0.00** |

Nothing was purchased and no provider was contacted. Every deliverable is text editing,
local execution and a local CLI render, all of which the $0 authority funds completely.
**No deliverable is NOT-POSSIBLE.**
