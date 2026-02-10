"""Bot FSM states."""

from aiogram.fsm.state import State, StatesGroup


class DoCommandState(StatesGroup):
    """States for /do command flow."""

    waiting_for_input = State()  # Waiting for voice or text after /do


class ContentSeedsState(StatesGroup):
    """States for viewing seeds by number."""

    waiting_for_number = State()  # Waiting for seed number to expand
