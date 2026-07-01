from typing import List, Optional, Union
from pydantic import BaseModel, Field, field_validator

class AssetRequest(BaseModel):
    primary: Optional[Union[str, List[str]]] = None
    fallback: Optional[Union[str, List[str]]] = None
    avoid: Optional[Union[str, List[str]]] = None

class Scene(BaseModel):
    id: int
    start: float
    end: float
    narration: str
    search_query: str
    asset_type: str = "stock_video"
    asset_request: Optional[AssetRequest] = None
    overlay: Optional[str] = None
    transition: Optional[str] = None
    effects: Optional[List[str]] = Field(default_factory=list)

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, value: str) -> str:
        allowed = {"stock_video", "image", "logo", "icon"}
        if value not in allowed:
            raise ValueError(f"asset_type must be one of {allowed}")
        return value

class VideoRequest(BaseModel):
    project_id: str
    title: str
    voice: Optional[str] = None
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
