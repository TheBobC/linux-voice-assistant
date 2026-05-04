"""Compatibility wrapper for original openwakeword to work with LVA code."""
import logging
import numpy as np
from openwakeword.model import Model as OriginalModel

_LOGGER = logging.getLogger(__name__)


class OpenWakeWordFeatures:
    """Mimics pyopen-wakeword features but just buffers audio."""

    @classmethod
    def from_builtin(cls):
        return cls()

    def process_streaming(self, audio_bytes):
        """Convert audio bytes to int16 array and yield in chunks."""
        # Convert bytes to int16 array
        audio_array = np.frombuffer(audio_bytes, dtype=np.int16)
        # Yield the full array (Model.predict will handle chunking)
        yield audio_array


class OpenWakeWord:
    """Wrapper for openwakeword.Model that mimics pyopen-wakeword API."""

    def __init__(self, model_path):
        _LOGGER.info(f"Loading OpenWakeWord model from: {model_path}")
        self.model = OriginalModel(wakeword_model_paths=[str(model_path)])
        self.wake_word = ""  # Will be set by caller
        self.id = ""  # Will be set by caller
        self._buffer = np.array([], dtype=np.int16)
        self.CHUNK_SIZE = 1280  # 80ms at 16kHz
        _LOGGER.info(f"OpenWakeWord model loaded successfully")

    def process_streaming(self, audio_array):
        """Process audio and yield probabilities."""
        # Add to buffer
        self._buffer = np.concatenate([self._buffer, audio_array])

        # Process complete chunks
        while len(self._buffer) >= self.CHUNK_SIZE:
            chunk = self._buffer[:self.CHUNK_SIZE]
            self._buffer = self._buffer[self.CHUNK_SIZE:]

            # Get prediction
            predictions = self.model.predict(chunk)

            # Yield the first (and likely only) model's score
            for model_name, score in predictions.items():
                if score > 0.3:  # Log high scores for debugging
                    _LOGGER.info(f"[WAKE] {self.wake_word}: prob={score:.3f} cutoff=0.40 {'TRIGGERED' if score > 0.5 else 'below-threshold'}")
                yield score
                break  # Only yield first model
