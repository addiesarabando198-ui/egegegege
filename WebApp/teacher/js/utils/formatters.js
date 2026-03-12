/**
 * Утилиты для форматирования данных
 */

/**
 * Форматирует дату в читаемый вид
 * @param {string|Date} date
 * @param {boolean} includeTime - включать ли время
 * @returns {string}
 */
export function formatDate(date, includeTime = true) {
  if (!date) return '';

  const d = new Date(date);
  if (isNaN(d)) return '';

  const options = {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    ...(includeTime && {
      hour: '2-digit',
      minute: '2-digit'
    })
  };

  return new Intl.DateTimeFormat('ru-RU', options).format(d);
}

/**
 * Форматирует дату в короткий формат
 * @param {string|Date} date
 * @returns {string} - например, "29.12.2025"
 */
export function formatDateShort(date) {
  if (!date) return '';

  const d = new Date(date);
  if (isNaN(d)) return '';

  return new Intl.DateTimeFormat('ru-RU').format(d);
}

/**
 * Форматирует относительное время
 * @param {string|Date} date
 * @returns {string} - например, "2 часа назад"
 */
export function formatRelativeTime(date) {
  if (!date) return '';

  const d = new Date(date);
  if (isNaN(d)) return '';

  const now = new Date();
  const diff = now - d;

  const seconds = Math.floor(diff / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);
  const months = Math.floor(days / 30);
  const years = Math.floor(days / 365);

  if (seconds < 60) {
    return 'только что';
  } else if (minutes < 60) {
    return `${minutes} ${pluralize(minutes, 'минута', 'минуты', 'минут')} назад`;
  } else if (hours < 24) {
    return `${hours} ${pluralize(hours, 'час', 'часа', 'часов')} назад`;
  } else if (days < 30) {
    return `${days} ${pluralize(days, 'день', 'дня', 'дней')} назад`;
  } else if (months < 12) {
    return `${months} ${pluralize(months, 'месяц', 'месяца', 'месяцев')} назад`;
  } else {
    return `${years} ${pluralize(years, 'год', 'года', 'лет')} назад`;
  }
}

/**
 * Форматирует число с разделителями разрядов
 * @param {number} num
 * @returns {string} - например, "1 000"
 */
export function formatNumber(num) {
  return new Intl.NumberFormat('ru-RU').format(num);
}

/**
 * Форматирует процент
 * @param {number} value - значение от 0 до 100
 * @param {number} decimals - количество знаков после запятой
 * @returns {string} - например, "85.5%"
 */
export function formatPercent(value, decimals = 1) {
  return `${value.toFixed(decimals)}%`;
}

/**
 * Форматирует размер файла
 * @param {number} bytes
 * @returns {string} - например, "1.5 MB"
 */
export function formatFileSize(bytes) {
  if (bytes === 0) return '0 B';

  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));

  return `${(bytes / Math.pow(k, i)).toFixed(2)} ${sizes[i]}`;
}

/**
 * Форматирует имя пользователя
 * @param {Object} user - объект пользователя
 * @returns {string}
 */
export function formatUserName(user) {
  if (!user) return 'Пользователь';

  const firstName = user.first_name || user.firstName || '';
  const lastName = user.last_name || user.lastName || '';
  const username = user.username ? `@${user.username}` : '';

  if (firstName && lastName) {
    return `${firstName} ${lastName}`;
  } else if (firstName) {
    return firstName;
  } else if (username) {
    return username;
  } else {
    return 'Пользователь';
  }
}

/**
 * Форматирует username с @
 * @param {string} username
 * @returns {string}
 */
export function formatUsername(username) {
  if (!username) return '';
  return username.startsWith('@') ? username : `@${username}`;
}

/**
 * Форматирует тип задания в читаемый вид
 * @param {string} type
 * @returns {string}
 */
export function formatAssignmentType(type) {
  const types = {
    'test_part': 'Тестовая часть (1-16)',
    'task19': 'Задание 19',
    'task20': 'Задание 20',
    'task24': 'Задание 24',
    'task25': 'Задание 25',
    'mixed': 'Смешанное задание',
    'full_exam': 'Полный вариант ЕГЭ',
    'custom': 'Кастомное задание'
  };

  return types[type] || type;
}

/**
 * Форматирует статус задания
 * @param {string} status
 * @returns {string}
 */
