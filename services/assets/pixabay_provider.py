import os
import logging
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import settings
from services.assets.base import AssetProvider

logger = logging.getLogger("video_engine.assets.pixabay")

class PixabayProvider(AssetProvider):
    def __init__(self):
        self.api_key = settings.pixabay_api_key
        self.api_url_video = "https://pixabay.com/api/videos/"
        self.api_url_image = "https://pixabay.com/api/"

    def search(self, query: str, orientation: str = "portrait", asset_type: str = "stock_video") -> List[Dict[str, Any]]:
        if not self.api_key:
            logger.warning("Pixabay API key not configured. Skipping search.")
            return []

        params = {
            "key": self.api_key,
            "q": query,
            "per_page": 5
        }
        if asset_type == "image":
            params["image_type"] = "photo"

        try:
            logger.info(f"Pixabay search ({asset_type}): '{query}'")
            if asset_type == "image":
                response = requests.get(self.api_url_image, params=params, timeout=10)
            else:
                response = requests.get(self.api_url_video, params=params, timeout=10)
            
            if response.status_code == 400:
                logger.error("Pixabay request error (400). Bad API key or params.")
                return []
            elif response.status_code != 200:
                logger.error(f"Pixabay error {response.status_code}: {response.text}")
                return []

            data = response.json()
            hits = data.get("hits", [])
            results = []

            if asset_type == "image":
                for hit in hits:
                    url = hit.get("largeImageURL") or hit.get("webformatURL")
                    if url:
                        results.append({
                            "url": url,
                            "id": str(hit.get("id")),
                            "width": hit.get("imageWidth"),
                            "height": hit.get("imageHeight"),
                            "duration": 0.0
                        })
            else:
                for hit in hits:
                    videos_dict = hit.get("videos", {})
                    if not videos_dict:
                        continue

                    best_video = None
                    for size in ["large", "medium", "small"]:
                        size_data = videos_dict.get(size)
                        if size_data and size_data.get("url"):
                            best_video = size_data
                            if size in ["large", "medium"]:
                                break

                    if best_video:
                        results.append({
                            "url": best_video.get("url"),
                            "id": str(hit.get("id")),
                            "width": best_video.get("width"),
                            "height": best_video.get("height"),
                            "duration": hit.get("duration")
                        })

            logger.info(f"Pixabay returned {len(results)} search results.")
            return results

        except Exception as e:
            logger.error(f"Pixabay search request failed: {e}")
            return []

    def download(self, download_url: str, output_path: Path) -> Path:
        """Download Pixabay video clip with chunk streaming."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info(f"Downloading asset from Pixabay: {download_url[:60]}...")
        
        try:
            # Pixabay requires a user-agent header sometimes to avoid bot blocking
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(download_url, headers=headers, stream=True, timeout=30)
            if response.status_code != 200:
                raise Exception(f"Pixabay download failed: HTTP {response.status_code}")

            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        
            logger.info(f"Asset downloaded successfully to: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to download asset: {e}")
            raise e
