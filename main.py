import os
import asyncio
import logging
import io
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


def handle_message(msg: dict):
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


def handle_voice_message(user_id: int, voice: dict, session, db):
    send_message(user_id, "🎤 Processing your voice note...")
    
    file_info = get_file(voice["file_id"])
    file_path = file_info.get("file_path")
    
    if not file_path:
        send_message(user_id, "❌ Could not download audio.")
        return
    
    audio_data = download_file(file_path)
    
    try:
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
        logger.error(f"Voice processing error: {e}")
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
    if session.state != "waiting_post":
        send_message(user_id, "Please complete the article confirmation first.")
        return
    
    photo = photos[-1]
    db.update_session(user_id, image_file_id=photo["file_id"], state="waiting_post")
    
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
        
        article_text = f"""📰 {article['title_ar']}

{article['content_ar']}

---

📰 {article['title_en']}

{article['content_en']}

---

✅ Click '📸 Post' to publish with an image, or send an image now."""
        
        send_message(user_id, article_text, reply_markup=post_keyboard())
        
    except Exception as e:
        logger.error(f"Article generation error: {e}")
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
            "image": f"data:image/jpeg;base64,{photo_data.hex()}",
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
    if not session.title_ar:
        send_message(user_id, "No article to post. Please start over.")
        return
    
    try:
        file_info = get_file(file_id)
        photo_data = download_file(file_info.get("file_path"))
        
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
            "image": f"data:image/jpeg;base64,{photo_data.hex()}",
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
        data["reply_markup"] = reply_markup.to_dict()
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
        update = Update.de_json(request.get_json(force=True), None)
        logger.info(f"Received update: {update.update_id}")
        
        if update.message:
            handle_message(update)
        elif update.callback_query:
            handle_callback(update.callback_query)
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


def handle_message(update: Update):
    message = update.message
    user_id = message.from_user.id
    
    db = get_db()
    session = db.get_session(user_id)
    
    if not session:
        session = db.create_session(user_id, "waiting_voice")
    
    if message.voice:
        handle_voice_message(update, session, db)
    elif message.text:
        handle_text_message(update, session, db)
    elif message.photo:
        handle_photo_message(update, session, db)
    else:
        send_message(user_id, "Please send a voice note to create a news article.")


def handle_voice_message(update: Update, session, db):
    user_id = update.message.from_user.id
    voice = update.message.voice
    
    send_message(user_id, "🎤 Processing your voice note...")
    
    file_info = get_file(voice.file_id)
    file_path = file_info.get("file_path")
    
    if not file_path:
        send_message(user_id, "❌ Could not download audio.")
        return
    
    audio_data = download_file(file_path)
    
    try:
        transcription_service = get_transcription_service()
        transcribed_text = transcription_service.transcribe_audio(audio_data)
        
        if not transcribed_text:
            send_message(user_id, "❌ Could not understand the audio. Please try again with clearer audio.")
            return
        
        db.update_session(user_id, transcribed_text=transcribed_text, state="waiting_confirmation")
        
        send_message(
            user_id,
            f"📝 You said:\n\n\"{transcribed_text}\"\n\nIs this correct?",
            reply_markup=confirmation_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        send_message(user_id, "❌ Error processing voice. Please try again.")


def handle_text_message(update: Update, session, db):
    user_id = update.message.from_user.id
    text = update.message.text.lower()
    
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


def handle_photo_message(update: Update, session, db):
    user_id = update.message.from_user.id
    
    if session.state != "waiting_post":
        send_message(user_id, "Please complete the article confirmation first.")
        return
    
    photo = update.message.photo[-1]
    db.update_session(user_id, image_file_id=photo.file_id, state="waiting_post")
    
    post_article(update.message, session, db)


def handle_callback(callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    query = callback_query
    
    answer_callback_query(query.id)
    
    db = get_db()
    session = db.get_session(user_id)
    
    if not session:
        send_message(user_id, "Session expired. Send /start to begin.")
        return
    
    if data == "confirm_yes":
        handle_confirmation_yes(session, query, db)
    elif data == "confirm_no":
        handle_confirmation_no(session, query, db)
    elif data == "post_news":
        handle_post_news(session, query, db)
    elif data == "action_cancel":
        db.delete_session(user_id)
        send_message(user_id, "❌ Cancelled. Send a voice note to start again.")


def handle_confirmation_yes(session, query, db):
    user_id = query.from_user.id
    
    send_message(user_id, "✍️ Creating your article...")
    
    try:
        article_service = get_article_service()
        article = article_service.generate_article(session.transcribed_text)
        
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
        
        article_text = f"""📰 {article['title_ar']}

{article['content_ar']}

---

📰 {article['title_en']}

{article['content_en']}

---

✅ Click '📸 Post' to publish with an image, or send an image now."""
        
        send_message(user_id, article_text, reply_markup=post_keyboard())
        
    except Exception as e:
        logger.error(f"Article generation error: {e}")
        send_message(user_id, "❌ Error generating article. Please try again.")


def handle_confirmation_no(session, query, db):
    user_id = query.from_user.id
    
    send_message(
        user_id,
        "❌ Please send the voice note again or type your message.",
        reply_markup=cancel_keyboard()
    )
    
    db.update_session(user_id, state="waiting_voice")


def handle_post_news(session, query, db):
    user_id = query.from_user.id
    
    if not session.image_file_id:
        send_message(user_id, "📸 Please send an image to include with the article.")
        return
    
    try:
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
        }
        
        file_info = get_file(session.image_file_id)
        photo_data = download_file(file_info.get("file_path"))
        
        article["image"] = f"data:image/jpeg;base64,{photo_data.hex()}"
        
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


def post_article(message, session, db):
    user_id = message.from_user.id
    
    if not session.title_ar:
        send_message(user_id, "No article to post. Please start over.")
        return
    
    try:
        photo = message.photo[-1]
        file_info = get_file(photo.file_id)
        photo_data = download_file(file_info.get("file_path"))
        
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
            "image": f"data:image/jpeg;base64,{photo_data.hex()}",
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