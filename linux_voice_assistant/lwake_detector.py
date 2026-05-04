"""
lwake Wake Word Detector Wrapper for LVA
Speaker-dependent wake word detection using DTW + embeddings
"""
import logging
import numpy as np
import struct
from pathlib import Path
from typing import Optional

_LOGGER = logging.getLogger(__name__)

class LwakeDetector:
    """Wrapper for lwake wake word detection compatible with LVA."""

    def __init__(self, reference_dir: str, threshold: float = 0.4,
                 method: str = "embedding", buffer_size: float = 2.0,
                 slide_size: float = 0.25):
        """
        Initialize lwake detector.

        Args:
            reference_dir: Directory with .wav reference samples
            threshold: DTW distance threshold (lower = stricter)
            method: Feature extraction method ("mfcc" or "embedding")
            buffer_size: Audio buffer size in seconds
            slide_size: How often to check for wake word in seconds
        """
        self.reference_dir = Path(reference_dir)
        self.threshold = threshold
        self.method = method
        self.sample_rate = 16000

        # Audio buffering
        self.buffer_size_samples = int(buffer_size * self.sample_rate)
        self.slide_size_samples = int(slide_size * self.sample_rate)
        self.audio_buffer = np.zeros(self.buffer_size_samples, dtype=np.float32)
        self.bytes_since_last_check = 0
        self.total_chunks_received = 0
        self.last_detection_chunk = -1000

        # Load reference samples
        self.support_set = []
        self._load_support_set()

        # Wake word ID
        self.id = self.reference_dir.name
        self.wake_word = self.id.replace("_", " ").replace("-", " ").title()

        _LOGGER.info(f"[lwake] Initialized: buffer={buffer_size}s slide={slide_size}s threshold={threshold}")

    def _load_support_set(self):
        """Load all reference .wav files and extract features."""
        from lwake.features import extract_mfcc_features, extract_embedding_features

        _LOGGER.info(f"[lwake] Loading support set from {self.reference_dir}")

        if not self.reference_dir.exists():
            _LOGGER.error(f"[lwake] Reference directory not found: {self.reference_dir}")
            return

        for wav_file in sorted(self.reference_dir.glob("*.wav")):
            try:
                if self.method == "mfcc":
                    features = extract_mfcc_features(path=str(wav_file))
                else:
                    features = extract_embedding_features(path=str(wav_file))

                if features is not None:
                    self.support_set.append((wav_file.name, features))
                    _LOGGER.debug(f"[lwake] Loaded {wav_file.name}: shape {features.shape}")
            except Exception as e:
                _LOGGER.error(f"[lwake] Error loading {wav_file.name}: {e}")

        _LOGGER.info(f"[lwake] Loaded {len(self.support_set)} reference samples")

        if not self.support_set:
            _LOGGER.error("[lwake] No valid reference samples found!")

    def process_streaming(self, audio_bytes: bytes) -> bool:
        """
        Process streaming audio bytes and detect wake word.

        Args:
            audio_bytes: Raw audio bytes (16kHz, 16-bit, mono)

        Returns:
            True if wake word detected, False otherwise
        """
        if not self.support_set:
            return False

        self.total_chunks_received += 1

        # Convert bytes to float32 audio samples
        num_samples = len(audio_bytes) // 2
        audio_chunk = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        # Add to rolling buffer
        self.audio_buffer = np.roll(self.audio_buffer, -len(audio_chunk))
        self.audio_buffer[-len(audio_chunk):] = audio_chunk

        # Track bytes and only check every slide_size samples
        self.bytes_since_last_check += len(audio_bytes)
        bytes_per_slide = self.slide_size_samples * 2

        if self.bytes_since_last_check < bytes_per_slide:
            return False

        self.bytes_since_last_check = 0

        # Refractory period
        chunks_since_detection = self.total_chunks_received - self.last_detection_chunk
        if chunks_since_detection < 20:
            return False

        # Check if buffer has enough non-zero audio
        audio_energy = np.sum(np.abs(self.audio_buffer))
        if audio_energy < 0.1:
            return False

        # Extract features from current buffer
        try:
            from lwake.features import extract_mfcc_features, extract_embedding_features, dtw_cosine_normalized_distance

            if self.method == "mfcc":
                features = extract_mfcc_features(y=self.audio_buffer, sample_rate=self.sample_rate)
            else:
                features = extract_embedding_features(y=self.audio_buffer, sample_rate=self.sample_rate)

            if features is None:
                _LOGGER.debug("[lwake] Feature extraction returned None")
                return False

            # Compare to all reference samples
            min_distance = float('inf')
            best_match = None

            for filename, ref_features in self.support_set:
                distance = dtw_cosine_normalized_distance(features, ref_features)

                if distance < min_distance:
                    min_distance = distance
                    best_match = filename

                # Debug: log all comparisons every 100 chunks
                if self.total_chunks_received % 100 == 0:
                    _LOGGER.debug(f"[lwake] Chunk {self.total_chunks_received}: {filename} distance={distance:.4f}")

            # Check best match against threshold
            if min_distance < self.threshold:
                _LOGGER.info(f"[lwake] {self.wake_word}: distance={min_distance:.4f} threshold={self.threshold} match={best_match} DETECTED")

                # Mark detection time to prevent rapid re-triggers
                self.last_detection_chunk = self.total_chunks_received

                # Clear buffer to avoid duplicate detections
                self.audio_buffer = np.zeros(self.buffer_size_samples, dtype=np.float32)
                self.bytes_since_last_check = 0

                return True

        except Exception as e:
            _LOGGER.error(f"[lwake] Detection error: {e}", exc_info=True)

        return False

    @classmethod
    def from_config(cls, config_path: Path) -> "LwakeDetector":
        """
        Load lwake detector from JSON config file.
        """
        import json

        with open(config_path) as f:
            config = json.load(f)

        reference_dir = config.get("reference_dir")
        if not reference_dir:
            raise ValueError("Config must specify 'reference_dir'")

        threshold = config.get("threshold", 0.4)
        method = config.get("method", "embedding")

        return cls(reference_dir=reference_dir, threshold=threshold, method=method)
