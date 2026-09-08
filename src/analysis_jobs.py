import threading
import uuid

# In-memory job store for /api/analyze's background-job + polling flow.
# Process-lifetime only (not persisted) - acceptable since this mirrors a
# single recruiter's live session, not history that needs to survive a
# restart (the DB is still the source of truth for completed analyses).
_jobs = {}
_lock = threading.Lock()


def create_job():
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"status": "running", "total": None, "results": [], "error": None}
    return job_id


def report_total(job_id, total):
    with _lock:
        _jobs[job_id]["total"] = total


def report_result(job_id, result):
    with _lock:
        _jobs[job_id]["results"].append(result)


def set_results(job_id, results):
    """Overwrites the job's results with a final, ordered list - used once
    the batch is fully done, since report_result() above only ever appends in
    completion order (from the on_result callback), not the best-fit-sorted
    order that run_zoho()/run_zoho_for_job() produce as their return value."""
    with _lock:
        _jobs[job_id]["results"] = list(results)


def finish_job(job_id):
    with _lock:
        _jobs[job_id]["status"] = "done"


def fail_job(job_id, error_message):
    with _lock:
        _jobs[job_id]["status"] = "error"
        _jobs[job_id]["error"] = error_message


def get_job(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {**job, "results": list(job["results"])}


def start_job(target):
    """Runs target(job_id) in a background thread and returns the new job_id
    immediately. target is expected to call report_total()/report_result()
    as it goes - it must not run pipeline work directly on the caller's
    thread, since that's the FastAPI event loop thread and would block every
    other request (including status polling) for the whole analysis run."""
    job_id = create_job()

    def runner():
        try:
            target(job_id)
            finish_job(job_id)
        except Exception as e:
            fail_job(job_id, str(e))

    threading.Thread(target=runner, daemon=True).start()
    return job_id
