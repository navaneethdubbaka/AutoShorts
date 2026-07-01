from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any, Optional

class AssetProvider(ABC):
    @abstractmethod
    def search(self, query: str, orientation: str = "portrait", asset_type: str = "stock_video") -> List[Dict[str, Any]]:
        """
        Search for video or image assets based on a query string.
        
        :param query: Search query (e.g. "coding in office").
        :param orientation: "portrait" or "landscape".
        :param asset_type: "stock_video" or "image".
        :return: A list of dicts containing asset metadata:
                 [{"url": "download_url", "id": "asset_id", "width": int, "height": int, "duration": float}]
        """
        pass

    @abstractmethod
    def download(self, download_url: str, output_path: Path) -> Path:
        """
        Download the asset to the given output path.
        
        :param download_url: The URL to download from.
        :param output_path: The file path to save the downloaded asset.
        :return: Path to the saved file.
        """
        pass
