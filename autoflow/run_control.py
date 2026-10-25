"""Validated per-main-graph desktop execution preferences."""
import re

DEFAULTS = dict(overlay=True, pause_key="F8", stop_key="F9", start_delay=3,
                minimize=True, position="top-right", debug_capture_key='F6',
                debug_resume_key='F10', debug_delay_key='Shift+F10')
SHORTCUTS = ('pause_key', 'stop_key', 'debug_capture_key', 'debug_resume_key', 'debug_delay_key')


def settings(project):
    raw = project.get("graphs", {}).get(project.get("main"), {}).get("run_settings", {})
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError("Invalid graph run settings")
    result = DEFAULTS | raw
    for key in ("overlay", "minimize"):
        if type(result[key]) is not bool:
            raise ValueError(f"{key} must be a boolean")
    for key in SHORTCUTS:
        if not isinstance(result[key], str) or not re.fullmatch(r"(?:(?:Control|Alt|Shift)\+)*F(?:[1-9]|1[0-9]|2[0-4])", result[key]):
            raise ValueError("Shortcuts must use F1-F24, optionally prefixed by Control+, Alt+, Shift+")
    if len({frozenset(result[key].split('+')) for key in SHORTCUTS}) != len(SHORTCUTS):
        raise ValueError('Run shortcuts must all be different')
    if type(result["start_delay"]) not in (int, float) or not 0 <= result["start_delay"] <= 60:
        raise ValueError("Start delay must be between 0 and 60 seconds")
    if result["position"] not in ("top-right", "top-left", "bottom-right", "bottom-left"):
        raise ValueError("Invalid overlay position")
    return result
