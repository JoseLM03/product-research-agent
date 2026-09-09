import asyncio
import logging
import time

from sqlalchemy import delete, select, update

from .agent import AgentError, research
from .db import Admission, Job, ToolEvent
from .providers import ProviderError
from .schemas import ResearchInput
from .tools import ResearchTools

log = logging.getLogger("fieldwork.worker")


async def run_job(job_id, sessions, settings, model, search):
    with sessions() as db:
        job = db.get(Job, job_id)
        request = ResearchInput.model_validate(job.inputs)

    async def emit(tool, status, detail):
        with sessions.begin() as db:
            db.add(ToolEvent(job_id=job_id, tool=tool, status=status, detail=detail[:500]))
        log.info("tool_event job=%s tool=%s status=%s", job_id, tool, status)

    report, status, error = None, "failed", None
    try:
        async with asyncio.timeout(settings.job_timeout_seconds):
            report, status = await research(
                request, model, ResearchTools(search, request.costs), settings.max_tool_calls, emit
            )
    except (AgentError, ProviderError) as exc:
        error = str(exc)
    except TimeoutError:
        error = "Research exceeded its time limit. Try a more focused idea."
    except asyncio.CancelledError:
        error = "The worker stopped before research finished. Please start a new task."
        raise
    except Exception as exc:
        # Exception class only: providers and validation errors may contain private data.
        log.error("job_error job=%s type=%s", job_id, type(exc).__name__)
        error = "Research encountered an unexpected error. Please try again."
    finally:
        with sessions.begin() as db:
            db.execute(
                update(Job)
                .where(Job.id == job_id, Job.status == "running")
                .values(status=status, report=report, error=error, finished_at=time.time())
            )
        log.info("job_finished job=%s status=%s", job_id, status)


async def worker(sessions, settings, model, search):
    last_cleanup = 0
    while True:
        now = time.time()
        try:
            with sessions.begin() as db:
                # A crashed worker never silently restarts a potentially billable request.
                db.execute(
                    update(Job)
                    .where(
                        Job.status == "running",
                        Job.started_at < now - settings.job_timeout_seconds - 60,
                    )
                    .values(
                        status="failed",
                        error="Worker interrupted. Start a new research task.",
                        finished_at=now,
                    )
                )
                if now - last_cleanup > 3600:
                    db.execute(
                        delete(Job).where(
                            Job.created_at < now - settings.retention_days * 86400,
                            Job.status.not_in(["queued", "running"]),
                        )
                    )
                    db.execute(delete(Admission).where(Admission.created_at < now - 2 * 86400))
                    last_cleanup = now
                candidate = db.scalar(
                    select(Job.id).where(Job.status == "queued").order_by(Job.created_at).limit(1)
                )
                claimed = None
                if candidate and settings.configured:
                    claimed = db.scalar(
                        update(Job)
                        .where(Job.id == candidate, Job.status == "queued")
                        .values(status="running", started_at=now)
                        .returning(Job.id)
                    )
            if claimed:
                await run_job(claimed, sessions, settings, model, search)
            else:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("worker_error type=%s", type(exc).__name__)
            await asyncio.sleep(3)
