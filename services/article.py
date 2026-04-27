import json
import logging
from typing import Dict, Optional

from google import genai
try:
    from google.genai import types
except ImportError:
    types = None

from config import config


logger = logging.getLogger(__name__)


class ArticleGenerationService:
    def __init__(self):
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not set in config")
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.model = "gemini-1.5-flash"
    
    def generate_article(self, transcribed_text: str) -> Dict[str, str]:
        if not transcribed_text:
            raise ValueError("Transcribed text is empty")

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
            logger.info(f"Generating article for text: {transcribed_text[:100]}...")
            
            generate_config = None
            if types:
                generate_config = types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7,
                )
            else:
                generate_config = {
                    "response_mime_type": "application/json",
                    "temperature": 0.7,
                }

            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=generate_config
            )

            if not response or not response.text:
                logger.error(f"Empty response from Gemini API. Response: {response}")
                raise Exception("Empty response from Gemini API")

            text = response.text
            logger.info(f"Raw response text: {text}")

            # Strip markdown fences if the model wrapped the JSON
            if text and text.strip().startswith("```"):
                text = text.strip()
                # Find the first and last triple backticks
                first_idx = text.find("```")
                last_idx = text.rfind("```")
                
                # Extract content between fences
                content = text[first_idx+3:last_idx].strip()
                if content.startswith("json"):
                    content = content[4:].strip()
                text = content

            try:
                article = json.loads(text)
            except json.JSONDecodeError as e:
                logger.error(f"JSON decode error: {e}. Raw text: {text}")
                # Try a more aggressive cleanup if simple strip failed
                raise

            # Validate required keys
            required_keys = ["title_ar", "title_en", "content_ar", "content_en", "excerpt_ar", "excerpt_en"]
            missing_keys = [k for k in required_keys if k not in article]
            if missing_keys:
                logger.warning(f"Missing keys in generated article: {missing_keys}")
                # Provide defaults for missing keys to avoid KeyError later
                for k in missing_keys:
                    article[k] = f"Missing {k}"

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