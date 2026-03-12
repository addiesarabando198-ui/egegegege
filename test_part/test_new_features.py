# test_new_features.py
# Тесты для проверки новой функциональности

import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch
from telegram import Update, CallbackQuery, Message, User, Chat
from telegram.ext import ContextTypes

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_skip_question_functionality():
    """Тест функции пропуска вопроса."""
    print("\n🧪 Тестирование функции пропуска вопроса...")
    
    # Мокаем необходимые объекты
    update = Mock(spec=Update)
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Настраиваем callback_query
    query = Mock(spec=CallbackQuery)
    query.data = "skip_question:random_all"
    query.answer = AsyncMock()
    query.message = Mock(spec=Message)
    query.message.reply_text = AsyncMock()
    update.callback_query = query
    
    # Настраиваем user_data
    context.user_data = {
        'current_question_id': 'test_q_1',
        'question_test_q_1': {
            'id': 'test_q_1',
            'question_text': 'Test question',
            'answer': 'Test answer',
            'type': 'text'
        },
        'last_mode': 'random_all'
    }
    
    # Импортируем обработчик
    from test_part.handlers import skip_question
    
    try:
        # Вызываем обработчик
        result = await skip_question(update, context)
        
        # Проверяем результаты
        assert query.answer.called, "query.answer не был вызван"
        assert 'question_test_q_1' not in context.user_data, "Вопрос не был удален из контекста"
        
        print("✅ Тест пропуска вопроса пройден успешно")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка в тесте пропуска вопроса: {e}")
        return False

async def test_exam_mode_initialization():
    """Тест инициализации режима экзамена."""
    print("\n🧪 Тестирование инициализации режима экзамена...")
    
    update = Mock(spec=Update)
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    
    query = Mock(spec=CallbackQuery)
    query.from_user = Mock(spec=User)
    query.from_user.id = 12345
    query.edit_message_text = AsyncMock()
    query.message = Mock(spec=Message)
    query.message.edit_text = AsyncMock()
    update.callback_query = query
    
    context.user_data = {}
    
    from test_part.handlers import start_exam_mode
    
    try:
        # Мокаем функцию получения вопросов
        with patch('test_part.handlers.safe_cache_get_by_exam_num') as mock_get_questions:
            # Настраиваем возврат тестовых вопросов
            mock_get_questions.side_effect = lambda num: [
                {
                    'id': f'exam_q_{num}',
                    'question_text': f'Question for exam number {num}',
                    'answer': f'Answer {num}',
                    'type': 'text',
                    'exam_number': num
                }
            ] if num <= 16 else []
            
            # Мокаем choose_question
            with patch('test_part.utils.choose_question') as mock_choose:
                mock_choose.side_effect = lambda user_id, questions: questions[0] if questions else None
                
                # Вызываем обработчик
                result = await start_exam_mode(update, context)
                
                # Проверяем инициализацию
                assert context.user_data.get('exam_mode') == True, "Режим экзамена не активирован"
                assert 'exam_questions' in context.user_data, "Вопросы экзамена не инициализированы"
                assert 'exam_answers' in context.user_data, "Ответы экзамена не инициализированы"
                assert 'exam_current' in context.user_data, "Текущий вопрос не установлен"
                
                print("✅ Тест инициализации режима экзамена пройден")
                return True
                
    except Exception as e:
        print(f"❌ Ошибка в тесте режима экзамена: {e}")
        return False

