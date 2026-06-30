import os
import time
import shutil
import logging
from pathlib import Path
from config import settings

logger = logging.getLogger("video_engine.utils.cleanup")

def cleanup_temp_dir(max_age_hours: float = 2.0) -> int:
    """
    Cleans up directories inside settings.temp_dir that have not been 
    modified in more than max_age_hours.
    
    :param max_age_hours: Threshold in hours.
    :return: Number of deleted directories.
    """
    temp_path = settings.temp_dir
    if not temp_path.exists():
        return 0
        
    now = time.time()
    cutoff = now - (max_age_hours * 3600)
    deleted_count = 0
    
    logger.info(f"Starting cleanup of temp directory: {temp_path} (threshold: {max_age_hours} hours)")
    
    for item in temp_path.iterdir():
        if item.is_dir():
            # Check modification time
            try:
                mtime = item.stat().st_mtime
                if mtime < cutoff:
                    logger.info(f"Deleting expired temp folder: {item.name} (last modified {time.ctime(mtime)})")
                    shutil.rmtree(item, ignore_errors=True)
                    deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to check/delete temp item {item.name}: {e}")
                
    if deleted_count > 0:
        logger.info(f"Pruned {deleted_count} expired temporary directories.")
    else:
        logger.info("No expired temporary directories found.")
        
    return deleted_count

if __name__ == "__main__":
    from utils.logging import setup_logging
    setup_logging()
    cleanup_temp_dir()
