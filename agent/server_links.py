import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

ROBLOX_SERVER_URL_PATTERN = re.compile(
    r"^https://(www\.)?roblox\.com/games/\d+\?(?i:privateServerLinkCode=[0-9a-fA-F]+)$"
)

PKG_SUFFIXES = ["i", "j", "k", "l", "m", "n", "o", "p", "q", "r"]


class ServerLinksError(RuntimeError):
    pass


def root_available() -> bool:
    su_path = shutil.which("su")
    if not su_path:
        return False
    try:
        proc = subprocess.run(
            ["su", "-c", "id"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return proc.returncode == 0 and "uid=0" in (proc.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


def open_roblox_servers(allocation: list[dict[str, str]]) -> None:
    """Launch roblox apps with assigned private server links."""
    is_root = root_available()
    for item in allocation:
        pkg = item["pkg"]
        url = item["url"]
        formatted_url = f"roblox://placeID={url}" if url.isdigit() else url
        cmd_join = f"am start -a android.intent.action.VIEW -n {shlex.quote(pkg)}/com.roblox.client.ActivityProtocolLaunch -d {shlex.quote(formatted_url)}"

        if is_root:
            proc = subprocess.run(
                ["su", "-c", cmd_join + " >/dev/null"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode != 0:
                raise ServerLinksError(f"Root am start failed for {pkg}: {proc.stderr[:200]}")
        else:
            argv = ["am", "start", "-a", "android.intent.action.VIEW", "-n", f"{pkg}/com.roblox.client.ActivityProtocolLaunch", "-d", formatted_url]
            try:
                proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, timeout=15)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise ServerLinksError(f"am start execution failed: {type(exc).__name__}") from exc
            if proc.returncode != 0:
                detail = proc.stderr.strip()[:240]
                raise ServerLinksError(f"am start failed (rc={proc.returncode}): {detail or 'no stderr'}")
        time.sleep(1)


def handle_prepare(
    action_id: str,
    allocation: Any,
    expires_at: int,
    links_path: pathlib.Path,
) -> dict[str, Any]:
    """Execute PREPARE phase of 2PC Server Links Allocation."""
    if expires_at <= int(time.time() * 1000):
        return {"status": "TIMEOUT", "executed": False}

    if not isinstance(allocation, list) or not (1 <= len(allocation) <= 10):
        return {"status": "PREPARE_FAILED", "executed": False, "reason": "invalid_allocation_format"}

    seen_urls = set()
    cleaned_allocation = []

    for i, item in enumerate(allocation):
        if not isinstance(item, dict):
            return {"status": "PREPARE_FAILED", "executed": False, "reason": f"invalid_allocation_item_at_{i}"}

        pkg = item.get("pkg", "")
        url = item.get("url", "")

        if pkg != f"com.tinh.vv.h{PKG_SUFFIXES[i]}":
            return {"status": "PREPARE_FAILED", "executed": False, "reason": f"invalid_package_order_at_{i}"}

        if not isinstance(url, str) or not ROBLOX_SERVER_URL_PATTERN.match(url):
            return {"status": "PREPARE_FAILED", "executed": False, "reason": f"invalid_roblox_url_at_{i}"}

        canonical_url = re.sub(r"(?i)\?privateServerLinkCode=", "?privateServerLinkCode=", url)
        if canonical_url in seen_urls:
            return {"status": "PREPARE_FAILED", "executed": False, "reason": f"duplicate_url_at_{i}"}

        seen_urls.add(canonical_url)
        cleaned_allocation.append({"pkg": pkg, "url": canonical_url})

    prep_path = pathlib.Path(f"{links_path}.prep.{action_id}")
    temp_path = pathlib.Path(f"{prep_path}.tmp")
    prep_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            for item in cleaned_allocation:
                f.write(f"{item['pkg']},{item['url']}\n")
        temp_path.replace(prep_path)
        return {"status": "PREPARE_READY", "executed": False}
    except Exception as e:
        return {"status": "PREPARE_FAILED", "executed": False, "reason": f"prepare_failed: {e}"}


def handle_commit(
    action_id: str,
    links_path: pathlib.Path,
    state: dict[str, Any],
    state_path: Optional[pathlib.Path] = None,
) -> dict[str, Any]:
    """Execute COMMIT phase of 2PC Server Links Allocation."""
    cached = (state.get("allocate_action_results") or {}).get(action_id)
    if cached and cached.get("status") == "OPENED":
        return {"status": "OPENED", "executed": True}

    links_path_str = str(links_path)
    bak_path = f"{links_path_str}.bak"
    prep_path = f"{links_path_str}.prep.{action_id}"

    existed_before = os.path.exists(links_path_str)
    try:
        if existed_before:
            shutil.copy2(links_path_str, bak_path)

        if not os.path.exists(prep_path):
            return {"status": "FAILED", "executed": False, "reason": "missing_prep_file"}

        os.replace(prep_path, links_path_str)

        allocation = []
        with open(links_path_str, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                parts = line_str.split(",")
                allocation.append({"pkg": parts[0], "url": ",".join(parts[1:])})

        # Launch apps
        open_roblox_servers(allocation)

        # Journal successful commit
        if "allocate_action_results" not in state:
            state["allocate_action_results"] = {}
        state["allocate_action_results"][action_id] = {"status": "OPENED", "updated_at": int(time.time() * 1000)}

        if state_path:
            try:
                state_path.parent.mkdir(parents=True, exist_ok=True)
                with open(state_path, "w", encoding="utf-8") as sf:
                    json.dump(state, sf)
            except OSError:
                pass

        return {"status": "OPENED", "executed": True}

    except Exception as e:
        # Automatic rollback to previous valid server_links.txt
        if existed_before and os.path.exists(bak_path):
            try:
                shutil.copy2(bak_path, links_path_str)
            except Exception:
                pass
        elif not existed_before and os.path.exists(links_path_str):
            try:
                os.remove(links_path_str)
            except Exception:
                pass
        return {"status": "FAILED", "executed": False, "reason": f"commit_failed: {e}"}


def handle_abort(action_id: str, links_path: pathlib.Path) -> dict[str, Any]:
    """Execute ABORT phase: cleans candidate preparation files."""
    prep_path = pathlib.Path(f"{links_path}.prep.{action_id}")
    try:
        if prep_path.exists():
            prep_path.unlink()
    except OSError:
        pass
    return {"status": "FAILED", "executed": False, "reason": "aborted_by_hub"}
