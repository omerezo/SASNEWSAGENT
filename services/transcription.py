import io
import logging
from typing import Optional

import assemblyai as aai

from config import config


logger = logging.getLogger(__name__)


class TranscriptionService:
    def __init__(self):
        if not config.assemblyai_api_key:
            raise ValueError("ASSEMBLYAI_API_KEY not set in config")
        
        logger.info("Initializing AssemblyAI transcription service")
        aai.settings.api_key = config.assemblyai_api_key
        self.transcriber = aai.Transcriber()
    
    def transcribe_audio(self, audio_data: bytes) -> str:
        try:
            logger.info(f"Transcribing audio: {len(audio_data)} bytes")
            
            # For bytes, we need to use upload_file first
            upload_url = self.transcriber.upload_file(audio_data)
            logger.info(f"Uploaded to: {upload_url}")
            
            transcript = self.transcriber.transcribe(upload_url)
            
            if transcript.status == aai.TranscriptStatus.error:
                error_msg = transcript.error or "Unknown error"
                logger.error(f"AssemblyAI error: {error_msg}")
                raise Exception(error_msg)
            
            if not transcript.text:
                logger.warning("Empty transcription result")
                return ""
            
            text = transcript.text.strip()
            logger.info(f"Transcription: {text[:100]}...")
            return text
            
        except Exception as e:
            logger.error(f"Transcription error: {e}", exc_info=True)
            raise


_transcription_service = None

def get_transcription_service() -> TranscriptionService:
    global _transcription_service
    if _transcription_service is None:
        _transcription_service = TranscriptionService()
    return _transcription_service