import json
import logging
from typing import Dict

from google import genai
from google.genai import types

from config import config


logger = logging.getLogger(__name__)


REQUIRED_FIELDS = ("title_ar", "title_en", "content_ar", "content_en", "excerpt_ar", "excerpt_en")


PROMPT_TEMPLATE = """You are a senior bilingual sports news writer for SAS Academy (SAS — Sudani Academy Sport), a sports academy that develops athletes and runs training programs.

Your task: convert the TRANSCRIBED TEXT below into a polished bilingual news article (Modern Standard Arabic + English).

STYLE GUIDE
- Professional, neutral, factual newsroom tone. No marketing fluff, no emojis, no hashtags.
- Stick strictly to the facts in the transcribed text. Do NOT invent names, scores, dates, places, quotes, or numbers. If a detail is missing, simply omit it — do not fabricate.
- Arabic must be Modern Standard Arabic (فصحى), not colloquial. English must be clean newsroom English.
- The Arabic version and the English version must convey the same facts; they are translations of each other, not separate articles.
- Refer to the academy as "أكاديمية سوداني الرياضية" in Arabic and "SAS Academy" or "Sudani Academy Sport" in English when relevant.

LENGTH TARGETS
- title_ar / title_en: a single concise headline, roughly 60–100 characters. No trailing period.
- excerpt_ar / excerpt_en: 1–2 sentences summarising the news, roughly 150–220 characters.
- content_ar / content_en: 3–5 short paragraphs separated by blank lines, roughly 180–320 words.

OUTPUT FORMAT
Return ONLY a single JSON object — no markdown, no commentary, no code fences — with EXACTLY these keys:
{{
    "title_ar":   "...",
    "title_en":   "...",
    "content_ar": "...",
    "content_en": "...",
    "excerpt_ar": "...",
    "excerpt_en": "..."
}}

All Arabic fields MUST be written in Arabic script. All English fields MUST be in English. Every field is required and non-empty.

TRANSCRIBED TEXT:
{transcribed_text}
"""


class ArticleGenerationService:
    def __init__(self):
        if not config.gemini_api_key:
            raise ValueError("GEMINI_API_KEY not set in config")
        self.client = genai.Client(api_key=config.gemini_api_key)
        self.model = "gemini-2.5-flash"

    def generate_article(self, transcribed_text: str) -> Dict[str, str]:
        logger.info(f"Generating article for text: {transcribed_text[:80]}...")

        prompt = PROMPT_TEMPLATE.format(transcribed_text=transcribed_text)

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.6,
                },
            )

            raw_text = response.text or ""
            logger.info(f"Raw response (first 300 chars): {raw_text[:300]}")

            article = json.loads(raw_text)

            # Validate every required field is present and non-empty
            missing = [f for f in REQUIRED_FIELDS if not (article.get(f) or "").strip()]
            if missing:
                raise ValueError(f"Missing/empty fields in article: {missing}")

            logger.info(f"Generated article: {article['title_ar'][:40]}...")
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
