import logging
from typing import Optional

import assemblyai as aai

from config import config


logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self):
        if not config.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY not set")
        
        aai.settings.api_key = config.assemblyai_api_key
        self.config = aai.TranscriptionConfig(
            language_code="ar",  # Arabic
        )
    
    def transcribe_audio(self, audio_data: bytes) -> str:
        try:
            transcriber = aai.Transcriber()
            
            transcript = transcriber.transcribe(
                audio_data,
                config=self.config
            )
            
            if transcript.status == aai.TranscriptStatus.error:
                logger.error(f"AssemblyAI error: {transcript.error}")
                raise Exception(transcript.error)
            
            text = transcript.text
            logger.info(f"Transcription: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            raise


_transcription_service = None

def get_transcription_service() -> TranscriptionService:
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service