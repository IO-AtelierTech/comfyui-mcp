"""ComfyUI API client functions.

Low-level HTTP functions for communicating with ComfyUI REST API.
"""

import json
import logging
import time
import urllib
from collections.abc import Callable
from functools import lru_cache
from urllib import request
from urllib.error import HTTPError, URLError

from .settings import settings

logger = logging.getLogger(__name__)


def comfy_get(endpoint: str, timeout: int = 30) -> dict:
    """GET request to ComfyUI API.

    Args:
        endpoint: API endpoint (e.g., '/system_stats')
        timeout: Request timeout in seconds

    Returns:
        Parsed JSON response

    Raises:
        HTTPError: On HTTP errors
        URLError: On connection errors
    """
    url = f"{settings.comfy_url}{endpoint}"
    try:
        req = request.Request(url)
        req.add_header("Accept", "application/json")
        resp = request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except HTTPError as e:
        logger.error(f"HTTP {e.code} for GET {endpoint}")
        raise
    except URLError as e:
        logger.error(f"Connection error for GET {endpoint}: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from {endpoint}: {e}")
        raise


def comfy_post(endpoint: str, data: dict | None = None, timeout: int = 30) -> tuple[int, dict]:
    """POST request to ComfyUI API.

    Args:
        endpoint: API endpoint
        data: JSON data to send
        timeout: Request timeout in seconds

    Returns:
        Tuple of (status_code, response_data)
    """
    url = f"{settings.comfy_url}{endpoint}"
    try:
        encoded = json.dumps(data or {}).encode("utf-8")
        req = request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        resp = request.urlopen(req, timeout=timeout)
        try:
            body = json.loads(resp.read())
        except json.JSONDecodeError:
            body = {}
        return resp.status, body
    except HTTPError as e:
        logger.error(f"HTTP {e.code} for POST {endpoint}")
        return e.code, {"error": str(e)}
    except URLError as e:
        logger.error(f"Connection error for POST {endpoint}: {e}")
        return 0, {"error": str(e)}


def get_file_url(server: str, params: dict) -> str:
    """Build URL for viewing files from ComfyUI.

    Args:
        server: Base server URL
        params: URL parameters (filename, subfolder, type)

    Returns:
        Complete URL string
    """
    url_values = urllib.parse.urlencode(params)
    return f"{server}/view?{url_values}"


def download_file(url: str, timeout: int = 30) -> bytes | None:
    """Download a file from ComfyUI.

    Args:
        url: Full URL to download
        timeout: Request timeout

    Returns:
        File content as bytes, or None on error
    """
    try:
        req = request.Request(url)
        resp = request.urlopen(req, timeout=timeout)
        if resp.status == 200:
            return resp.read()
        return None
    except (URLError, HTTPError) as e:
        logger.error(f"Download error: {e}")
        return None


def poll_for_result(
    prompt_id: str,
    output_node_id: str,
    max_attempts: int | None = None,
    interval: float | None = None,
    on_poll: Callable | None = None,
) -> bytes | None:
    """Poll history until result is ready.

    Args:
        prompt_id: The prompt ID to poll for
        output_node_id: Node ID to get output from
        max_attempts: Max poll attempts (default: settings.poll_timeout)
        interval: Seconds between polls (default: settings.poll_interval)
        on_poll: Optional callback for each poll attempt

    Returns:
        Image bytes if successful, None otherwise
    """
    max_attempts = max_attempts or settings.poll_timeout
    interval = interval or settings.poll_interval

    for attempt in range(max_attempts):
        try:
            history = comfy_get(f"/history/{prompt_id}")
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})

                if status.get("completed"):
                    outputs = entry.get("outputs", {})
                    if output_node_id in outputs:
                        images = outputs[output_node_id].get("images", [])
                        if images:
                            file_url = get_file_url(settings.comfy_url, images[0])
                            return download_file(file_url)
                    # Completed but no images
                    logger.warning(f"No images in node {output_node_id}")
                    return None

                if status.get("status_str") == "error":
                    messages = status.get("messages", [])
                    logger.error(f"Workflow error: {messages}")
                    return None

            if on_poll:
                on_poll(attempt + 1, max_attempts)

        except (URLError, HTTPError) as e:
            logger.warning(f"Poll attempt {attempt + 1} failed: {e}")

        time.sleep(interval)

    logger.error(f"Polling timed out after {max_attempts} attempts")
    return None


@lru_cache(maxsize=1)
def get_cached_nodes() -> dict:
    """Get all node info with caching.

    Returns cached result on subsequent calls.
    Use clear_node_cache() to refresh.
    """
    return comfy_get("/object_info")


def clear_node_cache() -> None:
    """Clear the node info cache."""
    get_cached_nodes.cache_clear()


def check_connection(timeout: int = 5) -> tuple[bool, str | None]:
    """Check if ComfyUI is reachable.

    Args:
        timeout: Connection timeout in seconds

    Returns:
        Tuple of (is_connected, comfyui_version)
    """
    try:
        stats = comfy_get("/system_stats", timeout=timeout)
        version = stats.get("system", {}).get("comfyui_version", "unknown")
        return True, version
    except Exception:
        return False, None


# === High-level API functions ===


def get_system_stats() -> dict:
    """Get ComfyUI system statistics."""
    return comfy_get("/system_stats")


def get_queue() -> dict:
    """Get current queue status."""
    return comfy_get("/queue")


def get_history(max_items: int = 10) -> dict:
    """Get generation history."""
    return comfy_get(f"/history?max_items={max_items}")


def get_history_item(prompt_id: str) -> dict:
    """Get specific history entry."""
    return comfy_get(f"/history/{prompt_id}")


def submit_prompt(workflow: dict) -> tuple[int, dict]:
    """Submit a workflow for execution."""
    return comfy_post("/prompt", {"prompt": workflow})


def interrupt(prompt_id: str | None = None) -> tuple[int, dict]:
    """Interrupt current execution."""
    data = {"prompt_id": prompt_id} if prompt_id else {}
    return comfy_post("/interrupt", data)


def clear_queue(delete_ids: list[str] | None = None) -> tuple[int, dict]:
    """Clear queue or delete specific items."""
    if delete_ids:
        return comfy_post("/queue", {"delete": delete_ids})
    return comfy_post("/queue", {"clear": True})


def get_node_info(node_name: str) -> dict:
    """Get info for a specific node."""
    return comfy_get(f"/object_info/{node_name}")


def get_models(folder: str = "checkpoints") -> list:
    """Get models in a folder."""
    try:
        return comfy_get(f"/models/{folder}")
    except HTTPError as e:
        if e.code == 404:
            return []
        raise


def get_embeddings() -> list:
    """Get available embeddings."""
    return comfy_get("/embeddings")
