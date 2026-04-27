import io
import tempfile
import logging
from typing import Optional

from google.cloud import speech_v2 as speech
from google.cloud.speech_v2.types import RecognitionConfig

from config import config


logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self):
        self.client = speech.SpeechClient()
        self.config = RecognitionConfig(
            auto_decoding_config={},
            language_code="ar-SA",
            model="latest_long",
        )
    
    def transcribe_audio(self, audio_data: bytes) -> str:
        content = audio_data
        
        if len(audio_data) < 16000:
            logger.warning(f"Audio too short: {len(audio_data)} bytes")
        
        audio = speech.RecognitionAudio(content=content)
        
        try:
            response = self.client.recognize(
                config=self.config,
                audio=audio
            )
            
            if not response.results:
                logger.warning("No transcription results")
                return ""
            
            result = response.results[0]
            if not result.alternatives:
                logger.warning("No alternatives in result")
                return ""
            
            transcript = result.alternatives[0].transcript
            logger.info(f"Transcription: {transcript[:100]}...")
            return transcript
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise


_transcription_service = None

def get_transcription_service() -> TranscriptionService:
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service