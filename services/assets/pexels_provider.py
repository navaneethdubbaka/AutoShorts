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
        self.api_url = "https://api.pexels.com/videos/search"

    def search(self, query: str, orientation: str = "portrait") -> List[Dict[str, Any]]:
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
            logger.info(f"Pexels search: '{query}' (orientation: {orientation})")
            response = requests.get(self.api_url, headers=headers, params=params, timeout=10)
            
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
            videos = data.get("videos", [])
            results = []

            for video in videos:
                files = video.get("video_files", [])
                if not files:
                    continue

                # Find the best quality mp4 link
                # We prefer HD (typically 720p or 1080p) to keep download size reasonable on CPU
                best_file = None
                
                # Sort files by resolution (height * width) descending
                mp4_files = [f for f in files if f.get("file_type") == "video/mp4"]
                mp4_files.sort(key=lambda f: (f.get("width", 0) or 0) * (f.get("height", 0) or 0), reverse=True)
                
                # We want something around 1080x1920 (if portrait) or 1920x1080 (if landscape)
                # Avoid files that are too huge (e.g. 4K) or too tiny (e.g. 240p)
                for f in mp4_files:
                    link = f.get("link")
                    if not link:
                        continue
                    w, h = f.get("width", 0) or 0, f.get("height", 0) or 0
                    
                    # Ideal portrait: height close to 1080 or 1920
                    # Ideal landscape: width close to 1080 or 1920
                    best_file = f
                    # Break early once we find a solid HD resolution (e.g. >= 720p)
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
