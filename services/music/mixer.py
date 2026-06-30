import logging
from typing import Optional

logger = logging.getLogger("video_engine.music.mixer")

def get_audio_mix_filters(
    voice_label: str = "a_voice", 
    music_label: str = "a_music", 
    has_music: bool = True,
    music_volume: float = 0.2
) -> str:
    """
    Returns the FFmpeg audio filter_complex string.
    Ducks the background music under the voice narration track and normalizes final loudness.
    """
    if not has_music:
        # No background music: just normalize the narration track
        logger.info("Building audio filter graph: Narration only (no background music)")
        return f"[{voice_label}]loudnorm[a_out]"

    logger.info("Building audio filter graph: Narration + sidechain ducked background music")
    
    # 1. Adjust music starting volume
    # 2. Apply sidechaincompress: compresses music when voice is active
    #    - threshold: compressor threshold (lower means more compression/quieter music during speech)
    #    - ratio: compression ratio
    #    - attack: response speed in ms
    #    - release: recovery speed in ms
    # 3. Mix both streams (duration=first means stop when narration ends)
    # 4. Apply loudnorm to normalize final mixed output to professional loudness standards
    filters = (
        f"[{music_label}]volume={music_volume:.2f}[music_vol];"
        f"[music_vol][voice_label]sidechaincompress=threshold=0.15:ratio=4:attack=50:release=300[ducked_music];"
        f"[ducked_music][voice_label]amix=inputs=2:duration=first:dropout_transition=2[mixed_audio];"
        f"[mixed_audio]loudnorm[a_out]"
    )
    return filters
