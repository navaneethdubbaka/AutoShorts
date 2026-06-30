from typing import List, Optional, Union
from pydantic import BaseModel, Field

class AssetRequest(BaseModel):
    primary: Optional[Union[str, List[str]]] = None
    fallback: Optional[Union[str, List[str]]] = None
    avoid: Optional[Union[str, List[str]]] = None

class Scene(BaseModel):
    start: float
    end: float
    narration: str
    search_keywords: List[str] = Field(default_factory=list)
    asset_request: Optional[AssetRequest] = None
    overlay: Optional[str] = None
    transition: Optional[str] = None
    effects: Optional[List[str]] = Field(default_factory=list)

class VideoRequest(BaseModel):
    project_id: str
    title: str
    script: Optional[str] = None
    duration: float
    voice: str
    voice_model: Optional[str] = None
    background_music: Optional[str] = None
    captions: Optional[bool] = True
    resolution: Optional[str] = "1080x1920"
    fps: Optional[int] = 60
    scenes: List[Scene]

class VideoJobResponse(BaseModel):
    job_id: str
    status: str

class VideoStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: Optional[float] = 0.0
    video_url: Optional[str] = None
    duration: Optional[float] = None
    error: Optional[str] = None
