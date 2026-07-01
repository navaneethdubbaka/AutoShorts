from abc import ABC, abstractmethod
from pathlib import Path

class TTSProvider(ABC):
    @abstractmethod
    def synthesize(self, text: str, voice_id: str, output_path: Path) -> Path:
        """
        Synthesizes text into speech and saves it as a WAV file.
        
        :param text: The text content to speak.
        :param voice_id: The ElevenLabs or provider-specific voice ID/name.
        :param output_path: The file path where the output WAV should be saved.
        :return: Path to the generated WAV file.
        """
        pass
