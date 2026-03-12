/**
 * Модуль аутентификации через Telegram WebApp
 * Обеспечивает безопасную аутентификацию учителя
 */

class TelegramAuth {
  constructor() {
    this.tg = window.Telegram?.WebApp;
    this.initData = null;
    this.user = null;
  }

  /**
   * Инициализация Telegram WebApp
   * @returns {boolean} - успешность инициализации
   */
  init() {
    if (!this.tg) {
      console.error('Telegram WebApp SDK не загружен');
      return false;
    }

    try {
      this.tg.ready();
      this.tg.expand();

      // Получаем initData для аутентификации на backend
      this.initData = this.tg.initData;

      // Получаем информацию о пользователе
      this.user = this.tg.initDataUnsafe?.user;

      if (!this.initData || !this.user) {
        console.error('Не удалось получить данные пользователя');
        return false;
      }

      // Применяем тему Telegram
      this.applyTheme();

      console.log('Telegram WebApp инициализирован', {
        userId: this.user.id,
        firstName: this.user.first_name
      });

      return true;
    } catch (error) {
      console.error('Ошибка инициализации Telegram WebApp:', error);
      return false;
    }
  }

  /**
   * Применяет цветовую схему Telegram
   */
  applyTheme() {
    if (!this.tg) return;

    const themeParams = this.tg.themeParams;
    const root = document.documentElement;

    // Применяем переменные темы
    if (themeParams.bg_color) {
      root.style.setProperty('--tg-theme-bg-color', themeParams.bg_color);
    }
    if (themeParams.text_color) {
      root.style.setProperty('--tg-theme-text-color', themeParams.text_color);
    }
    if (themeParams.hint_color) {
      root.style.setProperty('--tg-theme-hint-color', themeParams.hint_color);
    }
    if (themeParams.link_color) {
      root.style.setProperty('--tg-theme-link-color', themeParams.link_color);
    }
    if (themeParams.button_color) {
      root.style.setProperty('--tg-theme-button-color', themeParams.button_color);
    }
    if (themeParams.button_text_color) {
      root.style.setProperty('--tg-theme-button-text-color', themeParams.button_text_color);
    }
    if (themeParams.secondary_bg_color) {
      root.style.setProperty('--tg-theme-secondary-bg-color', themeParams.secondary_bg_color);
    }
  }

  /**
   * Получает initData для отправки на backend
   * @returns {string}
   */
  getInitData() {
    return this.initData;
  }

  /**
   * Получает информацию о текущем пользователе
   * @returns {Object}
   */
  getUser() {
    return this.user;
  }

  /**
   * Получает ID пользователя
   * @returns {number}
   */
  getUserId() {
    return this.user?.id;
  }

  /**
   * Получает имя пользователя
   * @returns {string}
   */
  getUserName() {
    const user = this.user;
    if (!user) return 'Пользователь';

    return user.first_name + (user.last_name ? ' ' + user.last_name : '');
  }

  /**
   * Показывает alert через Telegram
   * @param {string} message
   */
  showAlert(message) {
    if (this.tg?.showAlert) {
      this.tg.showAlert(message);
    } else {
      alert(message);
    }
  }

  /**
   * Показывает confirm через Telegram
   * @param {string} message
   * @returns {Promise<boolean>}
   */
  async showConfirm(message) {
    if (this.tg?.showConfirm) {
      return new Promise((resolve) => {
        this.tg.showConfirm(message, resolve);
      });
    } else {
      return confirm(message);
    }
  }

  /**
   * Показывает popup через Telegram
   * @param {Object} params - параметры popup
   */
  showPopup(params) {
    if (this.tg?.showPopup) {
      this.tg.showPopup(params);
    } else {
      this.showAlert(params.message);
    }
  }

  /**
   * Закрывает WebApp
   */
  close() {
    if (this.tg?.close) {
      this.tg.close();
    } else {
      window.close();
    }
  }

  /**
   * Включает/выключает кнопку подтверждения закрытия
   * @param {boolean} enabled
   */
  enableClosingConfirmation(enabled = true) {
    if (this.tg?.enableClosingConfirmation) {
      this.tg.enableClosingConfirmation();
    }
    if (!enabled && this.tg?.disableClosingConfirmation) {
      this.tg.disableClosingConfirmation();
    }
  }

  /**
   * Устанавливает главную кнопку Telegram
   * @param {Object} options
   */
  setMainButton(options) {
    if (!this.tg?.MainButton) return;

    const btn = this.tg.MainButton;

    if (options.text) {
      btn.setText(options.text);
    }

    if (options.color) {
      btn.setParams({ color: options.color });
    }

    if (options.onClick) {
      btn.onClick(options.onClick);
    }

    if (options.show) {
      btn.show();
    } else if (options.hide) {
      btn.hide();
    }

    if (options.loading !== undefined) {
      if (options.loading) {
        btn.showProgress();
      } else {
        btn.hideProgress();
      }
    }
  }

  /**
   * Отправляет данные обратно в бота
   * @param {Object} data
   */
  sendData(data) {
    if (this.tg?.sendData) {
      this.tg.sendData(JSON.stringify(data));
    }
  }

  /**
   * Открывает ссылку
   * @param {string} url
   */
  openLink(url) {
    if (this.tg?.openLink) {
      this.tg.openLink(url);
    } else {
      window.open(url, '_blank');
    }
  }

  /**
   * Вызывает вибрацию
   * @param {string} type - 'light', 'medium', 'heavy', 'rigid', 'soft'
   */
  hapticFeedback(type = 'light') {
    if (this.tg?.HapticFeedback) {
      switch (type) {
        case 'light':
        case 'medium':
        case 'heavy':
        case 'rigid':
        case 'soft':
          this.tg.HapticFeedback.impactOccurred(type);
          break;
        case 'success':
        case 'warning':
        case 'error':
          this.tg.HapticFeedback.notificationOccurred(type);
          break;
        default:
          this.tg.HapticFeedback.selectionChanged();
      }
    }
  }

  /**
   * Проверяет, открыто ли приложение в Telegram
   * @returns {boolean}
   */
  isInTelegram() {
    return !!this.tg;
  }

  /**
   * Получает версию Telegram WebApp API
   * @returns {string}
   */
  getVersion() {
    return this.tg?.version || 'unknown';
  }

  /**
   * Получает платформу (ios, android, etc.)
   * @returns {string}
   */
  getPlatform() {
    return this.tg?.platform || 'unknown';
  }
}

// Экспортируем singleton
export const telegramAuth = new TelegramAuth();
