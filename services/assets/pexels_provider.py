import os
import logging
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import settings
from services.assets.base import AssetProvider

logger = logging.getLogger("video_engine.assets.pexels")

class PexelsProvider(AssetProvider):
    def __init__(self):
        self.api_key = settings.pexels_api_key
        self.api_url_video = "https://api.pexels.com/videos/search"
        self.api_url_image = "https://api.pexels.com/v1/search"

    def search(self, query: str, orientation: str = "portrait", asset_type: str = "stock_video") -> List[Dict[str, Any]]:
        if not self.api_key:
            logger.warning("Pexels API key not configured. Skipping search.")
            return []

        headers = {
            "Authorization": self.api_key
        }
        params = {
            "query": query,
            "orientation": orientation,
            "per_page": 5
        }

        try:
            logger.info(f"Pexels search ({asset_type}): '{query}' (orientation: {orientation})")
            
            if asset_type == "image":
                response = requests.get(self.api_url_image, headers=headers, params=params, timeout=10)
            else:
                response = requests.get(self.api_url_video, headers=headers, params=params, timeout=10)
            
            if response.status_code == 401:
                logger.error("Pexels unauthorized. Invalid API key.")
                return []
            elif response.status_code == 429:
                logger.warning("Pexels rate limited (429).")
                return []
            elif response.status_code != 200:
                logger.error(f"Pexels error {response.status_code}: {response.text}")
                return []

            data = response.json()
            results = []

            if asset_type == "image":
                photos = data.get("photos", [])
                for photo in photos:
                    src = photo.get("src", {})
                    # Prefer portrait for portrait, large2x/large/original as fallback
                    url = src.get("portrait") or src.get("large2x") or src.get("large") or src.get("original")
                    if url:
                        results.append({
                            "url": url,
                            "id": str(photo.get("id")),
                            "width": photo.get("width"),
                            "height": photo.get("height"),
                            "duration": 0.0
                        })
            else:
                videos = data.get("videos", [])
                for video in videos:
                    files = video.get("video_files", [])
                    if not files:
                        continue

                    best_file = None
                    mp4_files = [f for f in files if f.get("file_type") == "video/mp4"]
                    mp4_files.sort(key=lambda f: (f.get("width", 0) or 0) * (f.get("height", 0) or 0), reverse=True)
                    
                    for f in mp4_files:
                        link = f.get("link")
                        if not link:
                            continue
                        w, h = f.get("width", 0) or 0, f.get("height", 0) or 0
                        
                        best_file = f
                        if min(w, h) >= 720 and max(w, h) <= 1920:
                            best_file = f
                            break

                    if best_file:
                        results.append({
                            "url": best_file.get("link"),
                            "id": str(video.get("id")),
                            "width": best_file.get("width"),
                            "height": best_file.get("height"),
                            "duration": video.get("duration")
                        })

            logger.info(f"Pexels returned {len(results)} search results.")
            return results

        except Exception as e:
            logger.error(f"Pexels search request failed: {e}")
            return []

    def download(self, download_url: str, output_path: Path) -> Path:
        """Download Pexels video clip with chunk streaming."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading asset from Pexels: {download_url[:60]}...")
        
        try:
            response = requests.get(download_url, stream=True, timeout=30)
            if response.status_code != 200:
                raise Exception(f"Pexels download failed: HTTP {response.status_code}")

            # Stream download to avoid loading large files into memory
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            logger.info(f"Asset downloaded successfully to: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to download asset: {e}")
            raise e
