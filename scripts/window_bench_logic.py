"""Scenario definitions and response scoring for the interactive window bench."""
from dataclasses import dataclass, field
import json
import re

@dataclass(frozen=True)
class Scenario:
    name: str
    fixture: str
    query: str
    action: str
    target: str
    value: str | None = None
    expected: str = "event"
    manual: bool = False
    tool: str = "screen_element_action"
    tool_args: dict = field(default_factory=dict)
    then: dict = field(default_factory=dict)


SCENARIOS = (
    Scenario("open shadow button", "shadow-open", "Open shadow target", "invoke", "target"),
    Scenario("nested shadow button", "shadow-nested", "Nested shadow target", "invoke", "target"),
    Scenario("slotted shadow button", "shadow-slotted", "Slotted target", "invoke", "slotted-target"),
    Scenario("closed shadow refusal", "shadow-closed", "Closed shadow target", "invoke", "target",
             expected="refused"),
    Scenario("covered button refusal", "overlay", "Covered button", "invoke", "target", expected="refused"),
    Scenario("same-origin iframe", "iframe-same-origin", "Frame target", "invoke", "frame-target"),
    Scenario("cross-origin iframe", "iframe-cross-origin", "Frame target", "invoke", "frame-target"),
    Scenario("native select", "select-native", "Native select", "select", "target", "Beta"),
    Scenario("custom listbox", "listbox-custom", "Custom listbox", "invoke", "listbox"),
    Scenario("filtered combobox", "combobox-filter", "Filter options", "set_value", "combo", "Bet"),
    Scenario("text input", "input-text", "Text input", "set_value", "target", "bench text"),
    Scenario("textarea", "textarea", "Notes", "set_value", "target", "bench notes"),
    Scenario("contenteditable", "contenteditable", "Editable note", "set_value", "target", "bench edit"),
    Scenario("password field", "password", "Password", "set_value", "target", expected="password"),
    Scenario("file input", "file-input", "Choose file", "set_files", "target", manual=True),
    Scenario("user-activation file chooser", "file-chooser", "Open file chooser", "invoke", "chooser",
             manual=True),
    Scenario("off-screen scroll target", "scroll-container", "Off-screen target", "scroll_into_view",
             "scroll-box"),
    Scenario("delayed animated target", "delayed-animated", "Animated target", "invoke", "target",
             expected="settled", then={"query": "Animated target", "control_type": "Button"}),
    Scenario("modal target", "modal", "Modal target", "invoke", "target"),
    Scenario("toast observation", "toast", "Toast notification", "observe", "toast", expected="state"),
    Scenario("navigation click", "navigation", "Navigate on click", "invoke", "target",
             expected="navigation"),
    Scenario("visual canvas target", "canvas", "Canvas target", "point_click", "canvas",
             expected="event", manual=True),
)
IMAGE_TOKEN_ESTIMATES = {"thumb": 85, "slim": 320, "original": 1100}


def estimate_tokens(response_bytes: int, image_tiers: list[str] | None = None) -> int:
    return response_bytes // 4 + sum(IMAGE_TOKEN_ESTIMATES.get(tier, 0) for tier in image_tiers or [])


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * p + 0.5)))
    return round(ordered[index], 3)


def response_cost(response: object, image_tiers: list[str] | None = None) -> dict:
    encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
    text_bytes = len(encoded)
    return {"response_bytes": len(encoded),
            "estimated_tokens": estimate_tokens(text_bytes, image_tiers), "image_tiers": image_tiers or []}


def image_tiers_in(*responses: object) -> list[str]:
    found = set()

    def visit(value: object) -> None:
        if isinstance(value, dict):
            variants = value.get("variants")
            if isinstance(variants, dict):
                found.update(tier for tier in IMAGE_TOKEN_ESTIMATES if tier in variants)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for response in responses:
        visit(response)
    return sorted(found)


def verify_response(response: dict, expected: str, target: str, expected_value: str | None = None) -> dict:
    """Verify only page observations; action response text is deliberately ignored."""
    state = response.get("observation", {})
    events = state.get("events", [])
    matches = [item for item in events if item.get("trusted") is True and item.get("target") == target
               and item.get("type") in ("click", "input", "change", "scroll")]
    if expected == "refused":
        ok = not matches and state.get("covered_or_closed") is True
    elif expected == "navigation":
        ok = state.get("navigation") is True and bool(matches)
    elif expected == "state":
        ok = bool(state.get("visible"))
    elif expected == "settled":
        ok = bool(matches) and state.get("settled") is True
    elif expected == "password":
        ok = bool(matches) and state.get("password_filled") is True
    else:
        ok = bool(matches)
    if expected_value is not None:
        ok = ok and state.get("value") == expected_value
    evidence = {"events": matches, "url": state.get("url"), "value": state.get("value"),
                "covered_or_closed": state.get("covered_or_closed")}
    return {"success": bool(ok), "evidence": evidence}

def ax_observation(answer: object) -> dict:
    """Extract verification evidence from the AX-readable fixture log and state."""
    strings = []

    def collect(value: object) -> None:
        if isinstance(value, str):
            strings.append(value)
        elif isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(answer)
    text = "\n".join(strings)
    events = [{"trusted": trusted == "true", "type": event_type, "target": target}
              for trusted, event_type, target in re.findall(
                  r"isTrusted=(true|false) type=([^\s]+) target=([^\r\n]+)", text)]
    value = re.search(r"state value=([^\r\n]+)", text)
    return {"events": events, "source": answer.get("source") if isinstance(answer, dict) else None,
            "text": text, "value": value.group(1) if value else None,
            "visible": "Toast notification" in text,
            "settled": "state animation=settled" in text,
            "password_filled": "state password=filled" in text,
            "covered_or_closed": "state overlay=true" in text or "state closedRoot=true" in text,
            "navigation": "Navigation complete" in text}


def find_helper_version(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("helper_version", "helperVersion"):
            if isinstance(value.get(key), str):
                return value[key]
        for child in value.values():
            found = find_helper_version(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = find_helper_version(child)
            if found:
                return found
    return None
