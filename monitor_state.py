"""
monitor_state.py — shared SILVERMIC alert dedup state (GitHub Gist backed).

Used by BOTH the Streamlit app and the GitHub Actions cron so a "perfect entry"
alert is sent only once per setup, no matter which path detects it first.

Credentials are read from Streamlit secrets OR environment variables, under either
naming convention, so the same gist is used in both contexts:
    token : GIST_TOKEN  or  GITHUB_TOKEN
    gist  : MONITOR_STATE_GIST  or  GIST_HISTORY_ID

If neither is configured, load() returns {} and save() is a no-op (the caller then
falls back to its own per-session dedup).
"""
from __future__ import annotations

import os
import json
import logging

import requests

logger = logging.getLogger(__name__)

_STATE_FILE = "silvermic_monitor_state.json"


def _val(name: str) -> str:
    """Streamlit secret first, then environment."""
    try:
        import streamlit as st
        v = st.secrets.get(name, "")
        if v:
            return str(v)
    except Exception:
        pass
    return os.environ.get(name, "")


def _creds() -> tuple[str, str]:
    token = _val("GIST_TOKEN") or _val("GITHUB_TOKEN")
    gist  = _val("MONITOR_STATE_GIST") or _val("GIST_HISTORY_ID")
    return token, gist


def load() -> dict:
    token, gist = _creds()
    if not (token and gist):
        return {}
    try:
        r = requests.get(f"https://api.github.com/gists/{gist}",
                         headers={"Authorization": f"token {token}"}, timeout=10)
        if r.status_code != 200:
            return {}
        files = r.json().get("files", {})
        if _STATE_FILE in files:
            return json.loads(files[_STATE_FILE].get("content") or "{}")
    except Exception as exc:
        logger.warning("monitor_state load failed: %s", exc)
    return {}


def save(state: dict) -> bool:
    token, gist = _creds()
    if not (token and gist):
        return False
    try:
        r = requests.patch(f"https://api.github.com/gists/{gist}",
                           headers={"Authorization": f"token {token}"},
                           json={"files": {_STATE_FILE: {"content": json.dumps(state)}}},
                           timeout=10)
        return r.status_code == 200
    except Exception as exc:
        logger.warning("monitor_state save failed: %s", exc)
        return False


def already_alerted(today: str, marker: str = "PERFECT") -> bool:
    """True if a `marker` alert was already sent today (per shared state)."""
    st = load()
    return st.get("date") == today and st.get("last_alerted") == marker


def mark_alerted(today: str, marker: str = "PERFECT") -> None:
    save({"last_alerted": marker, "date": today})


def reset(today: str) -> None:
    """Clear today's alert marker (call when the setup is no longer valid)."""
    save({"last_alerted": "WAIT", "date": today})
