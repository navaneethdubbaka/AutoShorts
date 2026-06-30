import os
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from config import settings
from services.effects.ffmpeg_filters import get_scale_and_crop_filter, get_fade_filters, get_ken_burns_filter
from services.music.mixer import get_audio_mix_filters

logger = logging.getLogger("video_engine.timeline.builder")

def format_ass_path_for_ffmpeg(path: Path) -> str:
    """
    Formats the ASS file path to be safe for FFmpeg's ass filter.
    Uses a relative path if possible to avoid colons (e.g. C:) which break FFmpeg options parsing.
    """
    try:
        # Resolve absolute paths and compute path relative to the current working directory
        cwd = Path.cwd().resolve()
        abs_path = path.resolve()
        rel_path = abs_path.relative_to(cwd)
        path_str = str(rel_path).replace("\\", "/")
    except ValueError:
        # Fallback to absolute path with escaped colon if on a different drive
        path_str = str(path.resolve()).replace("\\", "/")
        path_str = path_str.replace(":", "\\:")
        
    # Escape single quotes inside single-quoted FFmpeg filter strings
    path_str = path_str.replace("'", "'\\''")
    return path_str

def build_ffmpeg_command(
    voice_path: Path,
    scene_assets: List[Path],
    scene_durations: List[float],
    scene_effects: List[List[str]],
    scene_transitions: List[Optional[str]],
    output_path: Path,
    music_path: Optional[Path] = None,
    subtitles_path: Optional[Path] = None,
    resolution: str = "1080x1920",
    fps: int = 60
) -> List[str]:
    """
    Assembles a single-pass FFmpeg command using a complex filter graph.
    """
    # 1. Parse target resolution
    try:
        width, height = map(int, resolution.lower().split("x"))
    except ValueError:
        logger.warning(f"Invalid resolution '{resolution}', falling back to 1080x1920.")
        width, height = 1080, 1920

    # 2. Build inputs
    # Input 0: Voice narration (always index 0)
    inputs = ["-i", str(voice_path.resolve())]
    
    # Input 1: Background music (optional, index 1)
    has_music = music_path is not None and music_path.exists()
    if has_music:
        # Loop background music infinitely so we can trim it to match narration
        inputs += ["-stream_loop", "-1", "-i", str(music_path.resolve())]
        
    scene_start_index = 2 if has_music else 1
    
    # Add scene assets as inputs
    for asset_path in scene_assets:
        suffix = asset_path.suffix.lower()
        if suffix in [".jpg", ".jpeg", ".png"]:
            # Static image input: loop it
            inputs += ["-loop", "1", "-i", str(asset_path.resolve())]
        else:
            # Video input: loop infinitely so we can trim to exact scene duration
            inputs += ["-stream_loop", "-1", "-i", str(asset_path.resolve())]

    # 3. Build video filtergraph segments for each scene
    filter_complex_parts = []
    scene_v_labels = []
    
    for i, asset_path in enumerate(scene_assets):
        input_idx = scene_start_index + i
        duration = scene_durations[i]
        effects = scene_effects[i] if i < len(scene_effects) else []
        transition = scene_transitions[i] if i < len(scene_transitions) else None
        
        # Base input label for the scene
        curr_label = f"[{input_idx}:v]"
        
        # Chain filters: scale -> crop -> effects -> trim -> setpts
        filters = []
        
        # Scale and crop to fit vertical resolution
        filters.append(get_scale_and_crop_filter(width, height))
        
        # Apply Ken Burns zoompan effect if requested
        if "zoom" in effects or "zoompan" in effects or "ken_burns" in effects:
            filters.append(get_ken_burns_filter(duration, fps, width, height))
            
        # Trim to exact scene duration and reset presentation timestamps
        filters.append(f"trim=duration={duration:.2f},setpts=PTS-STARTPTS")
        
        # Apply fades for transition if requested (or default to subtle fade)
        if transition == "fade" or transition == "fade_in_out":
            filters.append(get_fade_filters(duration, 0.4))
        elif transition == "slow_fade":
            filters.append(get_fade_filters(duration, 0.8))
            
        # Compile filters for this scene
        scene_label = f"[v_scene_{i}]"
        filter_complex_parts.append(f"{curr_label}{','.join(filters)}{scene_label}")
        scene_v_labels.append(scene_label)

    # 4. Concatenate all scene videos
    concat_input_labels = "".join(scene_v_labels)
    num_scenes = len(scene_assets)
    concat_filter = f"{concat_input_labels}concat=n={num_scenes}:v=1:a=0[v_concat]"
    filter_complex_parts.append(concat_filter)

    # 5. Burn in subtitles if provided
    if subtitles_path and subtitles_path.exists():
        escaped_ass_path = format_ass_path_for_ffmpeg(subtitles_path)
        subtitle_filter = f"[v_concat]ass=filename='{escaped_ass_path}'[v_out]"
        filter_complex_parts.append(subtitle_filter)
    else:
        filter_complex_parts.append("[v_concat]null[v_out]")

    # 6. Mix and duck Audio
    voice_audio_label = "0:a"
    music_audio_label = "1:a" if has_music else "none"
    audio_mix_filter = get_audio_mix_filters(
        voice_label=voice_audio_label,
        music_label=music_audio_label,
        has_music=has_music,
        music_volume=0.15
    )
    filter_complex_parts.append(audio_mix_filter)

    # 7. Assemble FFmpeg CLI Command
    filter_complex_str = ";".join(filter_complex_parts)
    
    # We use libx264 veryfast preset as defined in the roadmap
    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex_str,
        "-map", "[v_out]",
        "-map", "[a_out]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        "-threads", "0",
        str(output_path.resolve())
    ]
    
    return cmd
