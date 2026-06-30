import shutil
import logging
from pathlib import Path
from config import settings
from services.storage.base import StorageBackend

logger = logging.getLogger("video_engine.storage.local")

class LocalStorage(StorageBackend):
    def __init__(self):
        self.output_dir = settings.output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def save(self, source_path: Path, filename: str) -> str:
        """
        Saves the file by copying it to the configured local output directory.
        Returns the local API download path.
        """
        if not source_path.exists():
            raise FileNotFoundError(f"Source file to store does not exist: {source_path}")
            
        dest_path = self.output_dir / filename
        
        # Avoid copying if source and dest are the same file
        if source_path.resolve() != dest_path.resolve():
            logger.info(f"Storing file: {source_path.name} -> {dest_path}")
            shutil.copy(source_path, dest_path)
        else:
            logger.info(f"File already in output directory: {dest_path}")
            
        # Return URL relative to our download endpoint
        # Example: /download/project_id
        # Extract filename base if matching our structure
        job_id = Path(filename).stem
        return f"/download/{job_id}"
