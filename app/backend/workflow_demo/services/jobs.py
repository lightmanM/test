"""Run deployment jobs outside the request.

``InlineJobRunner`` runs a job immediately (tests); ``ThreadJobRunner`` uses a thread pool
(local development). On Modal the demo spawns a function per job (P7).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

log = logging.getLogger(__name__)


class JobRunner(Protocol):
    def submit(self, job_id: int) -> None: ...


class InlineJobRunner:
    def __init__(self, run: Callable[[int], None]) -> None:
        self._run = run

    def submit(self, job_id: int) -> None:
        self._run(job_id)


class ThreadJobRunner:
    def __init__(self, run: Callable[[int], None], workers: int = 4) -> None:
        self._run = run
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")

    def submit(self, job_id: int) -> None:
        future = self._pool.submit(self._run, job_id)
        future.add_done_callback(
            lambda f: f.exception() and log.error("job %s crashed: %r", job_id, f.exception())
        )
