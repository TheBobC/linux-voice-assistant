"""Voice satellite protocol - Modified for direct orchestrator integration with keep-awake."""

import base64
import hashlib
import logging
import posixpath
import shutil
import tempfile
import time
import threading
from collections.abc import Iterable
from typing import Dict, Optional, Set, Union
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

import requests

# pylint: disable=no-name-in-module
from aioesphomeapi.api_pb2 import (  # type: ignore[attr-defined]
    DeviceInfoRequest,
    DeviceInfoResponse,
    ListEntitiesDoneResponse,
    ListEntitiesRequest,
    MediaPlayerCommandRequest,
    SubscribeHomeAssistantStatesRequest,
    VoiceAssistantAnnounceFinished,
    VoiceAssistantAnnounceRequest,
    VoiceAssistantAudio,
    VoiceAssistantConfigurationRequest,
    VoiceAssistantConfigurationResponse,
    VoiceAssistantEventResponse,
    VoiceAssistantExternalWakeWord,
    VoiceAssistantRequest,
    VoiceAssistantSetConfiguration,
    VoiceAssistantTimerEventResponse,
    VoiceAssistantWakeWord,
)
from aioesphomeapi.model import (
    VoiceAssistantEventType,
    VoiceAssistantFeature,
    VoiceAssistantTimerEventType,
)
from google.protobuf import message
from pymicro_wakeword import MicroWakeWord
from pyopen_wakeword import OpenWakeWord
import pvporcupine

from .api_server import APIServer
from .entity import MediaPlayerEntity
from .models import AvailableWakeWord, ServerState, WakeWordType
from .util import call_all

_LOGGER = logging.getLogger(__name__)

# =============================================================================
# ORCHESTRATOR CONFIGURATION
# =============================================================================

ORCHESTRATOR_URL = "https://10.0.0.9:5000"
SPEAKER_ID_URL = "http://localhost:5001"
SATELLITE_NAME = "Office"  # This satellite's name - CHANGE FOR EACH SATELLITE

# Default keep-awake timeout (can be overridden by orchestrator response)
DEFAULT_KEEPAWAKE_TIMEOUT = 8  # seconds


def speaker_id_start():
    """Tell speaker-id to start capturing (wake word fired)."""
    try:
        requests.post(f"{SPEAKER_ID_URL}/start", timeout=1)
        _LOGGER.debug("Speaker-ID: start capturing")
    except Exception as e:
        _LOGGER.warning(f"Speaker-ID start error: {e}")


def speaker_id_stop() -> str:
    """Tell speaker-id to stop and identify. Returns speaker name."""
    try:
        response = requests.post(f"{SPEAKER_ID_URL}/stop", timeout=5)
        if response.status_code == 200:
            data = response.json()
            speaker = data.get("speaker", "unknown")
            _LOGGER.info(f"Speaker-ID result: {speaker}")
            return speaker
    except Exception as e:
        _LOGGER.warning(f"Speaker-ID stop error: {e}")
    return "unknown"


def call_orchestrator(text: str, speaker: str, conversation_id: Optional[str] = None) -> Optional[Dict]:
    """Call Jarvis orchestrator and get response with audio."""
    try:
        _LOGGER.info(f"[STT→ORCH] Transcript: '{text}' | Speaker: {speaker} | Satellite: {SATELLITE_NAME} | Conv: {conversation_id or 'new'}")
        payload = {
            "text": text,
            "speaker": speaker,
            "satellite": SATELLITE_NAME
        }
        if conversation_id:
            payload["conversation_id"] = conversation_id

        response = requests.post(
            f"{ORCHESTRATOR_URL}/api/voice",
            json=payload,
            timeout=30,
            verify=False  # Jarvis uses self-signed certificate
        )
        if response.status_code == 200:
            result = response.json()
            audio_len = len(result.get("audio", ""))
            response_text = result.get("response", "")
            _LOGGER.info(f"[ORCH→SAT] Response: '{response_text[:100]}{'...' if len(response_text) > 100 else ''}' | Audio: {audio_len} bytes")
            return result
        else:
            _LOGGER.error(f"Orchestrator error: {response.status_code}")
    except Exception as e:
        _LOGGER.error(f"Orchestrator call failed: {e}")
    return None


# =============================================================================
# SATELLITE PROTOCOL
# =============================================================================

