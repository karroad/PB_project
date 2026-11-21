"""Dedicated worker process: `python -m app.worker [--concurrency N]`.

Run as many as you need (requires REDIS_URL). Each claims jobs atomically, so scaling to
200+ websites is a matter of adding workers within AI-provider and hosting quotas.
"""
import argparse
import asyncio
import logging
import signal

from .config import settings
from .events import bus
from .init_db import init_db
from .orchestrator.queue import queue


async def main(concurrency: int) -> None:
    init_db()
    await bus.start()
    await queue.start(concurrency)
    logging.getLogger("siteforge").info("Worker %s started with %s slots (%s queue)", queue.worker_id, concurrency, queue.backend)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    try:
        await stop.wait()
    finally:
        await queue.stop()
        await bus.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--concurrency", type=int, default=settings.MAX_CONCURRENT_JOBS)
    args = p.parse_args()
    if not settings.REDIS_URL:
        print("Warning: REDIS_URL is not set — this worker only sees jobs queued in its own process.")
    try:
        asyncio.run(main(args.concurrency))
    except KeyboardInterrupt:
        pass
