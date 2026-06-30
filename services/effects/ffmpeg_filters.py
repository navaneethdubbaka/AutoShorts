import logging

logger = logging.getLogger("video_engine.effects.filters")

def get_scale_and_crop_filter(target_w: int = 1080, target_h: int = 1920) -> str:
    """
    Returns an FFmpeg filter string that scales and crops any source video 
    to fill the target dimensions while preserving the aspect ratio.
    """
    # scale = resize so the video covers the target dimensions
    # crop = crop the center portion to match target dimensions
    return f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}"

def get_fade_filters(duration: float, fade_duration: float = 0.5) -> str:
    """
    Returns video fade-in and fade-out filters.
    """
    if duration <= fade_duration * 2:
        # If the clip is too short, scale down the fade duration
        fade_duration = duration / 3.0
        
    fade_in = f"fade=t=in:st=0:d={fade_duration:.2f}"
    fade_out = f"fade=t=out:st={duration - fade_duration:.2f}:d={fade_duration:.2f}"
    return f"{fade_in},{fade_out}"

def get_ken_burns_filter(duration: float, fps: int = 30, target_w: int = 1080, target_h: int = 1920) -> str:
    """
    Returns a safe zoompan filter to create a Ken Burns effect.
    """
    total_frames = int(duration * fps)
    
    # We zoom in slowly from 1.0 to 1.15 over the duration of the clip
    # 'min(zoom+0.0005,1.15)' -> increments zoom by 0.0005 per frame up to 1.15
    # x/y coordinates keep the zoom centered
    zoom_expr = "min(zoom+0.0005,1.15)"
    x_expr = "iw/2-(iw/zoom/2)"
    y_expr = "ih/2-(ih/zoom/2)"
    
    # Note: zoompan must be applied before scaling or after scaling depending on aspect ratio.
    # Applied to 1080x1920 stream:
    return f"zoompan=z='{zoom_expr}':x='{x_expr}':y='{y_expr}':d={total_frames}:s={target_w}x{target_h}:fps={fps}"
