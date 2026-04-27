import os
import logging
import io

from flask import Flask, request, jsonify
import telegram
from telegram import Update

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
bot = telegram.Bot(token=config.telegram_token)


@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot)
        logger.info(f"Received update: {update.update_id}")
        
        if update.message:
            handle_message(update)
        elif update.callback_query:
            handle_callback(update.callback_query)
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return jsonify({"ok": False, "error": str(e)}), 500
        logger.error(f"Webhook error: {e}")
        return jsonify({"ok": False}), 500


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
        bot.send_message(
            chat_id=user_id,
            text="Please send a voice note to create a news article."
        )


def handle_voice_message(update: Update, session, db):
    user_id = update.message.from_user.id
    voice = update.message.voice
    
    bot.send_message(chat_id=user_id, text="🎤 Processing your voice note...")
    
    file = bot.get_file(file_id=voice.file_id)
    audio_bytes = file.download_as_bytearray()
    audio_data = bytes(audio_bytes)
    
    try:
        transcription_service = get_transcription_service()
        transcribed_text = transcription_service.transcribe_audio(audio_data)
        
        if not transcribed_text:
            bot.send_message(
                chat_id=user_id,
                text="❌ Could not understand the audio. Please try again with clearer audio."
            )
            return
        
        db.update_session(user_id, transcribed_text=transcribed_text, state="waiting_confirmation")
        
        bot.send_message(
            chat_id=user_id,
            text=f"📝 You said:\n\n\"{transcribed_text}\"\n\nIs this correct?",
            reply_markup=confirmation_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Voice processing error: {e}")
        bot.send_message(
            chat_id=user_id,
            text="❌ Error processing voice. Please try again."
        )


def handle_text_message(update: Update, session, db):
    user_id = update.message.from_user.id
    text = update.message.text.lower()
    
    if text in ["/start", "/restart"]:
        db.delete_session(user_id)
        db.create_session(user_id, "waiting_voice")
        bot.send_message(
            chat_id=user_id,
            text="🎤 Send me a voice note to create a news article."
        )
    elif text in ["/cancel", "cancel"]:
        db.delete_session(user_id)
        bot.send_message(
            chat_id=user_id,
            text="❌ Cancelled. Send a voice note to start again.",
            reply_markup=None
        )
    elif session.state == "waiting_confirmation":
        db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
        bot.send_message(
            chat_id=user_id,
            text=f"📝 You said:\n\n\"{text}\"\n\nIs this correct?",
            reply_markup=confirmation_keyboard()
        )
    else:
        bot.send_message(
            chat_id=user_id,
            text="🎤 Send me a voice note to create a news article."
        )


def handle_photo_message(update: Update, session, db):
    user_id = update.message.from_user.id
    
    if session.state != "waiting_post":
        bot.send_message(
            chat_id=user_id,
            text="Please complete the article confirmation first."
        )
        return
    
    photo = update.message.photo[-1]
    db.update_session(user_id, image_file_id=photo.file_id, state="waiting_post")
    
    post_article(update.message, session, db)


def handle_callback(callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    query = callback_query
    
    bot.answer_callback_query(query.id)
    
    db = get_db()
    session = db.get_session(user_id)
    
    if not session:
        bot.send_message(chat_id=user_id, text="Session expired. Send /start to begin.")
        return
    
    if data == "confirm_yes":
        handle_confirmation_yes(session, query, db)
    elif data == "confirm_no":
        handle_confirmation_no(session, query, db)
    elif data == "post_news":
        handle_post_news(session, query, db)
    elif data == "action_cancel":
        db.delete_session(user_id)
        bot.send_message(
            chat_id=user_id,
            text="❌ Cancelled. Send a voice note to start again.",
            reply_markup=None
        )


def handle_confirmation_yes(session, query, db):
    user_id = query.from_user.id
    
    bot.send_message(chat_id=user_id, text="✍️ Creating your article...")
    
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
        
        bot.send_message(
            chat_id=user_id,
            text=article_text,
            reply_markup=post_keyboard()
        )
        
    except Exception as e:
        logger.error(f"Article generation error: {e}")
        bot.send_message(
            chat_id=user_id,
            text="❌ Error generating article. Please try again."
        )


def handle_confirmation_no(session, query, db):
    user_id = query.from_user.id
    
    bot.send_message(
        chat_id=user_id,
        text="❌ Please send the voice note again or type your message.",
        reply_markup=cancel_keyboard()
    )
    
    db.update_session(user_id, state="waiting_voice")


def handle_post_news(session, query, db):
    user_id = query.from_user.id
    
    if not session.image_file_id:
        bot.send_message(
            chat_id=user_id,
            text="📸 Please send an image to include with the article."
        )
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
        
        file = bot.get_file(file_id=session.image_file_id)
        photo_bytes = file.download_as_bytearray()
        
        article["image"] = f"data:image/jpeg;base64,{photo_bytes.hex()}"
        
        website_api = get_website_api()
        result = website_api.post_news(article)
        
        if result.get("success"):
            news_id = result.get("id")
            url = f"{config.website_base_url}/news/{news_id}"
            
            bot.send_message(
                chat_id=user_id,
                text=f"✅ Live!\n\nLink: {url}",
                reply_markup=None
            )
            
            db.delete_session(user_id)
        else:
            bot.send_message(
                chat_id=user_id,
                text="❌ Failed to post. Please try again."
            )
            
    except Exception as e:
        logger.error(f"Post error: {e}")
        bot.send_message(
            chat_id=user_id,
            text="❌ Error posting article. Please try again."
        )


def post_article(message, session, db):
    user_id = message.from_user.id
    
    if not session.title_ar:
        bot.send_message(chat_id=user_id, text="No article to post. Please start over.")
        return
    
    try:
        photo = message.photo[-1]
        file = bot.get_file(file_id=photo.file_id)
        photo_bytes = file.download_as_bytearray()
        
        article = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
            "image": f"data:image/jpeg;base64,{photo_bytes.hex()}",
        }
        
        website_api = get_website_api()
        result = website_api.post_news(article)
        
        if result.get("success"):
            news_id = result.get("id")
            url = f"{config.website_base_url}/news/{news_id}"
            
            bot.send_message(
                chat_id=user_id,
                text=f"✅ Live!\n\nLink: {url}",
                reply_markup=None
            )
            
            db.delete_session(user_id)
        else:
            bot.send_message(
                chat_id=user_id,
                text="❌ Failed to post. Please try again."
            )
            
    except Exception as e:
        logger.error(f"Post error: {e}")
        bot.send_message(
            chat_id=user_id,
            text="❌ Error posting article. Please try again."
        )


if __name__ == "__main__":
    app.run(host=config.host, port=config.port)