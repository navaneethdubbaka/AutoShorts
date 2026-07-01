import os
import shutil
import logging
from pathlib import Path
from pydub import AudioSegment

from config import settings
from models.schemas import VideoRequest
from services.tts.elevenlabs_provider import ElevenLabsProvider
from services.alignment.whisper_align import align_speech
from services.assets.downloader import get_scene_asset
from services.captions.ass_builder import build_ass_file
from services.timeline.filtergraph_builder import build_ffmpeg_command
from services.renderer.ffmpeg_runner import run_ffmpeg
from services.storage.local_storage import LocalStorage

logger = logging.getLogger("video_engine.pipeline")

def run_pipeline(job_id: str, payload: dict) -> dict:
    """
    Executes the entire video rendering pipeline step-by-step.
    """
    logger.info(f"Running video pipeline for job {job_id}")
    
    # 1. Parse request payload
    request = VideoRequest(**payload)
    
    # Create job-specific temporary directory
    job_temp_dir = settings.temp_dir / job_id
    job_temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Instantiate providers
    tts_provider = ElevenLabsProvider()
    storage = LocalStorage()
    
    scene_wavs = []
    total_duration = 0.0
    
    try:
        # --- STEP 1: TTS Generation per Scene ---
        logger.info("--- Step 1: Synthesizing TTS narration per scene ---")
        
        current_time = 0.0
        for i, scene in enumerate(request.scenes):
            scene_duration = scene.end - scene.start
            
            # Skip TTS if scene has no narration text
            if not scene.narration.strip():
                # If no narration, generate silent wav for scene duration
                logger.info(f"Scene ID {scene.id} has empty narration. Generating silence.")
                silent_wav = job_temp_dir / f"scene_{i}_silence.wav"
                silence = AudioSegment.silent(duration=int(scene_duration * 1000), frame_rate=44100)
                silence = silence.set_channels(1).set_sample_width(2)
                silence.export(silent_wav, format="wav")
                scene_wavs.append(silent_wav)
                actual_duration = scene_duration
            else:
                scene_wav_path = job_temp_dir / f"scene_{i}_narration.wav"
                voice_id = request.voice or settings.elevenlabs_voice_id
                tts_provider.synthesize(
                    text=scene.narration,
                    voice_id=voice_id,
                    output_path=scene_wav_path
                )
                scene_wavs.append(scene_wav_path)
                
                # Measure actual duration of the generated audio file
                audio_segment = AudioSegment.from_wav(str(scene_wav_path))
                actual_duration = len(audio_segment) / 1000.0
                
            # Dynamically update scene timestamps to match the voice track
            scene.start = current_time
            scene.end = current_time + actual_duration
            logger.info(f"Scene ID {scene.id} adjusted: start={scene.start:.2f}s, end={scene.end:.2f}s (duration={actual_duration:.2f}s)")
            current_time = scene.end

        total_duration = current_time

        # Concatenate scene narration audio files to create the master voice track
        logger.info("Concatenating scene audio tracks into master voice narration...")
        master_voice_path = job_temp_dir / "voice_narration.wav"
        combined_audio = AudioSegment.empty()
        for wav_path in scene_wavs:
            combined_audio += AudioSegment.from_wav(str(wav_path))
            
        combined_audio.export(master_voice_path, format="wav")
        logger.info(f"Master voice narration generated: {master_voice_path}")

        # --- STEP 2: Speech Alignment ---
        logger.info("--- Step 2: Running speech-to-text alignment ---")
        # Combine all scene narrations into a single script for alignment bias
        full_script = " ".join([s.narration for s in request.scenes if s.narration.strip()])
        word_timestamps = align_speech(master_voice_path, full_script)

        # --- STEP 3: Stock Assets Retrieval ---
        logger.info("--- Step 3: Downloading stock assets ---")
        scene_assets = []
        scene_durations = []
        scene_effects = []
        scene_transitions = []
        
        orientation = "landscape" if request.resolution == "1920x1080" else "portrait"
        for i, scene in enumerate(request.scenes):
            scene_duration = scene.end - scene.start
            scene_durations.append(scene_duration)
            scene_effects.append(scene.effects or [])
            scene_transitions.append(scene.transition)
            
            # Fetch asset (video/image)
            asset_path = get_scene_asset(
                search_query=scene.search_query,
                asset_type=scene.asset_type,
                duration=scene_duration,
                scene_id=scene.id,
                job_id=job_id,
                orientation=orientation
            )
            scene_assets.append(asset_path)

        # --- STEP 3b: Validate Stock Assets (Fail Fast) ---
        logger.info("--- Step 3b: Validating downloaded assets ---")
        for i, scene in enumerate(request.scenes):
            asset_path = scene_assets[i]
            if not asset_path.exists():
                raise FileNotFoundError(f"Validation failed: Asset for Scene ID {scene.id} is missing at {asset_path}")
            if asset_path.stat().st_size == 0:
                raise ValueError(f"Validation failed: Asset file for Scene ID {scene.id} at {asset_path} is empty (0 bytes)")

        # --- STEP 4: Caption Generation (ASS subtitle file) ---
        logger.info("--- Step 4: Generating ASS captions file ---")
        subtitles_path = None
        if request.captions and word_timestamps:
            subtitles_path = job_temp_dir / "captions.ass"
            build_ass_file(word_timestamps, subtitles_path)

        # --- STEP 5: Background Music Resolution ---
        logger.info("--- Step 5: Resolving background music ---")
        resolved_music_path = None
        if request.background_music:
            # Check if it exists in music directory
            music_file = settings.music_dir / request.background_music
            if not music_file.exists() and not music_file.is_absolute():
                # fallback to base dir/music
                music_file = settings.base_dir / settings.music_dir / request.background_music
                
            if music_file.exists():
                resolved_music_path = music_file
                logger.info(f"Background music resolved: {resolved_music_path}")
            else:
                logger.warning(f"Background music file not found: {request.background_music}. Proceeding without music.")

        # --- STEP 6: Render (FFmpeg Complex Graph Execution) ---
        logger.info("--- Step 6: Rendering final video ---")
        temp_output_mp4 = job_temp_dir / f"{job_id}_render.mp4"
        
        # Build command
        ffmpeg_cmd = build_ffmpeg_command(
            voice_path=master_voice_path,
            scene_assets=scene_assets,
            scene_durations=scene_durations,
            scene_effects=scene_effects,
            scene_transitions=scene_transitions,
            output_path=temp_output_mp4,
            music_path=resolved_music_path,
            subtitles_path=subtitles_path,
            resolution=request.resolution,
            fps=request.fps
        )
        
        # Run render
        run_ffmpeg(ffmpeg_cmd)

        # --- STEP 7: Storage and Cleanup ---
        logger.info("--- Step 7: Saving output and cleaning up ---")
        output_filename = f"{job_id}.mp4"
        video_url = storage.save(temp_output_mp4, output_filename)
        
        logger.info(f"Video pipeline finished. Output URL: {video_url}")
        return {
            "video_url": video_url,
            "duration": total_duration
        }

    except Exception as e:
        logger.error(f"Pipeline failed for job {job_id}: {e}")
        raise e
        
    finally:
        # Cleanup temporary job directory to keep storage clean
        if job_temp_dir.exists():
            logger.info(f"Cleaning up temporary job directory: {job_temp_dir}")
            shutil.rmtree(job_temp_dir, ignore_errors=True)
