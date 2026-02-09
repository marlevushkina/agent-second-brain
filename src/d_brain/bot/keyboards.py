"""Reply keyboards for Telegram bot."""

from aiogram.types import ReplyKeyboardMarkup
from aiogram.utils.keyboard import ReplyKeyboardBuilder


def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard with common commands."""
    builder = ReplyKeyboardBuilder()
    # First row: main commands
    builder.button(text="📊 Статус")
    builder.button(text="⚙️ Обработать")
    builder.button(text="📅 Неделя")
    # Second row: additional
    builder.button(text="✨ Запрос")
    builder.button(text="❓ Помощь")
    # Third row: content
    builder.button(text="🌱 Контент")
    builder.adjust(3, 2, 1)  # 3 in first row, 2 in second, 1 in third
    return builder.as_markup(resize_keyboard=True, is_persistent=True)
