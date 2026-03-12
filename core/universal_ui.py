"""
Универсальный модуль UI/UX компонентов для всех заданий бота.
Основан на стиле task20 для единообразия интерфейса.
"""

from typing import List, Dict, Optional, Tuple, Any
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class UniversalUIComponents:
    """Универсальные UI компоненты для всех модулей."""
    
    # Символы для прогресс-баров
    PROGRESS_CHARS = {
        'full': '█',
        'high': '▓',
        'medium': '▒',
        'low': '░',
        'empty': '░'
    }
    
    # Эмодзи для оценок
    SCORE_EMOJIS = {
        'perfect': '🌟',
        'excellent': '🎉',
        'good': '✅',
        'fair': '💡',
        'poor': '📚',
        'none': '❌'
    }
    
    # Цветовые индикаторы
    COLOR_INDICATORS = {
        'green': '🟢',
        'yellow': '🟡',
        'red': '🔴',
        'blue': '🔵',
        'white': '⚪'
    }
    
    @classmethod
    def create_progress_bar(cls, current: int, total: int, width: int = 10, 
                          show_percentage: bool = True) -> str:
        """
        Создать универсальный прогресс-бар.
        
        Args:
            current: Текущее значение
            total: Максимальное значение
            width: Ширина бара в символах
            show_percentage: Показывать ли процент
        """
        if total == 0:
            return cls.PROGRESS_CHARS['empty'] * width
        
        percentage = current / total
        filled = int(percentage * width)
        
        # Выбираем символ заполнения в зависимости от процента
        if percentage >= 0.9:
            fill_char = cls.PROGRESS_CHARS['full']
        elif percentage >= 0.7:
            fill_char = cls.PROGRESS_CHARS['high']
        elif percentage >= 0.5:
            fill_char = cls.PROGRESS_CHARS['medium']
        else:
            fill_char = cls.PROGRESS_CHARS['low']
        
        bar = fill_char * filled + cls.PROGRESS_CHARS['empty'] * (width - filled)
        
        if show_percentage:
            return f"{bar} {int(percentage * 100)}%"
        return bar
    
    @classmethod
    def create_score_visual(cls, score: int, max_score: int, 
                          use_stars: bool = True) -> str:
        """
        Визуализация оценки.
        
        Args:
            score: Полученная оценка
            max_score: Максимальная оценка
            use_stars: Использовать звезды или проценты
        """
        # Преобразуем оба значения в int для безопасности
        score = int(round(score))  # Округляем и преобразуем
        max_score = int(max_score)
        
        if use_stars:
            filled = "⭐" * score
            empty = "☆" * (max_score - score)
            return f"{filled}{empty} ({score}/{max_score})"
        else:
            percentage = (score / max_score * 100) if max_score > 0 else 0
            return f"{percentage:.0f}%"
    
    @classmethod
    def create_trend_indicator(cls, current: float, previous: float) -> str:
        """
        Индикатор тренда на основе сравнения значений.
        
        Args:
            current: Текущее значение
            previous: Предыдущее значение
        """
        if current > previous:
            return "📈 Растёт"
        elif current < previous:
            return "📉 Падает"
        else:
            return "➡️ Стабильно"
    
    @classmethod
    def format_time_spent(cls, minutes: int) -> str:
        """Форматирование времени в читаемый вид."""
        if minutes < 1:
            return "менее минуты"
        elif minutes < 60:
            return f"{minutes} мин"
        else:
            hours = minutes // 60
            mins = minutes % 60
            if mins == 0:
                return f"{hours} ч"
            return f"{hours} ч {mins} мин"
    
    @classmethod
    def format_date_relative(cls, date: datetime) -> str:
        """Относительное форматирование даты."""
        now = datetime.now()
        diff = now - date
        
        if diff.days == 0:
            if diff.seconds < 3600:
                return f"{diff.seconds // 60} мин назад"
            else:
                return f"{diff.seconds // 3600} ч назад"
        elif diff.days == 1:
            return "вчера"
        elif diff.days < 7:
            return f"{diff.days} дн назад"
        else:
            return date.strftime("%d.%m.%Y")
    
    @classmethod
    def create_achievement_badge(cls, name: str, icon: str = "🏆",
                               rarity: str = "common") -> str:
        """Создать бейдж достижения."""
        rarity_colors = {
            'common': '⚪',
            'uncommon': '🟢',
            'rare': '🔵',
            'epic': '🟣',
            'legendary': '🟡'
        }
        
        color = rarity_colors.get(rarity, '⚪')
        return f"{color} {icon} {name}"
    
    @classmethod
    def format_statistics_tree(cls, stats: Dict[str, Any]) -> str:
        """
        Форматирование статистики в виде дерева.
        
        Args:
            stats: Словарь со статистикой
        """
        lines = []
        items = list(stats.items())
        
        for i, (key, value) in enumerate(items):
            is_last = i == len(items) - 1
            prefix = "└" if is_last else "├"
            
            # Форматируем ключ
            formatted_key = key.replace('_', ' ').title()
            
            # Форматируем значение
            if isinstance(value, float):
                formatted_value = f"{value:.2f}"
            elif isinstance(value, bool):
                formatted_value = "✅" if value else "❌"
            else:
                formatted_value = str(value)
            
            lines.append(f"{prefix} {formatted_key}: {formatted_value}")
        
        return "\n".join(lines)
    
    @classmethod
    def get_color_for_score(cls, score: int, max_score: int) -> str:
        """Получить цветовой индикатор для оценки."""
        percentage = score / max_score if max_score > 0 else 0
        
        if percentage >= 0.9:
            return cls.COLOR_INDICATORS['green']
        elif percentage >= 0.7:
            return cls.COLOR_INDICATORS['yellow']
        elif percentage >= 0.5:
            return cls.COLOR_INDICATORS['blue']
        else:
            return cls.COLOR_INDICATORS['red']
    
    @classmethod
    def create_fancy_header(cls, title: str, subtitle: str = None) -> str:
        """Создает красивый заголовок с рамкой"""
        header = f"╔{'═' * (len(title) + 4)}╗\n"
        header += f"║  {title}  ║\n"
        header += f"╚{'═' * (len(title) + 4)}╝"
        
        if subtitle:
            header += f"\n\n{subtitle}"
        
        return header