export function formatAssignmentStatus(status) {
  const statuses = {
    'active': 'Активное',
    'completed': 'Завершено',
    'expired': 'Просрочено',
    'draft': 'Черновик'
  };

  return statuses[status] || status;
}

/**
 * Pluralize - склонение числительных
 * @param {number} count
 * @param {string} one - для 1 (например, "задание")
 * @param {string} few - для 2-4 (например, "задания")
 * @param {string} many - для 5+ (например, "заданий")
 * @returns {string}
 */
export function pluralize(count, one, few, many) {
  const mod10 = count % 10;
  const mod100 = count % 100;

  if (mod10 === 1 && mod100 !== 11) {
    return one;
  } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
    return few;
  } else {
    return many;
  }
}

/**
 * Форматирует счетчик с pluralization
 * @param {number} count
 * @param {string} one
 * @param {string} few
 * @param {string} many
 * @returns {string} - например, "5 заданий"
 */
export function formatCount(count, one, few, many) {
  return `${formatNumber(count)} ${pluralize(count, one, few, many)}`;
}

/**
 * Обрезает текст до указанной длины
 * @param {string} text
 * @param {number} maxLength
 * @param {string} suffix - суффикс для обрезанного текста
 * @returns {string}
 */
export function truncate(text, maxLength, suffix = '...') {
  if (!text || text.length <= maxLength) {
    return text;
  }

  return text.substring(0, maxLength - suffix.length) + suffix;
}

/**
 * Делает первую букву заглавной
 * @param {string} str
 * @returns {string}
 */
export function capitalize(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

/**
 * Форматирует список в строку
 * @param {Array} items
 * @param {string} separator - разделитель (по умолчанию ", ")
 * @param {string} lastSeparator - разделитель перед последним элементом (по умолчанию " и ")
 * @returns {string}
 */
export function formatList(items, separator = ', ', lastSeparator = ' и ') {
  if (!items || items.length === 0) return '';
  if (items.length === 1) return items[0];

  const allButLast = items.slice(0, -1).join(separator);
  const last = items[items.length - 1];

  return `${allButLast}${lastSeparator}${last}`;
}

/**
 * Форматирует длительность в читаемый вид
 * @param {number} milliseconds
 * @returns {string} - например, "2 часа 30 минут"
 */
export function formatDuration(milliseconds) {
  const seconds = Math.floor(milliseconds / 1000);
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const days = Math.floor(hours / 24);

  if (days > 0) {
    return `${days} ${pluralize(days, 'день', 'дня', 'дней')}`;
  } else if (hours > 0) {
    const remainingMinutes = minutes % 60;
    if (remainingMinutes > 0) {
      return `${hours} ${pluralize(hours, 'час', 'часа', 'часов')} ${remainingMinutes} ${pluralize(remainingMinutes, 'минута', 'минуты', 'минут')}`;
    }
    return `${hours} ${pluralize(hours, 'час', 'часа', 'часов')}`;
  } else if (minutes > 0) {
    return `${minutes} ${pluralize(minutes, 'минута', 'минуты', 'минут')}`;
  } else {
    return `${seconds} ${pluralize(seconds, 'секунда', 'секунды', 'секунд')}`;
  }
}

/**
 * Экранирует HTML
 * @param {string} str
 * @returns {string}
 */
export function escapeHTML(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

/**
 * Парсит HTML в текст
 * @param {string} html
 * @returns {string}
 */
export function stripHTML(html) {
  const div = document.createElement('div');
  div.innerHTML = html;
  return div.textContent || div.innerText || '';
}

/**
 * Форматирует балл/оценку
 * @param {number} score - балл
 * @param {number} maxScore - максимальный балл
 * @returns {string} - например, "15/20 (75%)"
 */
export function formatScore(score, maxScore) {
  const percent = (score / maxScore) * 100;
  return `${score}/${maxScore} (${formatPercent(percent, 0)})`;
}

/**
 * Debounce функция
 * @param {Function} func
 * @param {number} wait - время ожидания в мс
 * @returns {Function}
 */
export function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

/**
 * Throttle функция
 * @param {Function} func
 * @param {number} limit - минимальное время между вызовами в мс
 * @returns {Function}
 */
export function throttle(func, limit) {
  let inThrottle;
  return function executedFunction(...args) {
    if (!inThrottle) {
      func(...args);
      inThrottle = true;
      setTimeout(() => inThrottle = false, limit);
    }
  };
}
