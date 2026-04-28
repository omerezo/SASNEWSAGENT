import os
import base64
import logging
import requests
from flask import Flask, request, jsonify
from config import config
from db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{config.telegram_token}"


def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage", json=data, timeout=10)
    except Exception as e:
        logger.error(f"send_message error: {e}")


def answer_callback_query(query_id, text=None):
    data = {"callback_query_id": query_id}
    if text:
        data["text"] = text
    requests.post(f"{TELEGRAM_API}/answerCallbackQuery", json=data)


def get_file(file_id):
    resp = requests.post(f"{TELEGRAM_API}/getFile", json={"file_id": file_id})
    return resp.json().get("result", {})


def download_file(file_path):
    resp = requests.get(f"https://api.telegram.org/file/bot{config.telegram_token}/{file_path}")
    return resp.content


# Keyboards
def confirmation_keyboard():
    return {"inline_keyboard": [
        [{"text": "✏️ Edit", "callback_data": "edit_text"}],
        [{"text": "✅ Yes", "callback_data": "confirm_yes"}],
        [{"text": "❌ No", "callback_data": "confirm_no"}]
    ]}


def post_keyboard():
    return {"inline_keyboard": [
        [{"text": "📸 Post with Image", "callback_data": "post_news"}]
    ]}


# Routes
@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
        update_id = data.get("update_id", 0)
        
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
    return jsonify({"status": "ok"})


# Handlers
def handle_message(msg):
    try:
        user_id = msg["from"]["id"]
        chat_id = msg.get("chat", {}).get("id")
        is_group = chat_id and chat_id != user_id
        target_chat = chat_id
        
        logger.info(f"Message: user={user_id}, chat={chat_id}, is_group={is_group}")
        
        if is_group:
            text = msg.get("text", "")
            entities = msg.get("entities", [])
            mentioned = any(ent.get("type") in ["mention", "bot_command"] for ent in entities)
            is_reply = msg.get("reply_to_message", {}).get("from", {}).get("is_bot") if msg.get("reply_to_message") else False
            
            if text and not mentioned and not is_reply:
                return
        
        db = get_db()
        session = db.get_session(user_id)
        if not session:
            session = db.create_session(user_id, "waiting_voice")
        
        if "voice" in msg:
            handle_voice(user_id, target_chat, msg["voice"], session, db)
        elif "text" in msg:
            handle_text(user_id, target_chat, msg["text"], session, db)
        elif "photo" in msg:
            handle_photo(user_id, target_chat, msg["photo"], session, db)
    except Exception as e:
        logger.error(f"handle_message error: {e}", exc_info=True)


def handle_voice(user_id, chat_id, voice, session, db):
    try:
        send_message(chat_id, "🎤 Processing...")
        file_info = get_file(voice["file_id"])
        file_path = file_info.get("file_path")
        if not file_path:
            send_message(chat_id, "❌ Could not download audio.")
            return
        
        audio_data = download_file(file_path)
        from services.transcription import get_transcription_service
        transcribed = get_transcription_service().transcribe_audio(audio_data)
        
        if not transcribed:
            send_message(chat_id, "❌ Could not understand.")
            return
        
        db.update_session(user_id, transcribed_text=transcribed, state="waiting_confirmation")
        send_message(chat_id, f"📝 You said:\n\n\"{transcribed}\"\n\nIs this correct?", reply_markup=confirmation_keyboard())
    except Exception as e:
        logger.error(f"Voice error: {e}")
        send_message(chat_id, "❌ Error processing voice.")


def handle_text(user_id, chat_id, text, session, db):
    text_lower = text.lower()
    
    if text_lower in ["/start", "/restart"]:
        db.delete_session(user_id)
        db.create_session(user_id, "waiting_voice")
        send_message(chat_id, "🎤 Send me a voice note.")
    elif text_lower in ["/cancel", "cancel"]:
        db.delete_session(user_id)
        send_message(chat_id, "❌ Cancelled.")
    elif session.state == "editing_text":
        db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
        send_message(chat_id, f"📝 You said:\n\n\"{text}\"\n\nIs this correct?", reply_markup=confirmation_keyboard())
    elif session.state == "waiting_confirmation":
        db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
        send_message(chat_id, f"📝 You said:\n\n\"{text}\"\n\nIs this correct?", reply_markup=confirmation_keyboard())
    else:
        send_message(chat_id, "🎤 Send me a voice note.")


def handle_photo(user_id, chat_id, photos, session, db):
    if session.state != "waiting_post" or not session.title_ar:
        send_message(chat_id, "Please confirm article first.")
        return
    
    photo = photos[-1]
    db.update_session(user_id, image_file_id=photo["file_id"])
    session = db.get_session(user_id)
    post_article(user_id, chat_id, photo["file_id"], session, db)


def handle_callback(callback):
    user_id = callback["from"]["id"]
    data = callback["data"]
    query_id = callback["id"]
    
    answer_callback_query(query_id)
    
    db = get_db()
    session = db.get_session(user_id)
    
    if not session:
        send_message(user_id, "Session expired.")
        return
    
    if data == "edit_text":
        send_message(user_id, f"✏️ Current:\n{session.transcribed_text}\n\nSend corrected:")
        db.update_session(user_id, state="editing_text")
    elif data == "confirm_yes":
        handle_confirm_yes(user_id, session, db)
    elif data == "confirm_no":
        send_message(user_id, "❌ Send voice note again.")
        db.update_session(user_id, state="waiting_voice")
    elif data == "post_news":
        send_message(user_id, "📸 Send an image.")


def handle_confirm_yes(user_id, session, db):
    try:
        send_message(user_id, "✍️ Creating article...")
        from services.article import get_article_service
        article = get_article_service().generate_article(session.transcribed_text)
        
        db.update_session(user_id,
            title_ar=article.get("title_ar"),
            title_en=article.get("title_en"),
            content_ar=article.get("content_ar"),
            content_en=article.get("content_en"),
            excerpt_ar=article.get("excerpt_ar"),
            excerpt_en=article.get("excerpt_en"),
            state="waiting_post")
        
        send_message(user_id, f"📰 {article['title_ar']}\n{article['content_ar'][:200]}...\n\n📰 {article['title_en']}\n{article['content_en'][:200]}...", reply_markup=post_keyboard())
    except Exception as e:
        logger.error(f"Article error: {e}")
        send_message(user_id, "❌ Error generating article.")


def post_article(user_id, chat_id, file_id, session, db):
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
            "image": f"data:image/jpeg;base64,{base64.b64encode(photo_data).decode()}",
        }
        
        from services.website import get_website_api
        result = get_website_api().post_news(article)
        
        if result.get("success"):
            news_id = result.get("id")
            url = f"{config.website_base_url}/news/{news_id}"
            send_message(chat_id, f"✅ Live!\n{url}")
            db.delete_session(user_id)
        else:
            send_message(chat_id, "❌ Failed to post.")
    except Exception as e:
        logger.error(f"Post error: {e}", exc_info=True)
        send_message(chat_id, "❌ Error posting.")


if __name__ == "__main__":
    app.run(host=config.host, port=config.port)