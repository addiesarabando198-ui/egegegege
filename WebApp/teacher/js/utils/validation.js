/**
 * Утилиты валидации форм
 */

/**
 * Валидирует форму создания задания
 * @param {Object} state - состояние формы
 * @returns {Object} - объект с ошибками { field: 'error message' }
 */
export function validateAssignmentForm(state) {
  const errors = {};

  // Валидация типа задания
  if (!state.assignmentType) {
    errors.assignmentType = 'Выберите тип задания';
  }

  // ИСПРАВЛЕНО: Валидация модулей для ВСЕХ типов заданий, кроме custom и full_exam
  // task19, task20, task24, task25, mixed - все требуют выбора вопросов
  const needsModules = ['task19', 'task20', 'task24', 'task25', 'mixed', 'test_part'].includes(state.assignmentType);

  if (needsModules) {
    if (!state.modules || state.modules.length === 0) {
      errors.modules = 'Выберите хотя бы один вопрос';
    }

    // Проверяем каждый модуль
    if (state.modules && state.modules.length > 0) {
      state.modules.forEach((module, index) => {
        if (!module.module_code) {
          errors[`module_${index}_code`] = 'Не указан код модуля';
        }

        if (!module.selection_mode) {
          errors[`module_${index}_mode`] = 'Выберите способ отбора';
        }

        // Для конкретных вопросов проверяем их наличие
        if (module.selection_mode === 'specific') {
          if (!module.question_ids || module.question_ids.length === 0) {
            errors[`module_${index}_questions`] = 'Выберите хотя бы один вопрос';
          }
        }

        // Для случайного выбора проверяем количество
        if (module.selection_mode === 'random') {
          if (!module.question_count || module.question_count < 1) {
            errors[`module_${index}_count`] = 'Укажите количество вопросов';
          }
        }
      });
    }
  }

  // Валидация названия
  if (!state.title || state.title.trim().length === 0) {
    errors.title = 'Введите название задания';
  } else if (state.title.trim().length < 3) {
    errors.title = 'Название должно содержать минимум 3 символа';
  } else if (state.title.length > 100) {
    errors.title = 'Название не должно превышать 100 символов';
  }

  // Валидация описания
  if (state.description && state.description.length > 500) {
    errors.description = 'Описание не должно превышать 500 символов';
  }

  // Валидация учеников
  if (!state.studentIds || state.studentIds.length === 0) {
    errors.students = 'Выберите хотя бы одного ученика';
  } else if (state.studentIds.length > 100) {
    errors.students = 'Максимум 100 учеников на одно задание';
  }

  // Валидация дедлайна
  if (state.deadline) {
    const deadlineDate = new Date(state.deadline);
    const now = new Date();

    if (deadlineDate < now) {
      errors.deadline = 'Дедлайн не может быть в прошлом';
    }

    // Проверяем, что дедлайн не слишком далеко в будущем (например, больше года)
    const oneYearFromNow = new Date();
    oneYearFromNow.setFullYear(oneYearFromNow.getFullYear() + 1);

    if (deadlineDate > oneYearFromNow) {
      errors.deadline = 'Дедлайн не может быть более чем через год';
    }
  }

  return errors;
}

/**
 * Валидирует email
 * @param {string} email
 * @returns {boolean}
 */
export function validateEmail(email) {
  const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return re.test(email);
}

/**
 * Валидирует длину строки
 * @param {string} str
 * @param {number} min
 * @param {number} max
 * @returns {boolean}
 */
export function validateLength(str, min, max) {
  const length = str.trim().length;
  return length >= min && length <= max;
}

/**
 * Валидирует число в диапазоне
 * @param {number} num
 * @param {number} min
 * @param {number} max
 * @returns {boolean}
 */
export function validateRange(num, min, max) {
  return num >= min && num <= max;
}

/**
 * Валидирует URL
 * @param {string} url
 * @returns {boolean}
 */
export function validateURL(url) {
  try {
    new URL(url);
    return true;
  } catch {
    return false;
  }
}

/**
 * Валидирует дату
 * @param {string|Date} date
 * @returns {boolean}
 */
export function validateDate(date) {
  const d = new Date(date);
  return d instanceof Date && !isNaN(d);
}

/**
 * Проверяет, является ли строка пустой или содержит только пробелы
 * @param {string} str
 * @returns {boolean}
 */
export function isEmpty(str) {
  return !str || str.trim().length === 0;
}

/**
 * Санитизирует строку (удаляет потенциально опасные символы)
 * @param {string} str
 * @returns {string}
 */
export function sanitize(str) {
  return str
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .trim();
}

/**
 * Показывает ошибку на input элементе
 * @param {HTMLElement} input
 * @param {string} message
 */
export function showInputError(input, message) {
  input.classList.add('error');

  const errorElement = input.parentElement?.querySelector('.form-error');
  if (errorElement) {
    errorElement.textContent = message;
    errorElement.classList.add('show');
  }
}

/**
 * Убирает ошибку с input элемента
 * @param {HTMLElement} input
 */
export function clearInputError(input) {
  input.classList.remove('error');

  const errorElement = input.parentElement?.querySelector('.form-error');
  if (errorElement) {
    errorElement.textContent = '';
    errorElement.classList.remove('show');
  }
}

/**
 * Валидирует input в реальном времени
 * @param {HTMLElement} input
 * @param {Function} validator - функция валидации, возвращает { valid: boolean, message: string }
 */
export function attachLiveValidation(input, validator) {
  const validate = () => {
    const result = validator(input.value);

    if (result.valid) {
      clearInputError(input);
    } else if (input.value.length > 0) {
      // Показываем ошибку только если пользователь что-то ввел
      showInputError(input, result.message);
    }
  };

  // Валидация при потере фокуса
  input.addEventListener('blur', validate);

  // Валидация при вводе (с debounce)
  let timeout;
  input.addEventListener('input', () => {
    clearTimeout(timeout);
    timeout = setTimeout(validate, 500);
  });
}

/**
 * Валидатор для названия задания
 * @param {string} value
 * @returns {Object}
 */
export function titleValidator(value) {
  if (isEmpty(value)) {
    return { valid: false, message: 'Введите название задания' };
  }

  if (value.trim().length < 3) {
    return { valid: false, message: 'Минимум 3 символа' };
  }

  if (value.length > 100) {
    return { valid: false, message: 'Максимум 100 символов' };
  }

  return { valid: true, message: '' };
}

/**
 * Валидатор для описания
 * @param {string} value
 * @returns {Object}
 */
export function descriptionValidator(value) {
  if (value && value.length > 500) {
    return { valid: false, message: 'Максимум 500 символов' };
  }

  return { valid: true, message: '' };
}
