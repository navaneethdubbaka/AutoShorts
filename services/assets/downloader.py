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
    search_query: str, 
    asset_type: str,
    duration: float, 
    scene_id: int, 
    job_id: str,
    orientation: str = "portrait"
) -> Path:
    """
    Search, cache, and download stock asset (video or image) for a scene.
    If image asset is requested, it is downloaded and converted to an MP4 video of the specified duration.
    Falls back sequentially: Pexels -> Pixabay -> Local Fallback files -> FFmpeg generated solid colors.
    """
    dest_dir = settings.assets_dir / job_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"scene_{scene_id}.mp4"

    # 1. Prepare search query and cache key
    raw_query = search_query.strip()
    if not raw_query:
        raw_query = "abstract background"
        
    cache_query_key = f"{asset_type}:{raw_query}"

    # 2. Check Cache
    cached_results = asset_cache.get_search_results(cache_query_key, orientation)
    
    results = []
    if cached_results is not None:
        results = cached_results
    else:
        # Pexels search
        pexels = PexelsProvider()
        results = pexels.search(raw_query, orientation, asset_type)
        
        # Pixabay fallback search
        if not results:
            pixabay = PixabayProvider()
            results = pixabay.search(raw_query, orientation, asset_type)
            
        # Save search results to cache
        asset_cache.save_search_results(cache_query_key, orientation, results)

    # 3. Download best result if available
    if results:
        best_result = results[0]
        url = best_result["url"]
        
        # Check if media is already cached
        cached_media = asset_cache.get_cached_media(url)
        if cached_media and cached_media.exists():
            logger.info(f"Using cached asset for scene {scene_id}")
            if asset_type == "image":
                # Convert the cached image to MP4
                try:
                    logger.info(f"Converting cached image to MP4 for scene {scene_id} ({duration}s)...")
                    w_h = "1920x1080" if orientation == "landscape" else "1080x1920"
                    res_arg = "1920:1080" if orientation == "landscape" else "1080:1920"
                    vf_filter = f"scale={res_arg}:force_original_aspect_ratio=increase,crop={res_arg}"
                    
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1",
                        "-i", str(cached_media),
                        "-t", str(duration),
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-vf", vf_filter,
                        "-r", "30",
                        str(dest_path)
                    ]
                    subprocess.run(cmd, capture_output=True, text=True, check=True)
                    return dest_path
                except Exception as convert_err:
                    logger.error(f"Failed to convert cached image to video: {convert_err}")
            else:
                shutil.copy(cached_media, dest_path)
                return dest_path
            
        # Download and cache
        suffix = ".jpg" if asset_type == "image" else ".mp4"
        temp_download = settings.temp_dir / f"download_{job_id}_{scene_id}{suffix}"
        try:
            provider = PexelsProvider()  # Generic HTTP downloader works for both
            provider.download(url, temp_download)
            
            # Cache it
            cached_media = asset_cache.save_media(url, temp_download)
            
            if asset_type == "image":
                logger.info(f"Converting downloaded image to MP4 for scene {scene_id} ({duration}s)...")
                w_h = "1920x1080" if orientation == "landscape" else "1080x1920"
                res_arg = "1920:1080" if orientation == "landscape" else "1080:1920"
                vf_filter = f"scale={res_arg}:force_original_aspect_ratio=increase,crop={res_arg}"
                
                cmd = [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(cached_media),
                    "-t", str(duration),
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-vf", vf_filter,
                    "-r", "30",
                    str(dest_path)
                ]
                subprocess.run(cmd, capture_output=True, text=True, check=True)
            else:
                shutil.copy(cached_media, dest_path)
            return dest_path
        except Exception as e:
            logger.error(f"Download or processing failed for URL {url}: {e}. Trying other fallbacks...")
        finally:
            if temp_download.exists():
                os.remove(temp_download)

    # 4. Fallback: Local curated folder of files
    fallback_pool_dir = settings.assets_dir / "fallback"
    fallback_pool_dir.mkdir(parents=True, exist_ok=True)
    
    fallback_files = list(fallback_pool_dir.glob("*.mp4"))
    if fallback_files:
        selected_fallback = random.choice(fallback_files)
        logger.info(f"Using local B-roll fallback pool asset: {selected_fallback.name}")
        shutil.copy(selected_fallback, dest_path)
        return dest_path

    # 5. Last Resort Fallback: Generate solid pastel color MP4 using FFmpeg
    color = PASTEL_COLORS[scene_id % len(PASTEL_COLORS)]
    target_res = "1920x1080" if orientation == "landscape" else "1080x1920"
    try:
        generate_solid_color_video(color=color, duration=duration, output_path=dest_path, resolution=target_res)
        return dest_path
    except Exception as e:
        logger.error(f"Last resort color-generation fallback failed: {e}")
        raise e
