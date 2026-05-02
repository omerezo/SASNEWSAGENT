import os
import re
import time
import base64
import logging
import requests
from flask import Flask, request, jsonify
from config import config
from db import get_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _validate_env():
    """Warn (not crash) if critical env vars are missing, so misconfig is visible in logs."""
    missing = []
    if not config.telegram_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not config.database_url:
        missing.append("DATABASE_URL")
    if missing:
        logger.warning(f"Missing required env vars: {', '.join(missing)}")


_validate_env()

app = Flask(__name__)
TELEGRAM_API = f"https://api.telegram.org/bot{config.telegram_token}"


# --- Telegram HTTP layer (timeouts + light retry) -----------------------------

def _post_telegram(endpoint, json_data, timeout=10, retries=2):
    """POST to Telegram with timeout + retry on transient (5xx / network) errors."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(f"{TELEGRAM_API}/{endpoint}", json=json_data, timeout=timeout)
            if resp.status_code < 500:
                return resp
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.exceptions.RequestException as e:
            last_err = str(e)
        if attempt < retries:
            time.sleep(0.5 * (attempt + 1))
    logger.error(f"Telegram {endpoint} failed after retries: {last_err}")
    return None


def send_message(chat_id, text, reply_markup=None):
    data = {"chat_id": chat_id, "text": text}
    if reply_markup:
        data["reply_markup"] = reply_markup
    _post_telegram("sendMessage", data, timeout=10)


def answer_callback_query(query_id, text=None):
    try:
        data = {"callback_query_id": query_id}
        if text:
            data["text"] = text
        _post_telegram("answerCallbackQuery", data, timeout=5, retries=1)
    except Exception as e:
        logger.error(f"answer_callback_query error: {e}")


def get_file(file_id):
    resp = _post_telegram("getFile", {"file_id": file_id}, timeout=10)
    if not resp:
        return {}
    try:
        return resp.json().get("result", {}) or {}
    except Exception as e:
        logger.error(f"get_file parse error: {e}")
        return {}


def download_file(file_path):
    if not file_path:
        return None
    try:
        resp = requests.get(
            f"https://api.telegram.org/file/bot{config.telegram_token}/{file_path}",
            timeout=30,
        )
        if resp.status_code != 200:
            logger.error(f"download_file HTTP {resp.status_code}")
            return None
        return resp.content
    except requests.exceptions.RequestException as e:
        logger.error(f"download_file error: {e}")
        return None


# --- Keyboards ---------------------------------------------------------------

def input_type_keyboard():
    return {"inline_keyboard": [
        [{"text": "\U0001f3a4 Voice", "callback_data": "input_voice"}],
        [{"text": "\U0001f4dd Text", "callback_data": "input_text"}]
    ]}


def confirmation_keyboard():
    return {"inline_keyboard": [
        [{"text": "✏️ Edit", "callback_data": "edit_text"}],
        [{"text": "✅ Yes", "callback_data": "confirm_yes"}],
        [{"text": "❌ No", "callback_data": "confirm_no"}]
    ]}


def post_keyboard():
    return {"inline_keyboard": [
        [{"text": "✏️ Edit Article", "callback_data": "edit_article"}],
        [{"text": "\U0001f4f8 Post with Image", "callback_data": "post_news"}]
    ]}


# Telegram caps a single message at 4096 chars; trim with a clear marker if exceeded.
_TG_MAX = 4000


def _truncate(text, limit=_TG_MAX):
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n\n… (تم الاختصار)"


def _send_article_preview(chat_id, article):
    """Send the full article (AR + EN) so the user can read it. Buttons on the EN message."""
    ar = (
        f"\U0001f4f0 {article.get('title_ar','')}\n\n"
        f"{article.get('content_ar','')}\n\n"
        f"\U0001f4cc {article.get('excerpt_ar','')}"
    )
    en = (
        f"\U0001f4f0 {article.get('title_en','')}\n\n"
        f"{article.get('content_en','')}\n\n"
        f"\U0001f4cc {article.get('excerpt_en','')}"
    )
    send_message(chat_id, _truncate(ar))
    send_message(chat_id, _truncate(en), reply_markup=post_keyboard())


# --- Small helpers -----------------------------------------------------------

def _send_confirmation(chat_id, text):
    send_message(
        chat_id,
        f"\U0001f4dd You said:\n\n\"{text}\"\n\nIs this correct?",
        reply_markup=confirmation_keyboard(),
    )


def _normalize_command(text):
    """Lowercase + strip @bot suffix from commands, e.g. '/start@MyBot' -> '/start'."""
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"^(/[a-z_]+)@\w+", r"\1", t)
    return t


GROUP_TRIGGERS = [".news", "خبر", "write article", "create news", "breaking"]
GROUP_STOP = {"stop", "done", "finished", "cancel", "انهاء", "الغاء"}


def _is_stop_command(text_lower):
    """Match 'stop' etc. only as standalone tokens - avoids 'stopwatch', 'cancellation'."""
    if not text_lower:
        return False
    tokens = re.split(r"\W+", text_lower, flags=re.UNICODE)
    return any(tok in GROUP_STOP for tok in tokens if tok)


def _is_triggered(text_lower):
    if not text_lower:
        return False
    return any(trig in text_lower for trig in GROUP_TRIGGERS)


# --- Routes ------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def webhook():
    """Always return 200 - never let an exception trigger Telegram retry storms."""
    try:
        data = request.get_json(force=True, silent=True) or {}
        if "callback_query" in data:
            handle_callback(data["callback_query"])
        elif "message" in data:
            handle_message(data["message"])
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
    return jsonify({"ok": True})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/", methods=["GET", "POST"])
def root():
    return jsonify({"status": "ok"})


# --- Handlers ----------------------------------------------------------------

def handle_message(msg):
    try:
        user_id = msg["from"]["id"]
        chat_id = msg.get("chat", {}).get("id")
        is_group = chat_id and chat_id != user_id
        target_chat = chat_id

        logger.info(f"Message: user={user_id}, chat={chat_id}, is_group={is_group}")

        if is_group:
            text = msg.get("text", "") or ""
            text_lower = text.lower()

            if _is_stop_command(text_lower):
                db = get_db()
                if db.get_session(user_id):
                    db.delete_session(user_id)
                    send_message(chat_id, "✅ Done. Send .news to start again.")
                return

            entities = msg.get("entities", []) or []
            mentioned = any(ent.get("type") in ["mention", "bot_command"] for ent in entities)
            reply_to = msg.get("reply_to_message") or {}
            is_reply_to_bot = bool((reply_to.get("from") or {}).get("is_bot"))
            triggered = _is_triggered(text_lower)

            if not (triggered or mentioned or is_reply_to_bot):
                # Any active session means the user is mid-flow - process their message regardless of state.
                db = get_db()
                session = db.get_session(user_id)
                if not session:
                    return

            if triggered:
                db = get_db()
                if db.get_session(user_id):
                    db.delete_session(user_id)
                db.create_session(user_id, "waiting_input_type")
                send_message(chat_id, "\U0001f3a4 Choose input type:", reply_markup=input_type_keyboard())
                return

        db = get_db()
        session = db.get_session(user_id)

        if not session:
            db.create_session(user_id, "waiting_input_type")
            send_message(target_chat, "\U0001f3a4 Choose input type:", reply_markup=input_type_keyboard())
            return

        if session.state == "waiting_input_type":
            if "voice" in msg:
                handle_voice(user_id, target_chat, msg["voice"], session, db)
            elif "text" in msg:
                handle_text_input(user_id, target_chat, msg["text"], session, db)
            return

        if "voice" in msg:
            handle_voice(user_id, target_chat, msg["voice"], session, db)
        elif "text" in msg:
            handle_text(user_id, target_chat, msg["text"], session, db)
        elif "photo" in msg:
            handle_photo(user_id, target_chat, msg["photo"], session, db)
    except Exception as e:
        logger.error(f"handle_message error: {e}", exc_info=True)


def handle_text_input(user_id, chat_id, text, session, db):
    """First text message received while in 'waiting_input_type' state."""
    db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
    _send_confirmation(chat_id, text)


def handle_voice(user_id, chat_id, voice, session, db):
    try:
        send_message(chat_id, "\U0001f3a4 Processing...")
        file_info = get_file(voice["file_id"])
        file_path = file_info.get("file_path")
        if not file_path:
            send_message(chat_id, "❌ Could not download audio.")
            return

        audio_data = download_file(file_path)
        if not audio_data:
            send_message(chat_id, "❌ Could not download audio.")
            return

        from services.transcription import get_transcription_service
        transcribed = get_transcription_service().transcribe_audio(audio_data)

        if not transcribed:
            send_message(chat_id, "❌ Could not understand.")
            return

        db.update_session(user_id, transcribed_text=transcribed, state="waiting_confirmation")
        _send_confirmation(chat_id, transcribed)
    except Exception as e:
        logger.error(f"Voice error: {e}", exc_info=True)
        send_message(chat_id, "❌ Error processing voice.")


def handle_text(user_id, chat_id, text, session, db):
    cmd = _normalize_command(text)

    if cmd in ("/start", "/restart"):
        db.delete_session(user_id)
        db.create_session(user_id, "waiting_input_type")
        send_message(chat_id, "\U0001f3a4 Choose input type:", reply_markup=input_type_keyboard())
        return

    if cmd in ("/cancel", "cancel", "انهاء", "الغاء"):
        db.delete_session(user_id)
        db.create_session(user_id, "waiting_input_type")
        send_message(chat_id, "✅ Done. Send .news to start again.")
        return

    # User is refining an already-generated article with free-text instructions.
    if session.state == "editing_article":
        handle_edit_article(user_id, chat_id, text, session, db)
        return

    if session.state in ("waiting_input_type", "waiting_text", "waiting_voice",
                          "editing_text", "waiting_confirmation"):
        db.update_session(user_id, transcribed_text=text, state="waiting_confirmation")
        _send_confirmation(chat_id, text)
        return

    send_message(chat_id, "\U0001f3a4 Send .news to start or mention me.")


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
    msg = callback.get("message", {}) or {}
    chat_id = (msg.get("chat") or {}).get("id") or user_id
    data = callback["data"]
    query_id = callback["id"]

    answer_callback_query(query_id)

    db = get_db()
    session = db.get_session(user_id)

    if data in ("input_voice", "input_text"):
        if not session:
            session = db.create_session(user_id, "waiting_input_type")
        if data == "input_voice":
            send_message(chat_id, "\U0001f3a4 Send voice note or type message:")
            db.update_session(user_id, state="waiting_voice")
        else:
            send_message(chat_id, "\U0001f4dd Type your news content:")
            db.update_session(user_id, state="waiting_text")
        return

    if not session:
        send_message(chat_id, "Send .news to start.")
        return

    if data == "edit_text":
        send_message(chat_id, f"✏️ Current:\n{session.transcribed_text}\n\nSend corrected:")
        db.update_session(user_id, state="editing_text")
    elif data == "confirm_yes":
        handle_confirm_yes(user_id, chat_id, session, db)
    elif data == "confirm_no":
        send_message(chat_id, "❌ Send again.")
        db.update_session(user_id, state="waiting_input_type")
    elif data == "edit_article":
        if session.state != "waiting_post" or not session.title_ar:
            send_message(chat_id, "Nothing to edit yet.")
            return
        send_message(
            chat_id,
            "✏️ What would you like to change?\n"
            "Send your instructions in Arabic or English. Examples:\n"
            "- make it shorter / اجعله أقصر\n"
            "- change the title to ...\n"
            "- add detail about the medals",
        )
        db.update_session(user_id, state="editing_article")
    elif data == "post_news":
        send_message(chat_id, "\U0001f4f8 Send an image.")


def handle_confirm_yes(user_id, chat_id, session, db):
    try:
        send_message(chat_id, "✍️ Creating article...")
        from services.article import get_article_service
        article = get_article_service().generate_article(session.transcribed_text)

        db.update_session(
            user_id,
            title_ar=article.get("title_ar"),
            title_en=article.get("title_en"),
            content_ar=article.get("content_ar"),
            content_en=article.get("content_en"),
            excerpt_ar=article.get("excerpt_ar"),
            excerpt_en=article.get("excerpt_en"),
            state="waiting_post",
        )

        _send_article_preview(chat_id, article)
    except Exception as e:
        logger.error(f"Article error: {e}", exc_info=True)
        send_message(chat_id, "❌ Error generating article.")


def handle_edit_article(user_id, chat_id, edit_instructions, session, db):
    """Refine the existing article using user's edit instructions, then re-show it."""
    if not session.title_ar:
        send_message(chat_id, "Nothing to edit yet. Send .news to start.")
        return
    try:
        send_message(chat_id, "✍️ Updating article...")
        from services.article import get_article_service
        previous = {
            "title_ar": session.title_ar,
            "title_en": session.title_en,
            "content_ar": session.content_ar,
            "content_en": session.content_en,
            "excerpt_ar": session.excerpt_ar,
            "excerpt_en": session.excerpt_en,
        }
        article = get_article_service().refine_article(
            transcribed_text=session.transcribed_text or "",
            previous_article=previous,
            edit_instructions=edit_instructions,
        )

        db.update_session(
            user_id,
            title_ar=article.get("title_ar"),
            title_en=article.get("title_en"),
            content_ar=article.get("content_ar"),
            content_en=article.get("content_en"),
            excerpt_ar=article.get("excerpt_ar"),
            excerpt_en=article.get("excerpt_en"),
            state="waiting_post",
        )

        _send_article_preview(chat_id, article)
    except Exception as e:
        logger.error(f"Article edit error: {e}", exc_info=True)
        send_message(chat_id, "❌ Error updating article. Try again or tap Post with Image.")


def post_article(user_id, chat_id, file_id, session, db):
    try:
        file_info = get_file(file_id)
        photo_data = download_file(file_info.get("file_path"))
        if not photo_data:
            send_message(chat_id, "❌ Could not download image.")
            return

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
            url = f"{config.website_base_url}/news"
            send_message(chat_id, f"✅ Posted!\n{url}")
            db.delete_session(user_id)
        else:
            send_message(chat_id, "❌ Failed to post.")
    except Exception as e:
        logger.error(f"Post error: {e}", exc_info=True)
        send_message(chat_id, "❌ Error posting.")


if __name__ == "__main__":
    app.run(host=config.host, port=config.port)
