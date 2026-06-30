import os
import time
import json
import hashlib
import shutil
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from config import settings

logger = logging.getLogger("video_engine.assets.cache")

class AssetCacheManager:
    def __init__(self):
        self.cache_dir = settings.assets_dir / "cache"
        self.search_dir = self.cache_dir / "search"
        self.media_dir = self.cache_dir / "media"
        
        self.search_dir.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache duration: 24 hours in seconds
        self.cache_duration_sec = 24 * 60 * 60

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.encode("utf-8")).hexdigest()

    def get_search_results(self, query: str, orientation: str) -> Optional[List[Dict[str, Any]]]:
        """Retrieve cached search results if valid and under 24 hours old."""
        key = f"{query}|||{orientation}"
        hash_val = self._hash_key(key)
        cache_file = self.search_dir / f"{hash_val}.json"
        
        if cache_file.exists():
            # Check age
            file_age = time.time() - cache_file.stat().st_mtime
            if file_age < self.cache_duration_sec:
                try:
                    with open(cache_file, "r") as f:
                        logger.info(f"Cache hit for search query: '{query}' ({orientation})")
                        return json.load(f)
                except Exception as e:
                    logger.error(f"Failed to read search cache file: {e}")
            else:
                logger.info(f"Search cache expired for query: '{query}'")
        return None

    def save_search_results(self, query: str, orientation: str, results: List[Dict[str, Any]]):
        """Save search results to cache."""
        key = f"{query}|||{orientation}"
        hash_val = self._hash_key(key)
        cache_file = self.search_dir / f"{hash_val}.json"
        try:
            with open(cache_file, "w") as f:
                json.dump(results, f)
            logger.info(f"Saved search query to cache: '{query}'")
        except Exception as e:
            logger.error(f"Failed to write search cache file: {e}")

    def get_cached_media(self, url: str) -> Optional[Path]:
        """Retrieve cached media file path if it exists."""
        hash_val = self._hash_key(url)
        # Find any matching file suffix (e.g. .mp4, .jpg, etc.)
        for path in self.media_dir.glob(f"{hash_val}.*"):
            if path.exists() and path.stat().st_size > 0:
                logger.info(f"Cache hit for media URL: {url[:50]}...")
                return path
        return None

    def save_media(self, url: str, source_path: Path) -> Path:
        """Cache a downloaded media file."""
        if not source_path.exists():
            raise FileNotFoundError(f"Source file does not exist: {source_path}")
            
        hash_val = self._hash_key(url)
        suffix = source_path.suffix
        cache_path = self.media_dir / f"{hash_val}{suffix}"
        
        try:
            shutil.copy(source_path, cache_path)
            logger.info(f"Cached media file saved: {cache_path.name}")
            return cache_path
        except Exception as e:
            logger.error(f"Failed to copy media file to cache: {e}")
            return source_path

asset_cache = AssetCacheManager()
