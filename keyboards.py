from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def confirmation_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Yes", callback_data="confirm_yes")],
        [InlineKeyboardButton("❌ No", callback_data="confirm_no")]
    ])


def post_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Post", callback_data="post_news")]
    ])


def cancel_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="action_cancel")]
    ])