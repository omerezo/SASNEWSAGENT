import os
import base64
import logging
import json
import requests

from flask import Flask, request, jsonify

from config import config
from db import get_db, Database
from keyboards import confirmation_keyboard, post_keyboard, cancel_keyboard
from services.transcription import get_transcription_service
from services.article import get_article_service
from services.website import get_website_api


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


app = Flask(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{config.telegram_token}"


def send_message(chat_id: int, text: str, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    requests.post(f"{TELEGRAM_API}/sendMessage", json=data)


def answer_callback_query(callback_query_id: str, text: str = None):
    data = {"callback_query_id": callback_query_id}
    if text:
        data["text"] = text
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=data)


def get_file(file_id: str):
    resp = requests.post(f"{TELEGRAM_API}/getFile", json={"file_id": file_id})
    return resp.json().get("result", {})


def download_file(file_path: str):
    resp = requests.get(f"https://api.telegram.org/file/bot{config.telegram_token}/{file_path}")
    return resp.content


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update_id = data.get("update_id", 0)
        logger.info(f"Received update: {update_id}")
        
        if "callback_query" in data:
            handle_callback(data["callback_query"])
        elif "message" in data:
            handle_message(data["message"])
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/", methods=["GET", "POST"])
def root():
    return jsonify({"status": "ok", "service": "SAS News Agent"})


def handle_message(msg: dict):
    try:
        user_id = msg["from"]["id"]
        
        db = get_db()
        session = db.get_session(user_id)
        
        if not session:
            session = db.create_session(user_id, "waiting_voice")
        
        if "voice" in msg:
            handle_voice_message(user_id, msg["voice"], session, db)
        elif "text" in msg:
            handle_text_message(user_id, msg["text"], session, db)
        elif "photo" in msg:
            handle_photo_message(user_id, msg["photo"], session, db)
        else:
            send_message(user_id, "Please send a voice note to create a news article.")
    except Exception as e:
        logger.error(f"handle_message error: {e}", exc_info=True)
        user_id = msg.get("from", {}).get("id")
        if user_id:
            send_message(user_id, f"❌ Error: {str(e)}")


def handle_voice_message(user_id: int, voice: dict, session, db):
    try:
        send_message(user_id, "🎤 Processing your voice note...")
        
        file_info = get_file(voice["file_id"])
        file_path = file_info.get("file_path")
        
        if not file_path:
            send_message(user_id, "❌ Could not download audio.")
            return
        
        audio_data = download_file(file_path)
        logger.info(f"Downloaded audio: {len(audio_data)} bytes")
        
        transcription_service = get_transcription_service()
        transcribed_text = transcription_service.transcribe_audio(audio_data)
        
        if not transcribed_text:
            send_message(user_id, "❌ Could not understand the audio. Please try again.")
            return
        
        db.update_session(user_id, transcribed_text=transcribed_text, state="waiting_confirmation")
        
        send_message(
            user_id,
            f"📝 You said:\n\n\"{transcribed_text}\"\n\nIs this correct?",
            reply_markup=confirmation_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Voice processing error: {e}", exc_info=True)
        send_message(user_id, "❌ Error processing voice. Please try again.")


def handle_text_message(user_id: int, text: str, session, db):
    text = text.lower()
    
    if text in ["/start", "/restart"]:
        db.delete_session(user_id)
        db.create_session(user_id, "waiting_voice")
        send_message(user_id, "🎤 Send me a voice note to create a news article.")
    elif text in ["/cancel", "cancel"]:
        db.delete_session(user_id)
        send_message(user_id, "❌ Cancelled. Send a voice note to start again.")
    elif session.state == "waiting_confirmation":
        db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
        send_message(
            user_id,
            f"📝 You said:\n\n\"{text}\"\n\nIs this correct?",
            reply_markup=confirmation_keyboard()
        )
    else:
        send_message(user_id, "🎤 Send me a voice note to create a news article.")


def handle_photo_message(user_id: int, photos: list, session, db):
    logger.info(f"handle_photo: state={session.state}, title_ar={session.title_ar}")
    
    if session.state != "waiting_post" or not session.title_ar:
        logger.error(f"Invalid state or no article. state={session.state}, title_ar={session.title_ar}")
        send_message(user_id, "Please confirm the article first by clicking Yes button.")
        return
    
    photo = photos[-1]
    db.update_session(user_id, image_file_id=photo["file_id"], state="waiting_post")
    
    # Re-fetch session to get article data
    session = db.get_session(user_id)
    post_article_from_message(user_id, photo["file_id"], session, db)


def handle_callback(callback: dict):
    user_id = callback["from"]["id"]
    data = callback["data"]
    query_id = callback["id"]
    
    answer_callback_query(query_id)
    
    db = get_db()
    session = db.get_session(user_id)
    
    if not session:
        send_message(user_id, "Session expired. Send /start to begin.")
        return
    
    if data == "confirm_yes":
        handle_confirmation_yes(user_id, session, db)
    elif data == "confirm_no":
        handle_confirmation_no(user_id, session, db)
    elif data == "post_news":
        handle_post_news(user_id, session, db)
    elif data == "action_cancel":
        db.delete_session(user_id)
        send_message(user_id, "❌ Cancelled. Send a voice note to start again.")


def handle_confirmation_yes(user_id: int, session, db):
    send_message(user_id, "✍️ Creating your article...")
    
    try:
        article_service = get_article_service()
        article = article_service.generate_article(session.transcribed_text)
        
        logger.info(f"Saving article: title_ar={article.get('title_ar')[:30]}, content_ar={article.get('content_ar')[:30] if article.get('content_ar') else 'None'}")
        
        db.update_session(
            user_id,
            title_ar=article.get("title_ar"),
            title_en=article.get("title_en"),
            content_ar=article.get("content_ar"),
            content_en=article.get("content_en"),
            excerpt_ar=article.get("excerpt_ar"),
            excerpt_en=article.get("excerpt_en"),
            state="waiting_post"
        )
        
        # Verify save
        new_session = db.get_session(user_id)
        logger.info(f"After save: title_ar={new_session.title_ar}")
        
        article_text = f"""📰 {article['title_ar']}

{article['content_ar']}

---

📰 {article['title_en']}

{article['content_en']}

---

✅ Click '📸 Post' to publish with an image, or send an image now."""
        
        send_message(user_id, article_text, reply_markup=post_keyboard())
        
    except Exception as e:
        logger.error(f"Article generation error: {e}", exc_info=True)
        send_message(user_id, "❌ Error generating article. Please try again.")


def handle_confirmation_no(user_id: int, session, db):
    send_message(
        user_id,
        "❌ Please send the voice note again or type your message.",
        reply_markup=cancel_keyboard()
    )
    
    db.update_session(user_id, state="waiting_voice")


def handle_post_news(user_id: int, session, db):
    if not session.image_file_id:
        send_message(user_id, "📸 Please send an image to include with the article.")
        return
    
    try:
        file_info = get_file(session.image_file_id)
        photo_data = download_file(file_info.get("file_path"))
        
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
            "image": f"data:image/jpeg;base64,{base64.b64encode(photo_data).decode()}",
        }
        
        website_api = get_website_api()
        result = website_api.post_news(article)
        
        if result.get("success"):
            news_id = result.get("id")
            url = f"{config.website_base_url}/news/{news_id}"
            
            send_message(user_id, f"✅ Live!\n\nLink: {url}")
            
            db.delete_session(user_id)
        else:
            send_message(user_id, "❌ Failed to post. Please try again.")
            
    except Exception as e:
        logger.error(f"Post error: {e}")
        send_message(user_id, "❌ Error posting article. Please try again.")


def post_article_from_message(user_id: int, file_id: str, session, db):
    logger.info(f"post_article_from_message called. session.title_ar={session.title_ar}")
    
    if not session.title_ar:
        logger.error(f"Session data: title_ar={session.title_ar}, title_en={session.title_en}, content_ar={session.content_ar}")
        send_message(user_id, "No article to post. Please start over.")
        return
    
    try:
        file_info = get_file(file_id)
        photo_data = download_file(file_info.get("file_path"))
        
        logger.info(f"Preparing article: title_ar={session.title_ar[:30]}...")
        
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
            "image": f"data:image/jpeg;base64,{base64.b64encode(photo_data).decode()}",
        }
        
        website_api = get_website_api()
        result = website_api.post_news(article)
        
        if result.get("success"):
            news_id = result.get("id")
            url = f"{config.website_base_url}/news/{news_id}"
            
            send_message(user_id, f"✅ Live!\n\nLink: {url}")
            
            db.delete_session(user_id)
        else:
            send_message(user_id, "❌ Failed to post. Please try again.")
            
    except Exception as e:
        logger.error(f"Post error: {e}")
        send_message(user_id, "❌ Error posting article. Please try again.")


if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
