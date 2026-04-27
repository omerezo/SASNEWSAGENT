import json
import logging
from typing import Dict, Optional

from google import genai

from config import config


logger = logging.getLogger(__name__)


class ArticleGenerationService:
    def __init__(self):
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.model = "gemini-2.5-pro"
    
    def generate_article(self, transcribed_text: str) -> Dict[str, str]:
        prompt = f"""You are a professional sports news writer. Given a voice transcription, create a bilingual (Arabic + English) news article.

TRANSCRIBED TEXT:
{transcribed_text}

Create a professional news article with the following JSON structure:
{{
    "title_ar": "Arabic headline (concise, compelling)",
    "title_en": "English headline",
    "content_ar": "Arabic article body (2-3 paragraphs, professional news style)",
    "content_en": "English article body (same content, professional translation)",
    "excerpt_ar": "Arabic excerpt (1-2 sentences for preview)",
    "excerpt_en": "English excerpt"
}}

Requirements:
- Be professional and news-like
- Extract the key facts from the transcription
- Write in Arabic first, then translate professionally to English
- Keep titles under 100 characters
- Content should be 150-300 words
- Output ONLY valid JSON, no explanations"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.7,
                }
            )
            
            article = json.loads(response.text)
            logger.info(f"Generated article: {article.get('title_ar', 'N/A')[:50]}...")
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