async def test_exam_answer_processing():
    """Тест обработки ответов в режиме экзамена."""
    print("\n🧪 Тестирование обработки ответов в режиме экзамена...")
    
    update = Mock(spec=Update)
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    
    # Настраиваем сообщение с ответом
    message = Mock(spec=Message)
    message.text = "Правильный ответ"
    message.reply_text = AsyncMock()
    update.message = message
    
    # Настраиваем контекст экзамена
    context.user_data = {
        'exam_mode': True,
        'current_question_id': 'exam_q_1',
        'question_exam_q_1': {
            'id': 'exam_q_1',
            'answer': 'Правильный ответ',
            'type': 'text',
            'exam_position': 1
        },
        'exam_current': 1,
        'exam_questions': [
            {'id': 'exam_q_1', 'exam_position': 1}
        ],
        'exam_answers': {}
    }
    
    from test_part.handlers import check_exam_answer
    
    try:
        # Вызываем обработчик
        result = await check_exam_answer(update, context)
        
        # Проверяем сохранение ответа
        assert 'exam_q_1' in context.user_data['exam_answers'], "Ответ не сохранен"
        assert context.user_data['exam_answers']['exam_q_1']['is_correct'] == True, "Ответ не помечен как правильный"
        assert context.user_data['exam_answers']['exam_q_1']['user_answer'] == "Правильный ответ", "Ответ пользователя не сохранен"
        
        print("✅ Тест обработки ответов в режиме экзамена пройден")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка в тесте обработки ответов: {e}")
        return False

async def test_exam_results_calculation():
    """Тест подсчета результатов экзамена."""
    print("\n🧪 Тестирование подсчета результатов экзамена...")
    
    message = Mock(spec=Message)
    message.reply_text = AsyncMock()
    
    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.user_data = {
        'user_id': 12345,
        'exam_questions': [
            {'id': f'q_{i}', 'exam_position': i} for i in range(1, 17)
        ],
        'exam_answers': {
            'q_1': {'is_correct': True, 'question_num': 1},
            'q_2': {'is_correct': False, 'question_num': 2},
            'q_3': {'is_correct': True, 'question_num': 3},
            'q_4': {'is_correct': True, 'question_num': 4},
            'q_5': {'is_correct': False, 'question_num': 5},
            # Остальные пропущены
        },
        'exam_skipped': ['q_6', 'q_7', 'q_8', 'q_9', 'q_10', 'q_11', 'q_12', 'q_13', 'q_14', 'q_15', 'q_16']
    }
    
    from test_part.handlers import show_exam_results
    
    try:
        # Мокаем функции БД
        with patch('test_part.db.add_mistake') as mock_add_mistake:
            with patch('test_part.db.update_progress') as mock_update_progress:
                mock_add_mistake.return_value = AsyncMock()
                mock_update_progress.return_value = AsyncMock()
                
                # Вызываем функцию
                result = await show_exam_results(message, context)
                
                # Проверяем вызов reply_text
                assert message.reply_text.called, "Результаты не отправлены"
                
                # Получаем текст результатов
                call_args = message.reply_text.call_args
                result_text = call_args[0][0] if call_args else ""
                
                # Проверяем содержание результатов
                assert "РЕЗУЛЬТАТЫ ЭКЗАМЕНА" in result_text, "Заголовок результатов отсутствует"
                assert "3/" in result_text, "Неправильный подсчет правильных ответов"  # 3 правильных
                assert "Отвечено: 5" in result_text, "Неправильный подсчет отвеченных"
                assert "Пропущено: 11" in result_text, "Неправильный подсчет пропущенных"
                
                print("✅ Тест подсчета результатов экзамена пройден")
                return True
                
    except Exception as e:
        print(f"❌ Ошибка в тесте результатов: {e}")
        return False

async def run_all_tests():
    """Запуск всех тестов."""
    print("🚀 Запуск тестов новой функциональности модуля test_part\n")
    
    tests = [
        test_skip_question_functionality,
        test_exam_mode_initialization,
        test_exam_answer_processing,
        test_exam_results_calculation
    ]
    
    results = []
    for test in tests:
        try:
            result = await test()
            results.append(result)
        except Exception as e:
            print(f"❌ Критическая ошибка в тесте {test.__name__}: {e}")
            results.append(False)
    
    # Итоговая статистика
    passed = sum(results)
    total = len(results)
    
    print(f"\n📊 Результаты тестирования:")
    print(f"Пройдено: {passed}/{total}")
    
    if passed == total:
        print("✅ Все тесты пройдены успешно!")
    else:
        print(f"⚠️ Провалено тестов: {total - passed}")
    
    return passed == total

if __name__ == "__main__":
    # Запускаем тесты
    asyncio.run(run_all_tests())