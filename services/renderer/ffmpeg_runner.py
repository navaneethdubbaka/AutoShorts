import subprocess
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger("video_engine.renderer.runner")

class FFmpegRenderError(Exception):
    """Raised when the FFmpeg rendering subprocess fails."""
    pass

def run_ffmpeg(command: List[str], timeout_seconds: int = 300) -> None:
    """
    Executes an assembled FFmpeg command.
    Monitors process and catches stderr for diagnostics.
    """
    logger.info("Initializing FFmpeg render process...")
    # Log the command in a readable format for debugging
    logger.debug(f"FFmpeg Command: {' '.join(command)}")
    
    try:
        # Run subprocess and capture output
        # Using shell=False is safer and works across both Windows and Linux
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False  # We handle returncode manually to capture stderr
        )
        
        if result.returncode != 0:
            # Gather stderr output for detailed reporting
            stderr_output = result.stderr or "No error output provided by FFmpeg."
            logger.error(f"FFmpeg render failed with exit code {result.returncode}")
            logger.error(f"FFmpeg Stderr:\n{stderr_output}")
            raise FFmpegRenderError(
                f"FFmpeg process failed with exit code {result.returncode}.\n"
                f"Diagnostics: {stderr_output.strip().splitlines()[-10:]}" # last 10 lines of logs
            )
            
        logger.info("FFmpeg render completed successfully.")
        
    except subprocess.TimeoutExpired as e:
        logger.error(f"FFmpeg render exceeded the timeout of {timeout_seconds}s and was terminated.")
        raise FFmpegRenderError(f"Rendering process timed out after {timeout_seconds} seconds.")
    except Exception as e:
        if not isinstance(e, FFmpegRenderError):
            logger.error(f"An unexpected error occurred during rendering execution: {e}")
            raise FFmpegRenderError(f"Subprocess runner failed: {e}") from e
