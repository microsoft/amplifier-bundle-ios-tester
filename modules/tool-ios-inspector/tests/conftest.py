"""Shared test fixtures -- pure unit tests, no Mac/simulator/device required.

Everything below fakes `CommandRunner`'s injected `_runner` callable
(`(argv, timeout, env) -> CommandResult`), so every test exercises real
argv-construction and output-parsing logic without ever touching a real
`subprocess`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from amplifier_module_tool_ios_inspector.runner import CommandResult

SAMPLE_DESCRIBE_UI_JSON = {
    "type": "Application",
    "role": "application",
    "AXLabel": "MyApp",
    "AXValue": "",
    "AXUniqueId": "",
    "enabled": True,
    "AXFrame": "{{0, 0}, {393, 852}}",
    "children": [
        {
            "type": "StaticText",
            "role": "text",
            "AXLabel": "General",
            "AXValue": "",
            "AXUniqueId": "general-row",
            "enabled": True,
            "AXFrame": "{{16, 377.33}, {361, 52}}",
            "children": [],
        },
        {
            "type": "StaticText",
            "role": "text",
            "AXLabel": "Wi-Fi",
            "AXValue": "On",
            "AXUniqueId": "wifi-row",
            "enabled": True,
            "AXFrame": "{{16, 100}, {361, 52}}",
            "children": [],
        },
        {
            "type": "Button",
            "role": "button",
            "AXLabel": "",
            "AXValue": "",
            "AXUniqueId": "unlabeled-button",
            "enabled": True,
            "AXFrame": "{{16, 500}, {100, 40}}",
            "children": [],
        },
    ],
}

AMBIGUOUS_DESCRIBE_UI_JSON = {
    "type": "Application",
    "role": "application",
    "AXLabel": "MyApp",
    "AXValue": "",
    "AXUniqueId": "",
    "enabled": True,
    "AXFrame": "{{0, 0}, {393, 852}}",
    "children": [
        {
            "type": "Button",
            "role": "button",
            "AXLabel": "Row",
            "AXValue": "",
            "AXUniqueId": "row-1",
            "enabled": True,
            "AXFrame": "{{16, 100}, {361, 52}}",
            "children": [],
        },
        {
            "type": "Button",
            "role": "button",
            "AXLabel": "Row",
            "AXValue": "",
            "AXUniqueId": "row-2",
            "enabled": True,
            "AXFrame": "{{16, 200}, {361, 52}}",
            "children": [],
        },
    ],
}


def fake_png_bytes(width: int, height: int) -> bytes:
    """Minimal bytes that satisfy `png_dimensions`'s liveness check and
    report the given `width`/`height` -- an 8-byte signature, an 8-byte
    (unused) chunk-length+type placeholder, then the width/height as
    big-endian uint32s at the exact offsets `png_dimensions` reads
    (bytes 16:20 / 20:24). Not a real, renderable PNG -- just real enough
    for the dimension-sniffing this tool does."""
    sig = b"\x89PNG\r\n\x1a\n"
    placeholder = b"\x00" * 8
    return sig + placeholder + width.to_bytes(4, "big") + height.to_bytes(4, "big")


@dataclass
class FakeRunner:
    """Records every argv it was called with and returns queued/keyed canned
    results -- the injectable `_runner` for `CommandRunner`."""

    responses: dict[tuple[str, ...], CommandResult] = field(default_factory=dict)
    default: CommandResult | None = None
    queue: list[CommandResult] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)
    envs: list[dict[str, str] | None] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)

    def __call__(self, argv, timeout, env):
        self.calls.append(list(argv))
        self.envs.append(env)
        self.timeouts.append(timeout)
        if self.queue:
            return self.queue.pop(0)
        key = tuple(argv)
        if key in self.responses:
            return self.responses[key]
        if self.default is not None:
            return self.default
        return CommandResult(args=list(argv), returncode=0, stdout="", stderr="")
