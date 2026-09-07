"""Ratchet + byte pin for the `ios_inspector` description surface.

Shrinking is always allowed; growing is not, and a semantic can never be
quietly trimmed away. Three distinct guarantees:

1. **Ratchet** -- the tool description, every parameter description, the whole
   serialized wire block and `context/ios-awareness.md` each have a recorded
   ceiling. A new parameter must be given one before it can ship.
2. **Byte pin** -- the 26 parameter descriptions were already trigger-first and
   inside budget, so they were left byte-for-byte untouched. Their sha256s are
   pinned here (recorded at merge-base `a1fe589`): any edit at all, even a
   same-length one, fails.
3. **Fidelity** -- the field names, config keys, operation names and quoted
   contracts that carry behaviour must still appear somewhere in the session
   head (tool description + parameter descriptions + awareness), so a future
   trimming pass cannot drop `tap_point_note` or `screenshot_timeout_s` and
   still go green.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from amplifier_module_tool_ios_inspector import IosInspectorTool

REPO_ROOT = Path(__file__).resolve().parents[3]
AWARENESS_PATH = REPO_ROOT / "context" / "ios-awareness.md"

# --------------------------------------------------------------------------
# Recorded ceilings (lean values). Lower them when you shrink something.
# --------------------------------------------------------------------------

TOOL_DESCRIPTION_CEILING = 5138
WIRE_BLOCK_CEILING = 9245  # json.dumps({name, description, input_schema})
AWARENESS_CEILING = 3367  # characters

#: Per-parameter budget. The ~600-char standard applies to every one of them.
PARAM_BUDGET = 600

#: sha256 of each parameter description as shipped at merge-base `a1fe589`.
#: These were already compliant, so they are preserved byte-for-byte.
PARAM_PINS = {
    "operation": "43b37e55227f1fb3ac29433eea0546479637b3054a88b4bdeea53b4b77eed728",
    "backend": "ad430767b2e54caedeec9806106dbc3639b4e9ec8dd577910780fc8937cc067e",
    "udid": "770645ef34526df98af38635f9c13298e8b634585c487a1972efbf453f00f5e2",
    "name": "6d506258090a7a83d0304e20d36278b2d5b7a6f6384ec64b7472d1a5b239d8b8",
    "device_type": "f42df7f34eac906550aa4f8401e91c45582b224d152630ea8a68841bd3980e32",
    "runtime": "9725a90bf99329f45dcf1ee1ca743e140c716e8e28b55e049c8ae015ef3f9b84",
    "devicetype_id": "b9faeb8eac9f22f331f62aa69854f6c0af893d434b12660bac19e2842e753522",
    "runtime_id": "6cda665173c86c952997b064eb1409887a98bbe715004aa649546530a46a0c48",
    "app_path": "ca60c314b27199b55b96139442fa382c59529b07b3e15f172260cd9a7efe2c96",
    "bundle_id": "61fd61f6540d3f7f27867330e6ca31e19ecf6a6ea479998b10d3ae100135a9a4",
    "selector": "b4881c3c42f79a3889b01114a50610d7aecf7165128cdf739e349272f18540f1",
    "text": "b783b236e89a678f764b1b1b15d95f8dc6b2870dfe5389540f044a543d313106",
    "x": "5de851899bda72dcb78ec04d67fb671fbf7a3b3e1774410653621907f33b0f95",
    "y": "81cebff27f343bef80b2992d94c1e4720296d5695df1af2d6b971e63a35a3d35",
    "x1": "2e11637ac33bd9ea568f9a60e6841d8bae7f2dc8ef5cda0898e1ef78b1bf4b32",
    "y1": "84a3f7dcba4146e8032ed67438dc1114afb6cd62a9f4bcc62c5cffe092cd4938",
    "x2": "69d3ec9d95dd4a06c37e5b01874c9d97fb8717ec05349b765ae8851802bec4a3",
    "y2": "75dc2a5d5f9f55a1fb6f9513c078a5094da195498a97029e593c89907d516807",
    "duration_ms": "ada867316b3728b60536feb4726f656ed1b85d9b3c19d647895dbf96b2efd307",
    "keycode": "3d76ae872ad987cce2b5ef71949fce5799a7bb8f5026d146de7bd16cd9c3dccd",
    "timeout_s": "cadfe77bcaa35e078103d382c94cb9a2d0a5ab4189587f8129da7b89732d42e2",
    "poll_s": "6165faef808b7ee38e6b4f6bc151d980d3c84c742d9de170e0b4b035b2b61035",
    "absent": "e35e903de79f8d3cfda074121792bea8f2b151a5aa7cc703faf4ef61ae477bc5",
    "all_nodes": "a52313c192a183dfe65a41508047cd0088dd4c5c03fae8c46a9e34aef80be132",
    "predicate": "276445ae386f63ffd6ed4c36d9ba4f52ebadf4ea471bff11f0464f38042c9e13",
    "duration_s": "fef3bc43b79591549523b6436508963345926f5956106ee60274e3582b1d98b3",
}

#: The only description allowed over ~600 chars, and the contract that forces
#: it. A new over-budget description fails until it is named here.
OVER_BUDGET = {
    "<tool description>": (
        "the `operation` enum's 24 values -- each carries its own behaviour, "
        "return fields and failure mode (doctor/list_targets; the six lifecycle "
        "ops and their six timeout-budget config keys; screenshot/ui_dump/find/"
        "logs; tap/tap_xy/type_text/key/swipe/wait_for and the VERIFIED-vs-"
        "INFERRED contract; the six device_* ops, the DDI selection rule and the "
        "device-tier tap refusal), plus the selector grammar"
    ),
}

#: Identifier-shaped semantics that must survive anywhere in the session head.
REQUIRED_TOKENS = (
    "ssh_host",
    "frame_points",
    "frame_pixels",
    "center_points",
    "center_pixels",
    "DEVELOPER_DIR",
    "list_targets",
    "create_sim",
    "boot_timeout_s",
    "create_sim_timeout_s",
    "install_timeout_s",
    "launch_timeout_s",
    "ui_dump_timeout_s",
    "screenshot_timeout_s",
    "command_timeout_s",
    "device_type",
    "unique_id",
    "tap_xy",
    "tapped_at_points",
    "tapped_at_pixels",
    "tap_point_note",
    "total_node_count_before",
    "total_node_count_after",
    "total_node_count",
    "node_count",
    "type_text",
    "value_after_note",
    "value_after",
    "wait_for",
    "device_info",
    "device_screenshot",
    "device_apps",
    "device_elements",
    "device_enable_devmode",
    "device_mount_ddi",
    "label_contains",
    "estimated_uid",
    "platform_identifier",
    "spoken_description",
    "ProductVersion",
    "DeveloperModeStatus",
    "CPUArchitecture",
)

#: Contracts that are prose, not identifiers -- the token check cannot see
#: these, so they are pinned literally.
REQUIRED_PHRASES = (
    "never for computing tap coordinates",
    "Never trust a bare coordinate whose unit is ambiguous",
    "always returns both",
    "'scale'",
    "never errors, always returning a report",
    "no explicit 'udid') is an error",
    "'Install Started'",
    "Authorization is required to install the packages.",
    "'warnings'",
    "OPTIONAL",
    "ALWAYS raises a distinct error naming the command",
    "never an empty/absent result",
    "never inline",
    "not raw JSON",
    "always warn",
    "never a bare guess",
    "'before'",
    "WHAT was tapped, not just where",
    "never silent",
    "no 'focused' attribute",
    "never a silent null",
    "no bare sleeps",
    "NO GEOMETRY",
    "temporary-disable-then-restore",
    "never a bare 'turn off your passcode'",
    "nearest DDI at or below the device's iOS version",
    "ALWAYS refuse",
    "Multiple keys AND together",
    "is an error listing candidates",
    "never silently substituted",
    "no sudo",
    "0 codesigning identities over ssh vs 2",
    "does not install Xcode",
)


@pytest.fixture(scope="module")
def tool() -> IosInspectorTool:
    return IosInspectorTool()


@pytest.fixture(scope="module")
def params(tool: IosInspectorTool) -> dict[str, str]:
    props = tool.input_schema["properties"]
    return {k: v["description"] for k, v in props.items() if "description" in v}


@pytest.fixture(scope="module")
def awareness() -> str:
    return AWARENESS_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def head(tool: IosInspectorTool, params: dict[str, str], awareness: str) -> str:
    """Everything this bundle puts in a session head."""
    return "\n".join([tool.description, *params.values(), awareness])


# --------------------------------------------------------------------------
# 1. Ratchet
# --------------------------------------------------------------------------


def test_tool_description_does_not_grow(tool: IosInspectorTool) -> None:
    assert len(tool.description) <= TOOL_DESCRIPTION_CEILING, (
        f"tool description grew to {len(tool.description)} "
        f"(ceiling {TOOL_DESCRIPTION_CEILING}). Shrinking is fine -- lower the "
        "ceiling. Growing needs a reason written down here."
    )


def test_wire_block_does_not_grow(tool: IosInspectorTool) -> None:
    block = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }
    assert len(json.dumps(block)) <= WIRE_BLOCK_CEILING


def test_awareness_does_not_grow(awareness: str) -> None:
    assert len(awareness) <= AWARENESS_CEILING


def test_pins_cover_exactly_the_shipped_parameters(params: dict[str, str]) -> None:
    assert set(params) == set(PARAM_PINS), (
        "A parameter description was added or removed without recording its "
        "pin. Add it to PARAM_PINS (and give it a ceiling) before shipping."
    )


# --------------------------------------------------------------------------
# 2. Byte pin
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(PARAM_PINS))
def test_already_compliant_parameter_descriptions_are_byte_identical(
    params: dict[str, str], key: str
) -> None:
    digest = hashlib.sha256(params[key].encode("utf-8")).hexdigest()
    assert digest == PARAM_PINS[key], (
        f"parameter {key!r} description changed. It was already trigger-first "
        "and inside budget, so it is preserved byte-for-byte; an edit that "
        "exists only to produce a diff is worse than no edit."
    )


def test_no_parameter_description_exceeds_the_budget(params: dict[str, str]) -> None:
    over = {k: len(v) for k, v in params.items() if len(v) > PARAM_BUDGET}
    assert not over, f"parameter descriptions over {PARAM_BUDGET} chars: {over}"


# --------------------------------------------------------------------------
# 3. Standard: trigger-first, no examples, over-budget must be justified
# --------------------------------------------------------------------------


def test_no_example_or_commentary_blocks_in_any_description(head: str) -> None:
    for banned in ("<example>", "</example>", "<commentary>", "</commentary>"):
        assert banned not in head, (
            f"{banned} belongs in an agent description, never in a tool "
            "description, a parameter description or an awareness file."
        )


def test_every_over_budget_description_is_named_with_its_contract(
    tool: IosInspectorTool, params: dict[str, str]
) -> None:
    over = {"<tool description>"} if len(tool.description) > 600 else set()
    over |= {k for k, v in params.items() if len(v) > 600}
    assert over == set(OVER_BUDGET), (
        "Every description over ~600 chars must be named in OVER_BUDGET with "
        f"the parameter contract that forced it. over={sorted(over)} "
        f"named={sorted(OVER_BUDGET)}"
    )


def test_descriptions_lead_with_a_trigger_not_a_preamble(
    tool: IosInspectorTool, params: dict[str, str]
) -> None:
    preambles = ("this tool ", "you can ", "use this ", "the purpose of ")
    for label, text in [("<tool description>", tool.description), *params.items()]:
        opening = text.split(". ")[0].split("\n")[0]
        assert not any(opening.lower().startswith(p) for p in preambles), (
            f"{label} opens with a preamble, not a trigger: {opening[:80]!r}"
        )
        assert len(opening) <= 320, (
            f"{label}'s opening sentence is {len(opening)} chars -- a lead line, "
            "not a paragraph."
        )


# --------------------------------------------------------------------------
# 4. Fidelity
# --------------------------------------------------------------------------


@pytest.mark.parametrize("token", REQUIRED_TOKENS)
def test_required_identifier_semantics_survive_every_future_trim(
    head: str, token: str
) -> None:
    assert token in head, (
        f"{token!r} disappeared from the session head. It names a returned "
        "field, a config key or an operation -- a caller that cannot see it "
        "cannot use it."
    )


@pytest.mark.parametrize("phrase", REQUIRED_PHRASES)
def test_required_prose_contracts_survive_every_future_trim(
    head: str, phrase: str
) -> None:
    assert phrase in head, (
        f"{phrase!r} disappeared from the session head. It is a behaviour, a "
        "guarantee or a failure mode, not decoration."
    )
