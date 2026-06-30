from abc import ABC, abstractmethod
from pathlib import Path

class StorageBackend(ABC):
    @abstractmethod
    def save(self, source_path: Path, filename: str) -> str:
        """
        Saves a file to the storage backend.
        
        :param source_path: Path to the local file to save.
        :param filename: The destination filename.
        :return: A URL or reference string to retrieve the file.
        """
        pass
