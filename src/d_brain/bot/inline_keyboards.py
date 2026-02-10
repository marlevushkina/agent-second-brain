"""Inline keyboards for content and plan sub-menus."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def content_menu_keyboard() -> InlineKeyboardMarkup:
    """Inline menu for content seeds."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои seeds", callback_data="content:my_seeds")
    builder.button(text="🔄 Новые seeds", callback_data="content:new_seeds")
    builder.adjust(1)
    return builder.as_markup()


def plan_menu_keyboard() -> InlineKeyboardMarkup:
    """Inline menu for content plan."""
    builder = InlineKeyboardBuilder()
    builder.button(text="👁 Текущий", callback_data="plan:current")
    builder.button(text="🔄 Новый план", callback_data="plan:new")
    builder.button(text="🔄 Сверить с каналом", callback_data="plan:reconcile")
    builder.adjust(1)
    return builder.as_markup()
