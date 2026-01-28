"""Shared models."""

import json
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from queue import Queue
from typing import TYPE_CHECKING, Dict, List, Optional, Set, Union

if TYPE_CHECKING:
    from pymicro_wakeword import MicroWakeWord
    from pyopen_wakeword import OpenWakeWord
    import pvporcupine

    from .entity import ESPHomeEntity, MediaPlayerEntity
    from .entity import ESPHomeEntity, MediaPlayerEntity, ThinkingSoundEntity
    from .mpv_player import MpvMediaPlayer
    from .satellite import VoiceSatelliteProtocol

_LOGGER = logging.getLogger(__name__)


class WakeWordType(str, Enum):
    MICRO_WAKE_WORD = "micro"
    OPEN_WAKE_WORD = "openWakeWord"
    PORCUPINE = "porcupine"


@dataclass
class AvailableWakeWord:
    id: str
    type: WakeWordType
    wake_word: str
    trained_languages: List[str]
    wake_word_path: Path

    def load(self, porcupine_access_key: Optional[str] = None) -> "Union[MicroWakeWord, OpenWakeWord, pvporcupine.Porcupine]":
        if self.type == WakeWordType.MICRO_WAKE_WORD:
            from pymicro_wakeword import MicroWakeWord

            return MicroWakeWord.from_config(config_path=self.wake_word_path)

        if self.type == WakeWordType.OPEN_WAKE_WORD:
            from pyopen_wakeword import OpenWakeWord

            oww_model = OpenWakeWord.from_model(model_path=self.wake_word_path)
            setattr(oww_model, "wake_word", self.wake_word)

            return oww_model

        if self.type == WakeWordType.PORCUPINE:
            import pvporcupine

            if not porcupine_access_key:
                raise ValueError(
                    f"Porcupine access key required for model {self.id}. "
                    "Please provide --porcupine-access-key argument."
                )

            porcupine = pvporcupine.create(
                access_key=porcupine_access_key,
                keyword_paths=[str(self.wake_word_path)]
            )

            # Add metadata for consistency with other engines
            setattr(porcupine, "id", self.id)
            setattr(porcupine, "wake_word", self.wake_word)

            return porcupine

        raise ValueError(f"Unexpected wake word type: {self.type}")


@dataclass
class Preferences:
    active_wake_words: List[str] = field(default_factory=list)
    thinking_sound: int = 0  # 0 = disabled, 1 = enabled

@dataclass
class ServerState:
    name: str
    mac_address: str
    audio_queue: "Queue[Optional[bytes]]"
    entities: "List[ESPHomeEntity]"
    available_wake_words: "Dict[str, AvailableWakeWord]"
    wake_words: "Dict[str, Union[MicroWakeWord, OpenWakeWord]]"
    active_wake_words: Set[str]
    stop_word: "MicroWakeWord"
    music_player: "MpvMediaPlayer"
    tts_player: "MpvMediaPlayer"
    wakeup_sound: str
    processing_sound: str
    timer_finished_sound: str
    preferences: Preferences
    preferences_path: Path
    download_dir: Path

    porcupine_access_key: Optional[str] = None
    media_player_entity: "Optional[MediaPlayerEntity]" = None
    satellite: "Optional[VoiceSatelliteProtocol]" = None
    thinking_sound_entity: "Optional[ThinkingSoundEntity]" = None
    wake_words_changed: bool = False
    refractory_seconds: float = 2.0
    thinking_sound_enabled: bool = False

    def save_preferences(self) -> None:
        """Save preferences as JSON."""
        _LOGGER.debug("Saving preferences: %s", self.preferences_path)
        self.preferences_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.preferences_path, "w", encoding="utf-8") as preferences_file:
            json.dump(
                asdict(self.preferences), preferences_file, ensure_ascii=False, indent=4
            )
