from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirmation_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "✅ Yes", "callback_data": "confirm_yes"}],
            [{"text": "❌ No", "callback_data": "confirm_no"}]
        ]
    }


def post_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📸 Post", "callback_data": "post_news"}]
        ]
    }


def cancel_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "❌ Cancel", "callback_data": "action_cancel"}]
        ]
    }