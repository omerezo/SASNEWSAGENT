import json
import logging
from typing import Dict

from google import genai
from google.genai import types

from config import config


logger = logging.getLogger(__name__)


class ArticleGenerationService:
    def __init__(self):
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not set in config")
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.model = "gemini-2.5-flash"
    
    def generate_article(self, transcribed_text: str) -> Dict[str, str]:
        logger.info(f"Generating article for text: {transcribed_text[:50]}...")
        
        prompt = f"""You are a professional sports news writer. Given a voice transcription, create a bilingual (Arabic + English) news article.

TRANSCRIBED TEXT:
{transcribed_text}

Create EXACTLY this JSON (all fields required):
{{
    "title_ar": "Arabic headline in Arabic",
    "title_en": "English headline",
    "content_ar": "Arabic article body in Arabic",
    "content_en": "English article body",  
    "excerpt_ar": "Arabic excerpt in Arabic",
    "excerpt_en": "English excerpt"
}}

IMPORTANT: ALL Arabic fields MUST be in Arabic script. Output JSON only."""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.7,
                }
            )
            
            logger.info(f"Raw response text: {response.text}")
            
            article = json.loads(response.text)
            logger.info(f"Generated article: {article.get('title_ar', 'N/A')[:30]}...")
            
            if not article.get("content_ar"):
                raise ValueError("Missing content_ar in response")
            
            return article
            
        except Exception as e:
            logger.error(f"Article generation error: {e}", exc_info=True)
            raise


_article_service = None

def get_article_service() -> ArticleGenerationService:
    global _article_service
    if _article_service is None:
        _article_service = ArticleGenerationService()
    return _article_service
