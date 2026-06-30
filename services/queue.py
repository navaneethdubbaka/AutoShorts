import queue
import threading
import logging
import traceback
from models.job import job_store
from services.pipeline import run_pipeline

logger = logging.getLogger("video_engine.queue")

class JobQueueManager:
    def __init__(self):
        self._queue = queue.Queue()
        self._worker_thread = None
        self._stop_event = threading.Event()

    def start(self):
        """Start the background worker thread."""
        if self._worker_thread is not None and self._worker_thread.is_alive():
            logger.info("Worker thread is already running.")
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="JobWorkerThread")
        self._worker_thread.start()
        logger.info("Background job worker thread started.")

    def stop(self):
        """Stop the background worker thread."""
        self._stop_event.set()
        # Put a sentinel/None value in queue to wake up the worker
        self._queue.put(None)
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
            logger.info("Background job worker thread stopped.")

    def submit(self, job_id: str):
        """Submit a job ID to the queue."""
        self._queue.put(job_id)
        logger.info(f"Job {job_id} submitted to queue.")

    def _worker_loop(self):
        while not self._stop_event.is_set():
            try:
                # Wait for a job with a timeout so we periodically check stop_event
                job_id = self._queue.get(timeout=1.0)
                if job_id is None:
                    # Sentinel received, shutdown
                    self._queue.task_done()
                    break

                logger.info(f"Worker picked up job {job_id} from queue.")
                self._process_job(job_id)
                self._queue.task_done()

            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in worker loop: {e}\n{traceback.format_exc()}")

    def _process_job(self, job_id: str):
        job = job_store.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found in job store.")
            return

        # Mark job as processing
        job_store.update(job_id, status="processing", progress=5.0)
        logger.info(f"Job {job_id} marked as processing.")

        try:
            # Execute the actual generation pipeline
            result = run_pipeline(job_id, job.payload)
            
            # Update job status with results
            job_store.update(
                job_id, 
                status="completed", 
                progress=100.0,
                video_url=result.get("video_url"),
                duration=result.get("duration")
            )
            logger.info(f"Job {job_id} completed successfully.")

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Job {job_id} failed with error: {error_msg}\n{traceback.format_exc()}")
            job_store.update(
                job_id, 
                status="failed", 
                progress=100.0,
                error=error_msg
            )

# Global queue manager instance
queue_manager = JobQueueManager()
