"""Scheduler 运行时兼容入口。"""

from arthra.daily_summary import daily_summary_scheduler


async def run_scheduler() -> None:
    await daily_summary_scheduler()
