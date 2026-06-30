import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Header, Depends, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
import logging

from config import settings
from utils.logging import setup_logging
from models.schemas import VideoRequest, VideoJobResponse, VideoStatusResponse
from models.job import VideoJob, job_store
from services.queue import queue_manager

logger = logging.getLogger("video_engine.api")

# Verify API key dependency
async def verify_api_key(x_api_key: str = Header(default="", alias="X-API-Key")):
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key"
        )
    return x_api_key

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: setup logging and start background queue worker
    setup_logging()
    logger.info("Initializing AutoShorts Video Engine...")
    queue_manager.start()
    yield
    # Shutdown: stop background queue worker
    logger.info("Shutting down AutoShorts Video Engine...")
    queue_manager.stop()

app = FastAPI(
    title="AutoShorts Video Engine",
    description="CPU-optimized Video Rendering Engine API",
    version="1.0.0",
    lifespan=lifespan
)

@app.post(
    "/generate-video", 
    response_model=VideoJobResponse, 
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_key)]
)
async def generate_video(request: VideoRequest):
    # Determine job ID: use project_id (standard for this system)
    job_id = request.project_id
    
    # Check if job is already running/queued
    existing_job = job_store.get(job_id)
    if existing_job and existing_job.status in ["queued", "processing"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job {job_id} is already in state: {existing_job.status}"
        )
        
    logger.info(f"Received video generation request for project {job_id}")
    
    # Create the job state in our in-memory store
    job = VideoJob(
        job_id=job_id,
        status="queued",
        payload=request.model_dump()
    )
    job_store.add(job)
    
    # Submit job to the worker queue
    queue_manager.submit(job_id)
    
    return VideoJobResponse(job_id=job_id, status="queued")

@app.get("/status/{job_id}", response_model=VideoStatusResponse)
async def get_job_status(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
    
    # If the status is completed, verify if file exists
    video_url = None
    if job.status == "completed":
        file_name = f"{job_id}.mp4"
        file_path = settings.output_dir / file_name
        # Note: In Phase 1, we simulate completion without writing a file.
        # So we only assert file existence if the pipeline is actually running for real.
        # For now we will return the video url.
        video_url = f"/download/{job_id}"

    return VideoStatusResponse(
        job_id=job.job_id,
        status=job.status,
        progress=job.progress,
        video_url=video_url,
        duration=job.duration,
        error=job.error
    )

@app.get("/download/{job_id}")
async def download_video(job_id: str):
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found"
        )
        
    if job.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Job {job_id} has status: {job.status} (not completed)"
        )
        
    file_name = f"{job_id}.mp4"
    file_path = settings.output_dir / file_name
    if not file_path.is_absolute():
        file_path = settings.base_dir / file_path

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video file not found on disk"
        )
        
    return FileResponse(
        path=str(file_path),
        media_type="video/mp4",
        filename=file_name
    )

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "queue_depth": queue_manager._queue.qsize()
    }
