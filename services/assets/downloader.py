import os
import random
import subprocess
import logging
import shutil
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import settings
from services.assets.cache import asset_cache
from services.assets.pexels_provider import PexelsProvider
from services.assets.pixabay_provider import PixabayProvider

logger = logging.getLogger("video_engine.assets.downloader")

# Predefined pleasant colors for fallback video generation
PASTEL_COLORS = [
    "0x2B2D42", # Dark Slate
    "0x8D99AE", # Cool Grey
    "0xEF233C", # Crimson
    "0xD90429", # Red-ruby
    "0x4A90E2", # Soft Blue
    "0x50E3C2", # Turquoise
    "0xB8E986", # Soft Green
    "0xF5A623", # Amber
    "0x9013FE"  # Purple
]

def generate_solid_color_video(color: str, duration: float, output_path: Path, resolution: str = "1080x1920", fps: int = 30) -> Path:
    """Generates a solid color MP4 video using FFmpeg as a last-resort fallback."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Generating solid-color fallback video ({color}) of {duration}s -> {output_path.name}")
    
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={color}:s={resolution}:d={duration}:r={fps}",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return output_path
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg solid-color generation failed: {e.stderr}")
        raise RuntimeError(f"Failed to generate solid fallback video: {e.stderr}")

def get_scene_asset(
    keywords: List[str], 
    duration: float, 
    scene_index: int, 
    job_id: str,
    orientation: str = "portrait"
) -> Path:
    """
    Search, cache, and download stock asset for a scene.
    Falls back sequentially: Pexels -> Pixabay -> Local Fallback files -> FFmpeg generated solid colors.
    """
    dest_dir = settings.assets_dir / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"scene_{scene_index}.mp4"

    # 1. Prepare search query
    query = " ".join(keywords).strip()
    if not query:
        query = "abstract background"

    # 2. Check Cache
    cached_results = asset_cache.get_search_results(query, orientation)
    
    results = []
    if cached_results is not None:
        results = cached_results
    else:
        # Pexels search
        pexels = PexelsProvider()
        results = pexels.search(query, orientation)
        
        # Pixabay fallback search
        if not results:
            pixabay = PixabayProvider()
            results = pixabay.search(query, orientation)
            
        # Save search results to cache
        asset_cache.save_search_results(query, orientation, results)

    # 3. Download best result if available
    if results:
        # Take the first video result
        best_result = results[0]
        url = best_result["url"]
        
        # Check if media is already cached
        cached_media = asset_cache.get_cached_media(url)
        if cached_media and cached_media.exists():
            logger.info(f"Using cached video clip for scene {scene_index}")
            shutil.copy(cached_media, dest_path)
            return dest_path
            
        # Download and cache
        temp_download = settings.temp_dir / f"download_{job_id}_{scene_index}.mp4"
        try:
            # Pexels or Pixabay download (both can download standard HTTP links using requests)
            provider = PexelsProvider()  # Generic HTTP downloader works for both
            provider.download(url, temp_download)
            
            # Cache it
            asset_cache.save_media(url, temp_download)
            
            # Copy to destination
            shutil.copy(temp_download, dest_path)
            return dest_path
        except Exception as e:
            logger.error(f"Download failed for URL {url}: {e}. Trying other fallbacks...")
        finally:
            if temp_download.exists():
                os.remove(temp_download)

    # 4. Fallback: Local curated folder of files
    fallback_pool_dir = settings.assets_dir / "fallback"
    fallback_pool_dir.mkdir(parents=True, exist_ok=True)
    
    # Check if there are any MP4 files in fallback
    fallback_files = list(fallback_pool_dir.glob("*.mp4"))
    if fallback_files:
        selected_fallback = random.choice(fallback_files)
        logger.info(f"Using local B-roll fallback pool asset: {selected_fallback.name}")
        shutil.copy(selected_fallback, dest_path)
        return dest_path

    # 5. Last Resort Fallback: Generate solid pastel color MP4 using FFmpeg
    color = PASTEL_COLORS[scene_index % len(PASTEL_COLORS)]
    try:
        generate_solid_color_video(color=color, duration=duration, output_path=dest_path)
        return dest_path
    except Exception as e:
        logger.error(f"Last resort color-generation fallback failed: {e}")
        raise e
