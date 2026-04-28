import logging
from typing import Dict, Optional
import requests

from config import config


logger = logging.getLogger(__name__)


class WebsiteAPIService:
    def __init__(self):
        self.base_url = config.website_base_url
        self.api_key = config.website_api_key
    
    def post_news(self, article: Dict[str, str]) -> Dict:
        url = f"{self.base_url}/api/agent/news"
        headers = {
            "Content-Type": "application/json",
            "X-Agent-Key": self.api_key,
        }
        
        payload = {
            "title_ar": article.get("title_ar"),
            "title_en": article.get("title_en"),
            "content_ar": article.get("content_ar"),
            "content_en": article.get("content_en"),
            "excerpt_ar": article.get("excerpt_ar"),
            "excerpt_en": article.get("excerpt_en"),
            "image": article.get("image"),
            "featured": False,
            "published": True,
        }
        
        try:
            logger.info(f"Posting to {url}")
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text}")
            response.raise_for_status()
            result = response.json()
            logger.info(f"Posted news: {result.get('id')}")
            return result
        except requests.exceptions.HTTPError as e:
            logger.error(f"Website API HTTP error: {e} - {response.text}")
            raise
        except Exception as e:
            logger.error(f"Website API error: {e}")
            raise


_website_api = None

def get_website_api() -> WebsiteAPIService:
    global _website_api
    if _website_api is None:
        _website_api = WebsiteAPIService()
    return _website_api