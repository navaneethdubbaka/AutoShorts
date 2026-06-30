import time
from typing import Dict, Optional
from pydantic import BaseModel, Field
import threading

class VideoJob(BaseModel):
    job_id: str
    status: str = "queued"  # queued, processing, completed, failed
    progress: float = 0.0
    video_url: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    payload: dict

# Thread-safe in-memory job store
class JobStore:
    def __init__(self):
        self._jobs: Dict[str, VideoJob] = {}
        self._lock = threading.Lock()

    def add(self, job: VideoJob):
        with self._lock:
            self._jobs[job.job_id] = job

    def get(self, job_id: str) -> Optional[VideoJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **kwargs):
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                for k, v in kwargs.items():
                    if hasattr(job, k):
                        setattr(job, k, v)
                job.updated_at = time.time()
                return job
            return None

    def list_all(self) -> Dict[str, VideoJob]:
        with self._lock:
            return dict(self._jobs)

# Global job registry
job_store = JobStore()
