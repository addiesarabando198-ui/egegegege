"""Клавиатуры для модуля полного варианта ЕГЭ."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from typing import Dict, Optional, Set

from .scoring import get_max_score_for_task, PART2_MAX_SCORES


# ──────────────────────────────────────────────────────────────
# Главное меню модуля
# ──────────────────────────────────────────────────────────────

def get_entry_keyboard() -> InlineKeyboardMarkup:
    """Стартовое меню модуля: Новый вариант / Продолжить."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Новый вариант", callback_data="fe_new_variant")],
        [InlineKeyboardButton("📊 Мои результаты", callback_data="fe_my_results")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")],
    ])


def get_entry_keyboard_with_continue() -> InlineKeyboardMarkup:
    """Стартовое меню с возможностью продолжения."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Продолжить вариант", callback_data="fe_continue")],
        [InlineKeyboardButton("📋 Новый вариант", callback_data="fe_new_variant")],
        [InlineKeyboardButton("📊 Мои результаты", callback_data="fe_my_results")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")],
    ])


# ──────────────────────────────────────────────────────────────
# Обзор варианта с навигацией
# ──────────────────────────────────────────────────────────────

TASK_LABELS = {
    19: "Примеры", 20: "Суждения", 21: "Графики",
    22: "Анализ", 23: "Конституция", 24: "План", 25: "Обоснование",
}


def get_overview_keyboard(
    answered: Optional[Set[int]] = None,
    current_scores: Optional[Dict[int, int]] = None,
) -> InlineKeyboardMarkup:
    """
    Клавиатура обзора варианта.

    Показывает все задания 1-16 и 17-25 с индикаторами статуса.
    """
    answered = answered or set()
    current_scores = current_scores or {}
    buttons = []

    # ── Часть 1: строки по 4 кнопки ──
    buttons.append([InlineKeyboardButton(
        "📝 Часть 1 — Тестовая", callback_data="fe_noop"
    )])
    row = []
    for num in range(1, 17):
        if num in answered:
            icon = "✔️"
        else:
            icon = str(num)
        row.append(InlineKeyboardButton(icon, callback_data=f"fe_goto_{num}"))
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # ── Часть 2: по одной кнопке на задание ──
    buttons.append([InlineKeyboardButton(
        "📝 Часть 2 — Развёрнутая", callback_data="fe_noop"
    )])
    for num in sorted(PART2_MAX_SCORES):
        label = TASK_LABELS.get(num, str(num))
        if num in answered:
            text = f"✔️ №{num} {label} — ответ дан"
        else:
            text = f"📋 №{num} {label}"
        buttons.append([InlineKeyboardButton(text, callback_data=f"fe_goto_{num}")])

    # ── Управление ──
    buttons.append([
        InlineKeyboardButton("🏁 Завершить", callback_data="fe_finish"),
        InlineKeyboardButton("⬅️ Меню", callback_data="fe_back_to_menu"),
    ])

    return InlineKeyboardMarkup(buttons)


# ──────────────────────────────────────────────────────────────
# Навигация внутри задания
# ──────────────────────────────────────────────────────────────

def get_task_nav_keyboard(current_num: int, total_tasks_list=None) -> InlineKeyboardMarkup:
    """Клавиатура навигации при ответе на конкретное задание."""
    all_nums = sorted(total_tasks_list) if total_tasks_list else (
        list(range(1, 17)) + list(range(17, 26))
    )
    idx = all_nums.index(current_num) if current_num in all_nums else -1

    row_nav = []
    if idx > 0:
        prev_num = all_nums[idx - 1]
        row_nav.append(InlineKeyboardButton("⬅️ Пред.", callback_data=f"fe_goto_{prev_num}"))
    row_nav.append(InlineKeyboardButton("📋 Обзор", callback_data="fe_overview"))
    if idx < len(all_nums) - 1:
        next_num = all_nums[idx + 1]
        row_nav.append(InlineKeyboardButton("След. ➡️", callback_data=f"fe_goto_{next_num}"))

    buttons = [
        row_nav,
        [InlineKeyboardButton("⏭ Пропустить", callback_data=f"fe_skip_{current_num}")],
    ]
    return InlineKeyboardMarkup(buttons)


def get_after_answer_keyboard(current_num: int) -> InlineKeyboardMarkup:
    """Клавиатура после ответа на задание."""
    all_nums = list(range(1, 17)) + list(range(17, 26))
    idx = all_nums.index(current_num) if current_num in all_nums else -1

    buttons = []

    row = []
    if idx < len(all_nums) - 1:
        next_num = all_nums[idx + 1]
        row.append(InlineKeyboardButton(f"➡️ К заданию {next_num}", callback_data=f"fe_goto_{next_num}"))
    buttons.append(row)

    buttons.append([
        InlineKeyboardButton("📋 Обзор варианта", callback_data="fe_overview"),
        InlineKeyboardButton("🏁 Завершить", callback_data="fe_finish"),
    ])

    return InlineKeyboardMarkup(buttons)


def get_finish_confirm_keyboard() -> InlineKeyboardMarkup:
    """Подтверждение завершения варианта."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Да, завершить", callback_data="fe_finish_confirm"),
            InlineKeyboardButton("❌ Нет, продолжить", callback_data="fe_overview"),
        ]
    ])


def get_results_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура на экране результатов."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Новый вариант", callback_data="fe_new_variant")],
        [InlineKeyboardButton("📊 Подробный разбор", callback_data="fe_detailed_review")],
        [InlineKeyboardButton("⬅️ Главное меню", callback_data="main_menu")],
    ])


# ──────────────────────────────────────────────────────────────
# Учительский режим: предпросмотр и замена заданий
# ──────────────────────────────────────────────────────────────

def get_teacher_preview_keyboard(variant_id: str) -> InlineKeyboardMarkup:
    """Клавиатура предпросмотра варианта учителем."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Назначить", callback_data=f"fe_hw_assign_{variant_id}")],
        [InlineKeyboardButton("🔄 Новый вариант", callback_data="fe_hw_regenerate")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="fe_hw_back")],
    ])


def get_teacher_task_replace_keyboard(exam_number: int) -> InlineKeyboardMarkup:
    """Кнопка замены конкретного задания учителем."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔄 Заменить задание №{exam_number}",
            callback_data=f"fe_hw_replace_{exam_number}",
        )],
        [InlineKeyboardButton("⬅️ К обзору", callback_data="fe_hw_preview")],
    ])