class VoiceSatelliteProtocol(APIServer):

    def __init__(self, state: ServerState) -> None:
        super().__init__(state.name)

        self.state = state
        self.state.satellite = self

        if self.state.media_player_entity is None:
            self.state.media_player_entity = MediaPlayerEntity(
                server=self,
                key=len(state.entities),
                name="Media Player",
                object_id="linux_voice_assistant_media_player",
                music_player=state.music_player,
                announce_player=state.tts_player,
            )
            self.state.entities.append(self.state.media_player_entity)

        self._is_streaming_audio = False
        self._tts_url: Optional[str] = None
        self._tts_played = False
        self._continue_conversation = False
        self._conversation_id: Optional[str] = None  # Track conversation for multi-turn
        self._timer_finished = False
        self._external_wake_words: Dict[str, VoiceAssistantExternalWakeWord] = {}

        # Flag to skip HA's TTS when we handle it ourselves
        self._handled_by_orchestrator = False

        # === KEEP-AWAKE STATE ===
        self._keepawake_timeout = DEFAULT_KEEPAWAKE_TIMEOUT
        self._keepawake_timer: Optional[threading.Timer] = None
        self._in_keepawake_mode = False
        self._close_conversation = False  # Set by orchestrator when user says goodbye
        self._speech_detected_in_window = False  # Track if user spoke during keepawake

        # Preload random greeting
        self._greetings_dir = "/home/lva/greetings"
        self._next_greeting = None
        self._preload_greeting()

    def _preload_greeting(self):
        """Preload a random greeting for next wake word."""
        import random
        import os
        try:
            greetings = [f for f in os.listdir(self._greetings_dir) if f.endswith('.wav')]
            if greetings:
                self._next_greeting = os.path.join(self._greetings_dir, random.choice(greetings))
            else:
                self._next_greeting = self.state.wakeup_sound
        except Exception as e:
            _LOGGER.error(f"Error loading greeting: {e}")
            self._next_greeting = self.state.wakeup_sound

    def _cancel_keepawake_timer(self):
        """Cancel any active keep-awake timer."""
        if self._keepawake_timer:
            self._keepawake_timer.cancel()
            self._keepawake_timer = None
            _LOGGER.debug("Keep-awake timer cancelled")

    def _start_keepawake_timer(self):
        """Start the keep-awake timeout timer."""
        self._cancel_keepawake_timer()
        
        def timeout_handler():
            _LOGGER.info(f"Keep-awake timeout ({self._keepawake_timeout}s) - returning to wake word mode")
            self._in_keepawake_mode = False
            self._is_streaming_audio = False
            self._continue_conversation = False
            self._conversation_id = None  # Clear conversation on timeout
            self.unduck()
            # No need to send stop - just stop streaming audio
        
        self._keepawake_timer = threading.Timer(self._keepawake_timeout, timeout_handler)
        self._keepawake_timer.start()
        _LOGGER.debug(f"Keep-awake timer started: {self._keepawake_timeout}s")

    def handle_voice_event(
        self, event_type: VoiceAssistantEventType, data: Dict[str, str]
    ) -> None:
        _LOGGER.debug("Voice event: type=%s, data=%s", event_type.name, data)

        if event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_START:
            self._tts_url = data.get("url")
            self._tts_played = False

            # Don't clear conversation state if we're in keep-awake mode
            if not self._continue_conversation:
                _LOGGER.info(f"[DEBUG] RUN_START - clearing conv_id (was: {self._conversation_id})")
                self._conversation_id = None  # Clear conversation on new wake word
                self._continue_conversation = False
            else:
                _LOGGER.info(f"[DEBUG] RUN_START - KEEPING conv_id (keep-awake mode): {self._conversation_id}")

            self._handled_by_orchestrator = False
            self._close_conversation = False
            self._speech_detected_in_window = False
            
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_END:
            # === INTERCEPT: Call orchestrator directly ===
            self._is_streaming_audio = False
            self._cancel_keepawake_timer()  # Cancel timer - we got speech
            
            # Extract transcript
            transcript = data.get("text", "")
            if not transcript:
                _LOGGER.warning("No transcript in STT_END event")
                return
            
            _LOGGER.info(f"Transcript: {transcript}")
            self._speech_detected_in_window = True
            
            # Stop speaker-id and get identification result
            speaker = speaker_id_stop()

            # Call orchestrator (pass conversation_id if we're in a multi-turn conversation)
            _LOGGER.info(f"[DEBUG] Calling orchestrator with conv_id: {self._conversation_id}")
            result = call_orchestrator(transcript, speaker, self._conversation_id)

            if result and result.get("success"):
                response_text = result.get("response", "")
                audio_b64 = result.get("audio", "")

                # === READ KEEP-AWAKE FLAGS FROM ORCHESTRATOR ===
                self._continue_conversation = result.get("continue_conversation", False)
                self._close_conversation = result.get("close_conversation", False)
                self._keepawake_timeout = result.get("timeout", DEFAULT_KEEPAWAKE_TIMEOUT)
                received_conv_id = result.get("conversation_id")
                _LOGGER.info(f"[DEBUG] Received conv_id from orchestrator: {received_conv_id}")
                self._conversation_id = received_conv_id  # Track for multi-turn
                smart_continue = result.get("smart_continue", False)

                _LOGGER.info(f"Orchestrator response: '{response_text[:50]}...' | continue={self._continue_conversation} | close={self._close_conversation} | timeout={self._keepawake_timeout}s | smart={smart_continue}")

                # If close phrase detected, don't continue
                if self._close_conversation:
                    _LOGGER.info("Close phrase detected - ending conversation")
                    self._continue_conversation = False
                    self._conversation_id = None  # Clear conversation
                
                if audio_b64:
                    self._play_orchestrator_audio(audio_b64)
                    self._handled_by_orchestrator = True
                elif response_text:
                    # No audio but we have text - might be a quick close response
                    # Just finish up
                    self._in_keepawake_mode = False
                    self.unduck()
                else:
                    _LOGGER.warning("No audio in orchestrator response")
            else:
                _LOGGER.error("Orchestrator call failed, falling back to HA")
                
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_STT_VAD_END:
            self._is_streaming_audio = False
            
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_PROGRESS:
            if not self._handled_by_orchestrator:
                if data.get("tts_start_streaming") == "1":
                    self.play_tts()
                    
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_INTENT_END:
            if data.get("continue_conversation") == "1":
                self._continue_conversation = True
                
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_TTS_END:
            if self._handled_by_orchestrator:
                _LOGGER.debug("Skipping HA TTS - handled by orchestrator")
            else:
                self._tts_url = data.get("url")
                self.play_tts()
                
        elif event_type == VoiceAssistantEventType.VOICE_ASSISTANT_RUN_END:
            self._is_streaming_audio = False
            if not self._tts_played and not self._handled_by_orchestrator:
                self._tts_finished()
            self._tts_played = False

    def _play_orchestrator_audio(self, audio_b64: str) -> None:
        """Play audio from orchestrator response."""
        try:
            _LOGGER.info(f"[AUDIO] Decoding base64 audio: {len(audio_b64)} chars")
            audio_bytes = base64.b64decode(audio_b64)
            _LOGGER.info(f"[AUDIO] Playing WAV audio: {len(audio_bytes)} bytes")
            
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                import wave
                with wave.open(f.name, 'wb') as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(22050)
                    wav.writeframes(audio_bytes)
                
                self.duck()
                self.state.active_wake_words.add(self.state.stop_word.id)
                self.state.tts_player.play(f.name, done_callback=self._orchestrator_audio_finished)
                self._tts_played = True
                
        except Exception as e:
            _LOGGER.error(f"[AUDIO] PLAYBACK FAILED: {e}")
            import traceback
            traceback.print_exc()

    def _orchestrator_audio_finished(self) -> None:
        """Called when orchestrator audio finishes playing."""
        _LOGGER.info("[AUDIO] Playback completed successfully")
        self.state.active_wake_words.discard(self.state.stop_word.id)
        self.send_messages([VoiceAssistantAnnounceFinished()])
        
        # === KEEP-AWAKE LOGIC ===
        if self._close_conversation:
            # User said goodbye - end immediately
            _LOGGER.info("Conversation closed by user")
            self._in_keepawake_mode = False
            self._continue_conversation = False
            self.unduck()
        elif self._continue_conversation:
            # Start listening again with timeout
            _LOGGER.info(f"Keep-awake: Listening for {self._keepawake_timeout}s")
            self._in_keepawake_mode = True
            self.send_messages([VoiceAssistantRequest(start=True)])
            self._is_streaming_audio = True
            
            # Start speaker-id capture for the potential follow-up
            speaker_id_start()
            
            # Start timeout timer - will fire if no speech detected
            self._start_keepawake_timer()
        else:
            self._in_keepawake_mode = False
            self.unduck()

    def handle_timer_event(
        self,
        event_type: VoiceAssistantTimerEventType,
        msg: VoiceAssistantTimerEventResponse,
    ) -> None:
        _LOGGER.debug("Timer event: type=%s", event_type.name)
        if event_type == VoiceAssistantTimerEventType.VOICE_ASSISTANT_TIMER_FINISHED:
            if not self._timer_finished:
                self.state.active_wake_words.add(self.state.stop_word.id)
                self._timer_finished = True
                self.duck()
                self._play_timer_finished()

    def handle_message(self, msg: message.Message) -> Iterable[message.Message]:
        if isinstance(msg, VoiceAssistantEventResponse):
            data: Dict[str, str] = {}
            for arg in msg.data:
                data[arg.name] = arg.value

            self.handle_voice_event(VoiceAssistantEventType(msg.event_type), data)
        elif isinstance(msg, VoiceAssistantAnnounceRequest):
            _LOGGER.debug("Announcing: %s", msg.text)

            assert self.state.media_player_entity is not None

            urls = []
            if msg.preannounce_media_id:
                urls.append(msg.preannounce_media_id)

            urls.append(msg.media_id)

            self.state.active_wake_words.add(self.state.stop_word.id)
            self._continue_conversation = msg.start_conversation

            self.duck()
            yield from self.state.media_player_entity.play(
                urls, announcement=True, done_callback=self._tts_finished
            )
        elif isinstance(msg, VoiceAssistantTimerEventResponse):
            self.handle_timer_event(VoiceAssistantTimerEventType(msg.event_type), msg)
        elif isinstance(msg, DeviceInfoRequest):
            yield DeviceInfoResponse(
                uses_password=False,
                name=self.state.name,
                mac_address=self.state.mac_address,
                voice_assistant_feature_flags=(
                    VoiceAssistantFeature.VOICE_ASSISTANT
                    | VoiceAssistantFeature.API_AUDIO
                    | VoiceAssistantFeature.ANNOUNCE
                    | VoiceAssistantFeature.START_CONVERSATION
                    | VoiceAssistantFeature.TIMERS
                ),
            )
        elif isinstance(
            msg,
            (
                ListEntitiesRequest,
                SubscribeHomeAssistantStatesRequest,
                MediaPlayerCommandRequest,
            ),
        ):
            for entity in self.state.entities:
                yield from entity.handle_message(msg)

            if isinstance(msg, ListEntitiesRequest):
                yield ListEntitiesDoneResponse()
        elif isinstance(msg, VoiceAssistantConfigurationRequest):
            available_wake_words = [
                VoiceAssistantWakeWord(
                    id=ww.id,
                    wake_word=ww.wake_word,
                    trained_languages=ww.trained_languages,
                )
                for ww in self.state.available_wake_words.values()
            ]

            for eww in msg.external_wake_words:
                if eww.model_type != "micro":
                    continue

                available_wake_words.append(
                    VoiceAssistantWakeWord(
                        id=eww.id,
                        wake_word=eww.wake_word,
                        trained_languages=eww.trained_languages,
                    )
                )

                self._external_wake_words[eww.id] = eww

            yield VoiceAssistantConfigurationResponse(
                available_wake_words=available_wake_words,
                active_wake_words=[
                    ww.id
                    for ww in self.state.wake_words.values()
                    if ww.id in self.state.active_wake_words
                ],
                max_active_wake_words=2,
            )
            _LOGGER.info("Connected to Home Assistant")
        elif isinstance(msg, VoiceAssistantSetConfiguration):
            active_wake_words: Set[str] = set()

            for wake_word_id in msg.active_wake_words:
                if wake_word_id in self.state.wake_words:
                    active_wake_words.add(wake_word_id)
                    continue

                model_info = self.state.available_wake_words.get(wake_word_id)
                if not model_info:
                    external_wake_word = self._external_wake_words.get(wake_word_id)
                    if not external_wake_word:
                        continue

                    model_info = self._download_external_wake_word(external_wake_word)
                    if not model_info:
                        continue

                    self.state.available_wake_words[wake_word_id] = model_info

                _LOGGER.debug("Loading wake word: %s", model_info.wake_word_path)
                self.state.wake_words[wake_word_id] = model_info.load(
                    porcupine_access_key=self.state.porcupine_access_key
                )

                _LOGGER.info("Wake word set: %s", wake_word_id)
                active_wake_words.add(wake_word_id)
                break

            self.state.active_wake_words = active_wake_words
            _LOGGER.debug("Active wake words: %s", active_wake_words)

            self.state.preferences.active_wake_words = list(active_wake_words)
            self.state.save_preferences()
            self.state.wake_words_changed = True

    def handle_audio(self, audio_chunk: bytes) -> None:

        if not self._is_streaming_audio:
            return

        self.send_messages([VoiceAssistantAudio(data=audio_chunk)])

    def wakeup(self, wake_word: Union[MicroWakeWord, OpenWakeWord, pvporcupine.Porcupine]) -> None:
        if self._timer_finished:
            self._timer_finished = False
            self.state.tts_player.stop()
            _LOGGER.debug("Stopping timer finished sound")
            return

        wake_word_phrase = wake_word.wake_word
        _LOGGER.debug("Detected wake word: %s", wake_word_phrase)
        
        # Cancel any keep-awake timer since we got explicit wake word
        self._cancel_keepawake_timer()
        self._in_keepawake_mode = False
        
        # === START SPEAKER-ID CAPTURE ===
        speaker_id_start()
        
        self.send_messages(
            [VoiceAssistantRequest(start=True, wake_word_phrase=wake_word_phrase)]
        )
        self.duck()
        self._is_streaming_audio = True
        self.state.tts_player.play(self._next_greeting)
        self._preload_greeting()

    def stop(self) -> None:
        self.state.active_wake_words.discard(self.state.stop_word.id)
        self.state.tts_player.stop()
        self._cancel_keepawake_timer()
        self._in_keepawake_mode = False

        if self._timer_finished:
            self._timer_finished = False
            _LOGGER.debug("Stopping timer finished sound")
        else:
            _LOGGER.debug("TTS response stopped manually")
            self._tts_finished()

    def play_tts(self) -> None:
        if (not self._tts_url) or self._tts_played:
            return

        self._tts_played = True
        _LOGGER.debug("Playing TTS response: %s", self._tts_url)

        self.state.active_wake_words.add(self.state.stop_word.id)
        self.state.tts_player.play(self._tts_url, done_callback=self._tts_finished)

    def duck(self) -> None:
        _LOGGER.debug("Ducking music")
        self.state.music_player.duck()

    def unduck(self) -> None:
        _LOGGER.debug("Unducking music")
        self.state.music_player.unduck()

    def _tts_finished(self) -> None:
        self.state.active_wake_words.discard(self.state.stop_word.id)
        self.send_messages([VoiceAssistantAnnounceFinished()])

        if self._continue_conversation:
            self.send_messages([VoiceAssistantRequest(start=True)])
            self._is_streaming_audio = True
            _LOGGER.debug("Continuing conversation")
        else:
            self.unduck()

        _LOGGER.debug("TTS response finished")

    def _play_timer_finished(self) -> None:
        if not self._timer_finished:
            self.unduck()
            return

        self.state.tts_player.play(
            self.state.timer_finished_sound,
            done_callback=lambda: call_all(
                lambda: time.sleep(1.0), self._play_timer_finished
            ),
        )

    def connection_lost(self, exc):
        super().connection_lost(exc)
        self._cancel_keepawake_timer()
        _LOGGER.info("Disconnected from Home Assistant")

    def _download_external_wake_word(
        self, external_wake_word: VoiceAssistantExternalWakeWord
    ) -> Optional[AvailableWakeWord]:
        eww_dir = self.state.download_dir / "external_wake_words"
        eww_dir.mkdir(parents=True, exist_ok=True)

        config_path = eww_dir / f"{external_wake_word.id}.json"
        should_download_config = not config_path.exists()

        model_path = eww_dir / f"{external_wake_word.id}.tflite"
        should_download_model = True
        if model_path.exists():
            model_size = model_path.stat().st_size
            if model_size == external_wake_word.model_size:
                with open(model_path, "rb") as model_file:
                    model_hash = hashlib.sha256(model_file.read()).hexdigest()

                if model_hash == external_wake_word.model_hash:
                    should_download_model = False
                    _LOGGER.debug(
                        "Model size and hash match for %s. Skipping download.",
                        external_wake_word.id,
                    )

        if should_download_config or should_download_model:
            _LOGGER.debug("Downloading %s to %s", external_wake_word.url, config_path)
            with urlopen(external_wake_word.url) as request:
                if request.status != 200:
                    _LOGGER.warning(
                        "Failed to download: %s, status=%s",
                        external_wake_word.url,
                        request.status,
                    )
                    return None

                with open(config_path, "wb") as model_file:
                    shutil.copyfileobj(request, model_file)

        if should_download_model:
            parsed_url = urlparse(external_wake_word.url)
            parsed_url = parsed_url._replace(
                path=posixpath.join(posixpath.dirname(parsed_url.path), model_path.name)
            )
            model_url = urlunparse(parsed_url)

            _LOGGER.debug("Downloading %s to %s", model_url, model_path)
            with urlopen(model_url) as request:
                if request.status != 200:
                    _LOGGER.warning(
                        "Failed to download: %s, status=%s", model_url, request.status
                    )
                    return None

                with open(model_path, "wb") as model_file:
                    shutil.copyfileobj(request, model_file)

        return AvailableWakeWord(
            id=external_wake_word.id,
            type=WakeWordType.MICRO_WAKE_WORD,
            wake_word=external_wake_word.wake_word,
            trained_languages=external_wake_word.trained_languages,
            wake_word_path=config_path,
        )