def confirmation_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "✏️ Edit Text", "callback_data": "edit_text"}],
            [{"text": "✅ Yes", "callback_data": "confirm_yes"}],
            [{"text": "❌ No", "callback_data": "confirm_no"}]
        ]
    }


def post_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "✏️ Edit Article", "callback_data": "edit_article"}],
            [{"text": "📸 Post with Image", "callback_data": "post_news"}]
        ]
    }


def cancel_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "❌ Cancel", "callback_data": "action_cancel"}]
        ]
    }