import asyncio
import os

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import CHECK_SCHEDULE, TIMEZONE
from .services import check_all

scheduler = BackgroundScheduler(timezone=TIMEZONE)


def run_check_all() -> None:
    asyncio.run(check_all())


def start() -> None:
    if scheduler.get_job("daily_price_check"):
        return
    parts = CHECK_SCHEDULE.split(":")
    hour = int(parts[0]) if parts and parts[0].isdigit() else 8
    minute = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    scheduler.add_job(
        run_check_all,
        CronTrigger(hour=hour, minute=minute, timezone=os.getenv("TZ", TIMEZONE)),
        id="daily_price_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


def next_run() -> str | None:
    job = scheduler.get_job("daily_price_check")
    if job and job.next_run_time:
        return job.next_run_time.isoformat()
    return None


def stop() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