class AdaptiveKeyboards:
    """Адаптивные клавиатуры, меняющиеся в зависимости от контекста."""
    
    @staticmethod
    def create_result_keyboard(score: int, max_score: int,
                             module_code: str = "task") -> InlineKeyboardMarkup:
        """
        Создать клавиатуру после проверки ответа.
        Кнопки адаптируются к результату.
        """
        buttons = []
        percentage = score / max_score if max_score > 0 else 0
        
        if percentage == 1.0:
            # Отличный результат
            buttons.append([
                InlineKeyboardButton("🎉 Новое задание", callback_data=f"{module_code}_new"),
                InlineKeyboardButton("📊 Мой прогресс", callback_data=f"{module_code}_progress")
            ])
            buttons.append([
                InlineKeyboardButton("🏆 Достижения", callback_data=f"{module_code}_achievements")
            ])
        elif percentage >= 0.6:
            # Хороший результат
            buttons.append([
                InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"{module_code}_retry"),
                InlineKeyboardButton("📝 Новое задание", callback_data=f"{module_code}_new")
            ])
            buttons.append([
                InlineKeyboardButton("💡 Посмотреть эталон", callback_data=f"{module_code}_show_ideal")
            ])
        else:
            # Плохой результат
            buttons.append([
                InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"{module_code}_retry")
            ])
            buttons.append([
                InlineKeyboardButton("📚 Изучить теорию", callback_data=f"{module_code}_theory"),
                InlineKeyboardButton("💡 Примеры", callback_data=f"{module_code}_examples")
            ])
            buttons.append([
                InlineKeyboardButton("🎯 Другое задание", callback_data=f"{module_code}_new")
            ])
        
        # Общие кнопки
        buttons.append([
            InlineKeyboardButton("⬅️ В меню", callback_data=f"{module_code}_menu"),
            InlineKeyboardButton("🏠 Главное", callback_data="to_main_menu")
        ])
        
        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def create_menu_keyboard(user_stats: Dict[str, Any],
                           module_code: str = "task") -> InlineKeyboardMarkup:
        """
        Создать главное меню модуля с индикаторами прогресса.
        """
        buttons = []
        # Найдите блок создания кнопок и измените его для модуля "test":
        if module_code == "test":
            # Практика с индикатором стрика
            practice_text = "💪 Практика"
            if user_stats.get('streak', 0) > 0:
                practice_text += f" (🔥{user_stats['streak']})"
            buttons.append([InlineKeyboardButton(practice_text, callback_data=f"{module_code}_practice")])
            
            # Работа над ошибками с счётчиком
            if user_stats.get('mistakes_count', 0) > 0:
                mistakes_text = f"🔧 Работа над ошибками ({user_stats['mistakes_count']})"
                buttons.append([InlineKeyboardButton(mistakes_text, callback_data=f"{module_code}_mistakes")])
            
            # Прогресс с процентом
            progress_text = "📊 Мой прогресс"
            if user_stats.get('progress_percent', 0) > 0:
                progress_text += f" ({user_stats['progress_percent']}%)"
            buttons.append([InlineKeyboardButton(progress_text, callback_data=f"{module_code}_progress")])
            
            # Сбросить прогресс вместо настроек
            buttons.append([InlineKeyboardButton("🔄 Сбросить прогресс", callback_data=f"{module_code}_reset_confirm")])
            
            # Главное меню
            buttons.append([InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")])
        else:
            # Практика с индикатором стрика
            practice_text = "💪 Практика"
            if user_stats.get('streak', 0) > 0:
                practice_text += f" (🔥{user_stats['streak']})"
            buttons.append([InlineKeyboardButton(practice_text, callback_data=f"{module_code}_practice")])
            
            # Теория с индикатором новизны
            theory_text = "📚 Теория и советы"
            if user_stats.get('total_attempts', 0) == 0:
                theory_text += " 🆕"
            buttons.append([InlineKeyboardButton(theory_text, callback_data=f"{module_code}_theory")])
            
            # Банк примеров/эталонов
            examples_text = "🏦 Банк эталонов"
            if user_stats.get('examples_viewed', 0) == 0:
                examples_text += " 💡"
            buttons.append([InlineKeyboardButton(examples_text, callback_data=f"{module_code}_examples")])
            
            # Работа над ошибками с счётчиком
            if user_stats.get('mistakes_count', 0) > 0:
                mistakes_text = f"🔧 Работа над ошибками ({user_stats['mistakes_count']})"
                buttons.append([InlineKeyboardButton(mistakes_text, callback_data=f"{module_code}_mistakes")])
            
            # Прогресс с процентом
            progress_text = "📊 Мой прогресс"
            if user_stats.get('progress_percent', 0) > 0:
                progress_text += f" ({user_stats['progress_percent']}%)"
            buttons.append([InlineKeyboardButton(progress_text, callback_data=f"{module_code}_progress")])
            
            # Настройки и главное меню
            buttons.extend([
                [InlineKeyboardButton("⚙️ Настройки", callback_data=f"{module_code}_settings")],
                [InlineKeyboardButton("🏠 Главное меню", callback_data="to_main_menu")]
            ])
        
        return InlineKeyboardMarkup(buttons)
    
    @staticmethod
    def create_progress_keyboard(has_detailed_stats: bool = False,
                               can_export: bool = False,
                               module_code: str = "task") -> InlineKeyboardMarkup:
        """
        Создать клавиатуру для экрана прогресса.
        
        Args:
            has_detailed_stats: Есть ли детальная статистика
            can_export: Можно ли экспортировать результаты
            module_code: Код модуля для callback_data
        """
        buttons = []
        
        if has_detailed_stats:
            buttons.append([
                InlineKeyboardButton("📈 Детальная статистика", 
                                   callback_data=f"{module_code}_detailed_progress")  # ИСПРАВЛЕНО!
            ])
        
        if can_export:
            buttons.append([
                InlineKeyboardButton("📤 Экспорт результатов", 
                                   callback_data=f"{module_code}_export")
            ])
        
        buttons.extend([
            [
                InlineKeyboardButton("🔄 Сбросить прогресс", 
                                   callback_data=f"{module_code}_reset_confirm"),
                InlineKeyboardButton("💪 Продолжить", 
                                   callback_data=f"{module_code}_practice")
            ],
            [InlineKeyboardButton("⬅️ Назад", callback_data=f"{module_code}_menu")]
        ])
        
        return InlineKeyboardMarkup(buttons)


class MessageFormatter:
    """Форматирование сообщений в едином стиле."""
    
    @staticmethod
    def format_result_message(score: int, max_score: int, topic: str,
                            details: Optional[Dict] = None) -> str:
        """
        Форматирование сообщения с результатом.
        
        Args:
            score: Полученный балл
            max_score: Максимальный балл
            topic: Название темы
            details: Дополнительные детали для отображения
        """
        percentage = score / max_score if max_score > 0 else 0
        
        # Заголовок в зависимости от результата
        if percentage == 1.0:
            header = "🎉 <b>Отличный результат!</b>"
            emoji = "🌟"
        elif percentage >= 0.8:
            header = "👍 <b>Хороший результат!</b>"
            emoji = "✅"
        elif percentage >= 0.6:
            header = "📝 <b>Неплохо, но есть над чем поработать</b>"
            emoji = "💡"
        else:
            header = "❌ <b>Нужно больше практики</b>"
            emoji = "📚"
        
        # Визуализация оценки
        score_visual = UniversalUIComponents.create_score_visual(score, max_score)
        
        text = f"""{header}

<b>Тема:</b> {topic}
<b>Результат:</b> {score_visual}

{emoji} <b>Анализ:</b>"""
        
        # Добавляем детали, если есть
        if details:
            for key, value in details.items():
                if value:
                    text += f"\n• {key}: {value}"
        
        # Рекомендации в зависимости от оценки
        if percentage < 1.0:
            text += "\n\n💡 <b>Рекомендация:</b> "
            if percentage < 0.3:
                text += "Изучите теорию и примеры по этой теме"
            elif percentage < 0.6:
                text += "Обратите внимание на типичные ошибки"
            else:
                text += "Вы на правильном пути! Попробуйте ещё раз для закрепления"
        
        return text
    
    @staticmethod
    def format_progress_message(stats: Dict[str, Any], module_name: str) -> str:
        """
        Форматирование сообщения с прогрессом.
        
        Args:
            stats: Статистика пользователя
            module_name: Название модуля
        """
        # Прогресс-бар
        progress_bar = UniversalUIComponents.create_progress_bar(
            stats.get('completed', 0),
            stats.get('total', 1)
        )
        
        # Форматирование времени
        time_spent = UniversalUIComponents.format_time_spent(
            stats.get('total_time', 0)
        )
        
        # Тренд
        if 'trend' in stats:
            trend = UniversalUIComponents.create_trend_indicator(
                stats.get('current_average', 0),
                stats.get('previous_average', 0)
            )
        else:
            trend = "➡️ Начало пути"
        
        text = f"""📊 <b>Ваш прогресс по {module_name}</b>

<b>📈 Общая статистика:</b>
{UniversalUIComponents.format_statistics_tree({
    'Выполнено заданий': stats.get('total_attempts', 0),
    'Средний балл': f"{stats.get('average_score', 0):.2f}",
    'Изучено тем': f"{stats.get('completed', 0)}/{stats.get('total', 0)}",
    'Время практики': time_spent,
    'Тренд': trend
})}

<b>🎯 Прогресс по темам:</b>
{progress_bar}"""
        
        # Добавляем топ результаты, если есть
        if 'top_results' in stats and stats['top_results']:
            text += "\n\n<b>🏆 Лучшие результаты:</b>"
            for i, result in enumerate(stats['top_results'][:3], 1):
                score_visual = UniversalUIComponents.create_score_visual(
                    result['score'],
                    result['max_score']
                )
                text += f"\n{i}. {result['topic']}: {score_visual}"
        
        # Персональные рекомендации
        avg_score = stats.get('average_score', 0)
        if avg_score > 0:
            text += "\n\n💡 <b>Рекомендация:</b> "
            if avg_score < 2:
                text += "Уделите больше внимания теории перед практикой"
            elif avg_score < 2.5:
                text += "Вы на правильном пути! Продолжайте практиковаться"
            else:
                text += "Отличная работа! Попробуйте более сложные темы"
        
        return text
    
    @staticmethod
    def format_welcome_message(module_name: str, is_new_user: bool = True) -> str:
        """Приветственное сообщение модуля."""
        if is_new_user:
            return f"""👋 <b>Добро пожаловать в {module_name}!</b>

Здесь вы научитесь выполнять это задание на максимальный балл.

<b>Что вас ждёт:</b>
• 📚 Пошаговое изучение всех типов заданий
• 🎯 Персональные рекомендации
• 🏅 Система достижений и мотивации
• 📈 Детальная статистика прогресса

Готовы начать? Выберите режим в меню!"""
        else:
            return f"""👋 <b>С возвращением!</b>

Продолжим подготовку к {module_name}.
Выберите режим работы:"""


# Экспорт компонентов
__all__ = [
    'UniversalUIComponents',
    'AdaptiveKeyboards',
    'MessageFormatter'
]