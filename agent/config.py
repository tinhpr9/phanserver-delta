import json
import os
import pathlib
import re
from typing import Any, Dict, Optional

DEFAULT_CONFIG_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/agent_config.json")
DEFAULT_DEVICE_ID_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/device_id.txt")
DEFAULT_DEVICE_GROUP_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/device_group.txt")
DEFAULT_STATE_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/aot_group_state.json")
DEFAULT_SERVER_LINKS_PATH = pathlib.Path("/storage/emulated/0/Download/Shouko/server_links.txt")


def normalize_device_id(value: Any) -> Optional[str]:
    raw = str(value or "").strip().lower()
    match = re.fullmatch(r"m([1-9]\d{0,5})", raw)
    if match:
        return f"m{match.group(1)}"
    legacy = re.fullmatch(r"(marmot|nova)-(\d{2})", raw)
    if legacy:
        idx = int(legacy.group(2))
        if 1 <= idx <= 10:
            return f"{legacy.group(1).upper()}-{idx:02d}"
    return None


def normalize_device_group(value: Any) -> Optional[str]:
    raw = str(value or "").strip().upper().replace(" ", "").replace("_", "").replace("-", "")
    if raw in ("1", "NHOM1", "GROUP1", "MARMOT"):
        return "MARMOT"
    if raw in ("2", "NHOM2", "GROUP2", "NOVA"):
        return "NOVA"
    if raw in ("MARMOT", "NOVA"):
        return raw
    return None


def load_device_id(path: pathlib.Path = DEFAULT_DEVICE_ID_PATH) -> Optional[str]:
    try:
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            return normalize_device_id(content)
    except OSError:
        pass
    return None


def load_device_group(path: pathlib.Path = DEFAULT_DEVICE_GROUP_PATH) -> str:
    try:
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            grp = normalize_device_group(content)
            if grp:
                return grp
    except OSError:
        pass
    return "NOVA"


def load_agent_config(path: pathlib.Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    try:
        if path.is_file():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}
