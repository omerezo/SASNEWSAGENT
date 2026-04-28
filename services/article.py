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
        self.model = "gemini-2.0-flash"

    def generate_article(self, transcribed_text: str) -> Dict[str, str]:
        prompt = f"""You are a professional sports news writer. Given a voice transcription, create a bilingual (Arabic + English) news article.

TRANSCRIBED TEXT:
{transcribed_text}

Create a professional news article with EXACTLY this JSON structure (all fields required):
{{
    "title_ar": "Arabic headline",
    "title_en": "English headline",
    "content_ar": "Arabic article body (2-3 paragraphs, Arabic script only)",
    "content_en": "English article body (2-3 paragraphs)",
    "excerpt_ar": "Arabic excerpt (1-2 sentences, Arabic script only)",
    "excerpt_en": "English excerpt (1-2 sentences)"
}}

Requirements:
- Write ALL Arabic fields in Arabic script, NOT transliteration
- Keep titles under 100 characters
- Content should be 150-300 words per language
- Output ONLY valid JSON, no markdown, no explanations"""

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                ),
            )

            if not response or not response.text:
                raise ValueError("Empty response from Gemini API")

            text = response.text.strip()

            # Strip markdown fences if the model wrapped the JSON
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()

            article = json.loads(text)

            required_keys = ["title_ar", "title_en", "content_ar", "content_en", "excerpt_ar", "excerpt_en"]
            for k in required_keys:
                if k not in article:
                    article[k] = ""

            logger.info(f"Generated article: {article.get('title_en', 'N/A')[:60]}")
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
