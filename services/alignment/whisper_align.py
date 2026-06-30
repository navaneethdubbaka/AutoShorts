import os
import time
import logging
from pathlib import Path
from typing import List, Dict, Any
from faster_whisper import WhisperModel
from config import settings

logger = logging.getLogger("video_engine.alignment")

# Global singleton for the model to avoid reloading it on every request
_whisper_model = None

def get_whisper_model() -> WhisperModel:
    """Retrieve or initialize the shared WhisperModel instance."""
    global _whisper_model
    if _whisper_model is None:
        model_size = "small.en"  # small.en is fast and highly accurate on CPU
        logger.info(f"Loading WhisperModel ({model_size}) on CPU with INT8 quantization...")
        
        # CPU-specific speedups: INT8 quantization and float32 fallback
        # Under Windows/Linux, "cpu" compute_type "int8" is the fastest CPU path.
        try:
            _whisper_model = WhisperModel(
                model_size, 
                device="cpu", 
                compute_type="int8",
                cpu_threads=4  # standard VM thread allotment
            )
            logger.info("WhisperModel loaded successfully.")
        except Exception as e:
            logger.error(f"Failed to load WhisperModel: {e}")
            raise e
            
    return _whisper_model

def align_speech(audio_path: Path, reference_text: str = "") -> List[Dict[str, Any]]:
    """
    Transcribes audio and extracts word-level timestamps.
    Falls back to even-distribution mocking if the audio is empty/silent or Whisper fails.
    """
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Check if we should use mock alignment (e.g. if ELEVENLABS key is missing and we generated mock silence)
    # We can inspect the file size or name, or if reference_text is provided but Whisper returns nothing.
    # To be safe, if we catch any error or if the model fails to load, we fall back to mock alignment.
    try:
        model = get_whisper_model()
        logger.info(f"Aligning audio file: {audio_path.name}")
        
        # Transcribe with word timestamps enabled
        # We pass initial_prompt to bias transcription toward our reference script
        initial_prompt = reference_text if reference_text else None
        
        segments, info = model.transcribe(
            str(audio_path),
            word_timestamps=True,
            initial_prompt=initial_prompt,
            beam_size=5
        )
        
        words_list = []
        for segment in segments:
            if segment.words:
                for word in segment.words:
                    words_list.append({
                        "word": word.word.strip(),
                        "start": round(word.start, 3),
                        "end": round(word.end, 3),
                        "probability": round(word.probability, 3)
                    })
        
        if not words_list:
            logger.warning("Whisper returned zero words. Falling back to mock alignment.")
            return generate_mock_alignment(reference_text, audio_path)

        logger.info(f"Successfully aligned {len(words_list)} words using Whisper.")
        return words_list

    except Exception as e:
        logger.warning(f"Whisper alignment failed ({e}). Falling back to mock alignment.")
        return generate_mock_alignment(reference_text, audio_path)

def generate_mock_alignment(text: str, audio_path: Path) -> List[Dict[str, Any]]:
    """Generates evenly spaced word timestamps as a fallback."""
    logger.info("Generating mock word timestamps...")
    
    # Get audio duration using pydub
    from pydub import AudioSegment
    try:
        audio = AudioSegment.from_file(str(audio_path))
        duration_sec = len(audio) / 1000.0
    except Exception:
        duration_sec = 10.0  # default fallback
        
    words = text.split() if text else ["Demo", "video", "narration", "text"]
    word_count = len(words)
    
    if word_count == 0:
        return []
        
    # Space them out evenly across the duration
    word_duration = duration_sec / word_count
    words_list = []
    
    for i, word in enumerate(words):
        start = i * word_duration
        end = (i + 1) * word_duration
        words_list.append({
            "word": word,
            "start": round(start, 3),
            "end": round(end, 3),
            "probability": 1.0
        })
        
    return words_list
