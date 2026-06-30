import os
import hashlib
import shutil
import logging
import requests
from pathlib import Path
from pydub import AudioSegment
from config import settings
from services.tts.base import TTSProvider

logger = logging.getLogger("video_engine.tts")

class ElevenLabsProvider(TTSProvider):
    # Class-level index to persist the current active key across instances/scenes/threads
    _current_key_idx = 0

    def __init__(self):
        # Retrieve either the list of keys (comma-separated) or fallback to single key
        raw_keys = settings.elevenlabs_api_keys or settings.elevenlabs_api_key
        if raw_keys:
            self.api_keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
        else:
            self.api_keys = []
            
        self.cache_dir = settings.temp_dir / "tts_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initialized ElevenLabsProvider with {len(self.api_keys)} API key(s).")

    def _get_cache_path(self, text: str, voice_id: str) -> Path:
        """Generate a stable cache filename based on text and voice ID."""
        hash_input = f"{text}|||{voice_id}"
        hash_digest = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{hash_digest}.wav"

    def synthesize(self, text: str, voice_id: str, output_path: Path) -> Path:
        """
        Synthesizes text into speech. Loops through configured ElevenLabs API keys 
        and rotates to the next key on error (401, 429, connection timeouts, etc.).
        """
        # Ensure parent directory of output_path exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Check Cache first
        cache_file = self._get_cache_path(text, voice_id)
        if cache_file.exists():
            logger.info(f"Using cached TTS audio for: '{text[:30]}...'")
            shutil.copy(cache_file, output_path)
            return output_path

        # If no API keys are configured, generate a mock silent WAV using pydub
        if not self.api_keys:
            logger.warning(f"No ElevenLabs API keys configured. Generating mock silent audio for: '{text[:30]}...'")
            return self._generate_mock_audio(text, output_path, cache_file)

        # Loop through keys starting from the current index
        num_keys = len(self.api_keys)
        last_exception = None

        for attempt in range(num_keys):
            # Calculate current key index using modulo
            idx = ElevenLabsProvider._current_key_idx % num_keys
            api_key = self.api_keys[idx]
            
            logger.info(f"Attempting TTS synthesis using ElevenLabs API key at index {idx} (attempt {attempt + 1}/{num_keys})...")
            
            try:
                # Call the real ElevenLabs API
                self._call_api_with_key(api_key, text, voice_id, output_path, cache_file)
                # If it succeeds, return the output path
                return output_path
                
            except Exception as e:
                last_exception = e
                logger.warning(f"ElevenLabs API key at index {idx} failed: {e}. Rotating to next key.")
                # Rotate index to the next key
                ElevenLabsProvider._current_key_idx += 1

        # If all keys failed
        logger.error(f"All {num_keys} ElevenLabs API keys failed. Last error: {last_exception}")
        raise RuntimeError(f"All ElevenLabs API keys failed or exhausted. Last error: {last_exception}")

    def _call_api_with_key(self, api_key: str, text: str, voice_id: str, output_path: Path, cache_file: Path) -> None:
        """Helper to invoke ElevenLabs API with a specific key."""
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        headers = {
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
            "xi-api-key": api_key
        }
        
        data = {
            "text": text,
            "model_id": "eleven_flash_v2_5",
            "voice_settings": {
                "stability": 0.5,
                "similarity_boost": 0.75
            }
        }

        params = {
            "output_format": "mp3_44100_128"
        }

        response = requests.post(url, json=data, headers=headers, params=params, stream=True, timeout=15)
        
        if response.status_code == 429:
            raise RuntimeError("Rate limit or quota exceeded (429)")
        elif response.status_code == 401:
            raise RuntimeError("Unauthorized (401). Invalid API key")
        elif response.status_code != 200:
            raise RuntimeError(f"API Error {response.status_code}: {response.text}")

        # Stream download file
        temp_mp3 = settings.temp_dir / f"temp_tts_{os.getpid()}.mp3"
        try:
            with open(temp_mp3, "wb") as f:
                for chunk in response.iter_content(chunk_size=4096):
                    if chunk:
                        f.write(chunk)
            
            # Convert MP3 to WAV using pydub
            logger.info("Converting ElevenLabs MP3 response to WAV...")
            sound = AudioSegment.from_mp3(str(temp_mp3))
            sound = sound.set_frame_rate(44100).set_channels(1).set_sample_width(2)
            sound.export(output_path, format="wav")
            
            # Cache the generated WAV
            shutil.copy(output_path, cache_file)
            logger.info(f"TTS synthesis completed and cached at {cache_file.name}")
            
        finally:
            if temp_mp3.exists():
                os.remove(temp_mp3)

    def _generate_mock_audio(self, text: str, output_path: Path, cache_file: Path) -> Path:
        """Helper to generate silent WAV file when no keys are available."""
        word_count = len(text.split())
        duration_sec = max(2.0, word_count / 2.5)
        duration_ms = int(duration_sec * 1000)
        
        silent_audio = AudioSegment.silent(duration=duration_ms, frame_rate=44100)
        silent_audio = silent_audio.set_channels(1).set_sample_width(2)
        silent_audio.export(output_path, format="wav")
        
        # Cache the mock
        shutil.copy(output_path, cache_file)
        return output_path
