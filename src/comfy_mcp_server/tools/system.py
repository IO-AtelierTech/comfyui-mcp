"""System monitoring and control tools.

Impact: High (essential for debugging and monitoring)
Complexity: Low (simple API calls)
"""

from mcp.server.fastmcp import Context
from pydantic import Field

from ..api import comfy_get, comfy_post
from ..models import ErrorResponse, QueueStatus, SystemStats


def register_system_tools(mcp):
    """Register system monitoring tools."""

    @mcp.tool()
    def get_system_stats(ctx: Context) -> dict:
        """Get ComfyUI server health: version, memory, device info.

        Returns system information including:
        - ComfyUI and PyTorch versions
        - RAM usage
        - Device info (CPU/GPU)

        Use this to verify ComfyUI is running and check resource usage.
        """
        ctx.info("Fetching system stats...")
        try:
            data = comfy_get("/system_stats")
            stats = SystemStats(**data)
            return stats.model_dump()
        except Exception as e:
            return ErrorResponse.unavailable(str(e)).model_dump()

    @mcp.tool()
    def get_queue_status(ctx: Context) -> dict:
        """Get current queue: running and pending jobs.

        Returns:
        - queue_running: List of currently executing workflows
        - queue_pending: List of queued workflows waiting to run
        - running_count: Number of running jobs
        - pending_count: Number of pending jobs

        Use this to check if workflows are executing or queued.
        """
        ctx.info("Fetching queue status...")
        try:
            data = comfy_get("/queue")
            status = QueueStatus(**data)
            result = status.model_dump()
            result["running_count"] = status.running_count
            result["pending_count"] = status.pending_count
            result["is_empty"] = status.is_empty
            return result
        except Exception as e:
            return ErrorResponse.unavailable(str(e)).model_dump()

    @mcp.tool()
    def get_history(
        limit: int = Field(default=10, ge=1, le=100, description="Max entries to return"),
        ctx: Context = None,
    ) -> dict:
        """Get recent generation history.

        Args:
            limit: Maximum number of history entries (1-100, default: 10)

        Returns history entries with outputs and status for each job.
        Use this to see past generations and their results.
        """
        if ctx:
            ctx.info(f"Fetching last {limit} history entries...")
        try:
            return comfy_get(f"/history?max_items={limit}")
        except Exception as e:
            return ErrorResponse.unavailable(str(e)).model_dump()

    @mcp.tool()
    def cancel_current(
        prompt_id: str = Field(default=None, description="Specific prompt ID to cancel"),
        ctx: Context = None,
    ) -> str:
        """Interrupt current generation.

        Args:
            prompt_id: Optional specific prompt ID to cancel.
                      If not provided, cancels all running jobs.

        Use this to stop a long-running generation.
        """
        if ctx:
            msg = f"Cancelling prompt {prompt_id}" if prompt_id else "Cancelling all"
            ctx.info(msg)

        data = {"prompt_id": prompt_id} if prompt_id else {}
        status, _ = comfy_post("/interrupt", data)
        return "Interrupted successfully" if status == 200 else "Interrupt failed"

    @mcp.tool()
    def clear_queue(
        delete_ids: list = Field(default=None, description="Specific prompt IDs to delete"),
        ctx: Context = None,
    ) -> str:
        """Clear the queue or delete specific items.

        Args:
            delete_ids: Optional list of prompt IDs to delete.
                       If not provided, clears entire queue.

        Use this to remove pending jobs from the queue.
        """
        if ctx:
            if delete_ids:
                ctx.info(f"Deleting {len(delete_ids)} items from queue")
            else:
                ctx.info("Clearing entire queue")

        if delete_ids:
            status, _ = comfy_post("/queue", {"delete": delete_ids})
        else:
            status, _ = comfy_post("/queue", {"clear": True})

        return "Queue cleared" if status == 200 else "Clear failed"
