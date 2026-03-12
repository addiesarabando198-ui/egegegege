/**
 * Утилиты для работы с UI элементами
 */

/**
 * Показывает toast уведомление
 * @param {string} message
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {number} duration - длительность в мс
 */
export function showToast(message, type = 'info', duration = 3000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  // Добавляем иконку
  const icon = getToastIcon(type);
  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-message">${message}</span>
  `;

  container.appendChild(toast);

  // Автоматически удаляем через duration
  setTimeout(() => {
    toast.style.animation = 'slideOutRight 0.3s ease';
    setTimeout(() => {
      container.removeChild(toast);
    }, 300);
  }, duration);
}

/**
 * Возвращает иконку для toast
 * @param {string} type
 * @returns {string}
 */
function getToastIcon(type) {
  const icons = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ'
  };
  return icons[type] || icons.info;
}

/**
 * Показывает экран загрузки
 * @param {string} message
 */
export function showLoadingScreen(message = 'Загрузка...') {
  let screen = document.getElementById('loading-screen');

  if (!screen) {
    screen = document.createElement('div');
    screen.id = 'loading-screen';
    screen.className = 'loading-screen';
    document.body.appendChild(screen);
  }

  screen.innerHTML = `
    <div class="spinner"></div>
    <p>${message}</p>
  `;

  screen.style.display = 'flex';
}

/**
 * Скрывает экран загрузки
 */
export function hideLoadingScreen() {
  const screen = document.getElementById('loading-screen');
  if (screen) {
    screen.style.display = 'none';
  }
}

/**
 * Показывает модальное окно
 * @param {string} id - ID модального окна
 */
export function showModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.style.display = 'flex';
    document.body.style.overflow = 'hidden';
  }
}

/**
 * Скрывает модальное окно
 * @param {string} id - ID модального окна
 */
export function hideModal(id) {
  const modal = document.getElementById(id);
  if (modal) {
    modal.style.display = 'none';
    document.body.style.overflow = '';
  }
}

/**
 * Создает и показывает кастомное модальное окно
 * @param {Object} options
 */
export function createModal(options) {
  const {
    title,
    content,
    onConfirm,
    onCancel,
    confirmText = 'OK',
    cancelText = 'Отмена',
    showCancel = true
  } = options;

  // Создаем модальное окно
  const modal = document.createElement('div');
  modal.className = 'modal';
  modal.style.display = 'flex';

  modal.innerHTML = `
    <div class="modal-content">
      <div class="modal-header">
        <h2>${title}</h2>
        <button class="close-btn" id="modal-close">×</button>
      </div>
      <div class="modal-body">
        ${content}
      </div>
      <div class="modal-footer">
        ${showCancel ? `<button class="btn-secondary" id="modal-cancel">${cancelText}</button>` : ''}
        <button class="btn-primary" id="modal-confirm">${confirmText}</button>
      </div>
    </div>
  `;

  document.body.appendChild(modal);
  document.body.style.overflow = 'hidden';

  // Обработчики
  const closeBtn = modal.querySelector('#modal-close');
  const confirmBtn = modal.querySelector('#modal-confirm');
  const cancelBtn = modal.querySelector('#modal-cancel');

  const removeModal = () => {
    document.body.removeChild(modal);
    document.body.style.overflow = '';
  };

  closeBtn?.addEventListener('click', () => {
    removeModal();
    onCancel?.();
  });

  confirmBtn?.addEventListener('click', () => {
    removeModal();
    onConfirm?.();
  });

  cancelBtn?.addEventListener('click', () => {
    removeModal();
    onCancel?.();
  });

  // Закрытие по клику на фон
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      removeModal();
      onCancel?.();
    }
  });

  return modal;
}

/**
 * Показывает подтверждение
 * @param {string} message
 * @returns {Promise<boolean>}
 */
export function confirm(message) {
  return new Promise((resolve) => {
    createModal({
      title: 'Подтверждение',
      content: `<p>${message}</p>`,
      onConfirm: () => resolve(true),
      onCancel: () => resolve(false)
    });
  });
}

/**
 * Устанавливает состояние кнопки
 * @param {HTMLElement} button
 * @param {boolean} loading
 * @param {string} loadingText
 */
export function setButtonLoading(button, loading, loadingText = 'Загрузка...') {
  if (!button) return;

  if (loading) {
    button.dataset.originalText = button.textContent;
    button.textContent = loadingText;
    button.disabled = true;
  } else {
    button.textContent = button.dataset.originalText || button.textContent;
    button.disabled = false;
    delete button.dataset.originalText;
  }
}

/**
 * Скроллит к элементу
 * @param {HTMLElement|string} element - элемент или селектор
 * @param {Object} options
 */
export function scrollTo(element, options = {}) {
  const el = typeof element === 'string'
    ? document.querySelector(element)
    : element;

  if (!el) return;

  el.scrollIntoView({
    behavior: options.behavior || 'smooth',
    block: options.block || 'start',
    inline: options.inline || 'nearest'
  });
}

/**
 * Показывает пустое состояние
 * @param {HTMLElement} container
 * @param {Object} options
 */
export function showEmptyState(container, options = {}) {
  const {
    icon = '📭',
    title = 'Ничего не найдено',
    description = ''
  } = options;

  container.innerHTML = `
    <div class="empty-state">
      <div class="empty-state-icon">${icon}</div>
      <div class="empty-state-text">${title}</div>
      ${description ? `<div class="empty-state-hint">${description}</div>` : ''}
    </div>
  `;
}

/**
 * Создает spinner элемент
 * @returns {HTMLElement}
 */
export function createSpinner() {
  const spinner = document.createElement('div');
  spinner.className = 'spinner';
  return spinner;
}

/**
 * Обновляет индикатор прогресса
 * @param {number} current - текущий шаг (1-5)
 * @param {number} total - всего шагов
 */
export function updateProgress(current, total = 5) {
  for (let i = 1; i <= total; i++) {
    const step = document.querySelector(`.progress-step[data-step="${i}"]`);
    if (!step) continue;

    step.classList.remove('completed', 'active');

    if (i < current) {
      step.classList.add('completed');
    } else if (i === current) {
      step.classList.add('active');
    }
  }
}

/**
 * Копирует текст в буфер обмена
 * @param {string} text
 * @returns {Promise<boolean>}
 */
export async function copyToClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    showToast('Скопировано в буфер обмена', 'success');
    return true;
  } catch (error) {
    console.error('Failed to copy:', error);
    showToast('Ошибка копирования', 'error');
    return false;
  }
}

/**
 * Создает элемент из HTML строки
 * @param {string} html
 * @returns {HTMLElement}
 */
export function createElementFromHTML(html) {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  return template.content.firstChild;
}

/**
 * Показывает/скрывает элемент
 * @param {HTMLElement|string} element
 * @param {boolean} show
 */
export function toggle(element, show) {
  const el = typeof element === 'string'
    ? document.querySelector(element)
    : element;

  if (!el) return;

  if (show) {
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
}
