var TeacherApp = (function (exports) {
  'use strict';

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
  const telegramAuth = new TelegramAuth();

  /**
   * API клиент для взаимодействия с backend
   * Все запросы автоматически включают аутентификационные данные
   */


  class APIClient {
    constructor() {
      // TODO: Заменить на актуальный URL после деплоя
      this.baseURL = window.location.origin + '/api/teacher';
      this.headers = {
        'Content-Type': 'application/json'
      };
    }

    /**
     * Выполняет HTTP запрос с автоматической аутентификацией
     * @param {string} endpoint
     * @param {Object} options
     * @returns {Promise<Object>}
     */
    async request(endpoint, options = {}) {
      const url = `${this.baseURL}${endpoint}`;

      // Добавляем initData для аутентификации
      const headers = {
        ...this.headers,
        'X-Telegram-Init-Data': telegramAuth.getInitData(),
        ...options.headers
      };

      const config = {
        ...options,
        headers
      };

      try {
        const response = await fetch(url, config);

        // Обработка ошибок HTTP
        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new APIError(
            errorData.detail || errorData.error || `HTTP ${response.status}`,
            response.status,
            errorData
          );
        }

        // Парсим JSON ответ
        const data = await response.json();
        return data;

      } catch (error) {
        if (error instanceof APIError) {
          throw error;
        }

        // Обработка сетевых ошибок
        console.error('API Request Error:', error);
        throw new APIError(
          'Ошибка сети. Проверьте подключение к интернету.',
          0,
          { originalError: error.message }
        );
      }
    }

    /**
     * GET запрос
     * @param {string} endpoint
     * @param {Object} params - query параметры
     * @returns {Promise<Object>}
     */
    async get(endpoint, params = {}) {
      const queryString = new URLSearchParams(params).toString();
      const url = queryString ? `${endpoint}?${queryString}` : endpoint;

      return this.request(url, {
        method: 'GET'
      });
    }

    /**
     * POST запрос
     * @param {string} endpoint
     * @param {Object} data
     * @returns {Promise<Object>}
     */
    async post(endpoint, data = {}) {
      return this.request(endpoint, {
        method: 'POST',
        body: JSON.stringify(data)
      });
    }

    /**
     * PUT запрос
     * @param {string} endpoint
     * @param {Object} data
     * @returns {Promise<Object>}
     */
    async put(endpoint, data = {}) {
      return this.request(endpoint, {
        method: 'PUT',
        body: JSON.stringify(data)
      });
    }

    /**
     * DELETE запрос
     * @param {string} endpoint
     * @returns {Promise<Object>}
     */
    async delete(endpoint) {
      return this.request(endpoint, {
        method: 'DELETE'
      });
    }

    // ============================================
    // TEACHER ENDPOINTS
    // ============================================

    /**
     * Получает профиль учителя
     * @returns {Promise<Object>}
     */
    async getTeacherProfile() {
      return this.get('/profile');
    }

    /**
     * Получает список учеников
     * @param {Object} params - { search, limit, offset }
     * @returns {Promise<Object>}
     */
    async getStudents(params = {}) {
      return this.get('/students', params);
    }

    /**
     * Получает список модулей
     * @returns {Promise<Object>}
     */
    async getModules() {
      return this.get('/modules');
    }

    /**
     * Получает список вопросов
     * @param {Object} params - { module, search, limit, offset }
     * @returns {Promise<Object>}
     */
    async getQuestions(params = {}) {
      if (!params.module) {
        throw new Error('Параметр module обязателен');
      }
      return this.get('/questions', params);
    }

    /**
     * Создает новое задание
     * @param {Object} assignmentData
     * @returns {Promise<Object>}
     */
    async createAssignment(assignmentData) {
      return this.post('/assignments', assignmentData);
    }

    /**
     * Получает список заданий
     * @param {Object} params - { limit, offset, status }
     * @returns {Promise<Object>}
     */
    async getAssignments(params = {}) {
      return this.get('/assignments', params);
    }

    /**
     * Получает конкретное задание по ID
     * @param {number} assignmentId
     * @returns {Promise<Object>}
     */
    async getAssignment(assignmentId) {
      return this.get(`/assignments/${assignmentId}`);
    }

    /**
     * Обновляет задание
     * @param {number} assignmentId
     * @param {Object} data
     * @returns {Promise<Object>}
     */
    async updateAssignment(assignmentId, data) {
      return this.put(`/assignments/${assignmentId}`, data);
    }

    /**
     * Удаляет задание
     * @param {number} assignmentId
     * @returns {Promise<Object>}
     */
    async deleteAssignment(assignmentId) {
      return this.delete(`/assignments/${assignmentId}`);
    }

    /**
     * Сохраняет черновик задания
     * @param {Object} draftData
     * @returns {Promise<Object>}
     */
    async saveDraft(draftData) {
      return this.post('/drafts', { draft_data: draftData });
    }

    /**
     * Получает список черновиков
     * @returns {Promise<Object>}
     */
    async getDrafts() {
      return this.get('/drafts');
    }

    /**
     * Удаляет черновик
     * @param {string} draftId
     * @returns {Promise<Object>}
     */
    async deleteDraft(draftId) {
      return this.delete(`/drafts/${draftId}`);
    }

    /**
     * Получает статистику учителя
     * @returns {Promise<Object>}
     */
    async getStats() {
      return this.get('/stats');
    }

    /**
     * Получает статистику по ученику
     * @param {number} studentId
     * @returns {Promise<Object>}
     */
    async getStudentStats(studentId) {
      return this.get(`/students/${studentId}/stats`);
    }
  }

  /**
   * Кастомный класс ошибки API
   */
  class APIError extends Error {
    constructor(message, status, data = {}) {
      super(message);
      this.name = 'APIError';
      this.status = status;
      this.data = data;
    }

    /**
     * Проверяет, является ли ошибка ошибкой аутентификации
     * @returns {boolean}
     */
    isAuthError() {
      return this.status === 401 || this.status === 403;
    }

    /**
     * Проверяет, является ли ошибка ошибкой валидации
     * @returns {boolean}
     */
    isValidationError() {
      return this.status === 422 || this.data.error === 'validation_error';
    }

    /**
     * Получает детали ошибки валидации
     * @returns {Object}
     */
    getValidationErrors() {
      return this.data.details || {};
    }

    /**
     * Получает понятное пользователю сообщение об ошибке
     * @returns {string}
     */
    getUserMessage() {
      switch (this.status) {
        case 0:
          return 'Ошибка сети. Проверьте подключение к интернету.';
        case 401:
          return 'Ошибка аутентификации. Попробуйте перезапустить приложение.';
        case 403:
          return 'Доступ запрещен. У вас нет прав на это действие.';
        case 404:
          return 'Ресурс не найден.';
        case 422:
          return 'Ошибка валидации данных. Проверьте введенные значения.';
        case 429:
          return 'Слишком много запросов. Попробуйте позже.';
        case 500:
          return 'Ошибка сервера. Мы уже работаем над исправлением.';
        default:
          return this.message || 'Произошла ошибка. Попробуйте еще раз.';
      }
    }
  }

  // Экспортируем singleton и класс ошибки
  const api = new APIClient();

  /**
   * Утилиты для работы с LocalStorage
   * Используется для сохранения черновиков и кеширования данных
   */

  class Storage {
    constructor(prefix = 'teacher_') {
      this.prefix = prefix;
    }

    /**
     * Генерирует ключ с префиксом
     * @param {string} key
     * @returns {string}
     */
    _getKey(key) {
      return `${this.prefix}${key}`;
    }

    /**
     * Сохраняет данные в LocalStorage
     * @param {string} key
     * @param {*} value
     * @returns {boolean}
     */
    set(key, value) {
      try {
        const data = JSON.stringify(value);
        localStorage.setItem(this._getKey(key), data);
        return true;
      } catch (error) {
        console.error('Storage.set error:', error);
        return false;
      }
    }

    /**
     * Получает данные из LocalStorage
     * @param {string} key
     * @param {*} defaultValue - значение по умолчанию
     * @returns {*}
     */
    get(key, defaultValue = null) {
      try {
        const data = localStorage.getItem(this._getKey(key));
        return data ? JSON.parse(data) : defaultValue;
      } catch (error) {
        console.error('Storage.get error:', error);
        return defaultValue;
      }
    }

    /**
     * Удаляет данные из LocalStorage
     * @param {string} key
     * @returns {boolean}
     */
    remove(key) {
      try {
        localStorage.removeItem(this._getKey(key));
        return true;
      } catch (error) {
        console.error('Storage.remove error:', error);
        return false;
      }
    }

    /**
     * Проверяет наличие ключа
     * @param {string} key
     * @returns {boolean}
     */
    has(key) {
      return localStorage.getItem(this._getKey(key)) !== null;
    }

    /**
     * Очищает все данные с префиксом
     * @returns {boolean}
     */
    clear() {
      try {
        const keys = Object.keys(localStorage);
        keys.forEach(key => {
          if (key.startsWith(this.prefix)) {
            localStorage.removeItem(key);
          }
        });
        return true;
      } catch (error) {
        console.error('Storage.clear error:', error);
        return false;
      }
    }

    /**
     * Получает все ключи с префиксом
     * @returns {string[]}
     */
    keys() {
      const allKeys = Object.keys(localStorage);
      return allKeys
        .filter(key => key.startsWith(this.prefix))
        .map(key => key.replace(this.prefix, ''));
    }

    /**
     * Получает размер используемого хранилища (приблизительно)
     * @returns {number} - размер в байтах
     */
    getSize() {
      let size = 0;
      const keys = Object.keys(localStorage);
      keys.forEach(key => {
        if (key.startsWith(this.prefix)) {
          const value = localStorage.getItem(key);
          size += key.length + (value?.length || 0);
        }
      });
      return size;
    }
  }

  /**
   * Менеджер черновиков заданий
   */
  class DraftManager extends Storage {
    constructor() {
      super('draft_');
      this.currentDraftKey = 'assignment_current';
      this.maxAge = 24 * 60 * 60 * 1000; // 24 часа
    }

    /**
     * Сохраняет текущий черновик задания
     * @param {Object} draftData
     * @returns {boolean}
     */
    saveCurrent(draftData) {
      const draft = {
        timestamp: Date.now(),
        data: draftData
      };
      return this.set(this.currentDraftKey, draft);
    }

    /**
     * Загружает текущий черновик задания
     * @returns {Object|null}
     */
    loadCurrent() {
      const draft = this.get(this.currentDraftKey);

      if (!draft) {
        return null;
      }

      // Проверяем возраст черновика
      const age = Date.now() - draft.timestamp;
      if (age > this.maxAge) {
        console.log('Черновик устарел, удаляем');
        this.removeCurrent();
        return null;
      }

      return draft.data;
    }

    /**
     * Удаляет текущий черновик
     * @returns {boolean}
     */
    removeCurrent() {
      return this.remove(this.currentDraftKey);
    }

    /**
     * Проверяет наличие черновика
     * @returns {boolean}
     */
    hasCurrent() {
      return this.has(this.currentDraftKey);
    }

    /**
     * Получает возраст текущего черновика в миллисекундах
     * @returns {number|null}
     */
    getCurrentAge() {
      const draft = this.get(this.currentDraftKey);
      if (!draft) return null;

      return Date.now() - draft.timestamp;
    }

    /**
     * Сохраняет именованный черновик
     * @param {string} name
     * @param {Object} draftData
     * @returns {boolean}
     */
    saveNamed(name, draftData) {
      const draft = {
        name,
        timestamp: Date.now(),
        data: draftData
      };
      return this.set(`named_${name}`, draft);
    }

    /**
     * Загружает именованный черновик
     * @param {string} name
     * @returns {Object|null}
     */
    loadNamed(name) {
      return this.get(`named_${name}`);
    }

    /**
     * Получает список всех именованных черновиков
     * @returns {Array}
     */
    listNamed() {
      const keys = this.keys();
      return keys
        .filter(key => key.startsWith('named_'))
        .map(key => {
          const draft = this.get(key);
          return {
            key,
            name: draft.name,
            timestamp: draft.timestamp,
            age: Date.now() - draft.timestamp
          };
        })
        .sort((a, b) => b.timestamp - a.timestamp);
    }
  }

  /**
   * Менеджер кеша данных
   */
  class CacheManager extends Storage {
    constructor() {
      super('cache_');
      this.defaultTTL = 5 * 60 * 1000; // 5 минут
    }

    /**
     * Сохраняет данные в кеш
     * @param {string} key
     * @param {*} value
     * @param {number} ttl - время жизни в миллисекундах
     * @returns {boolean}
     */
    setCache(key, value, ttl = this.defaultTTL) {
      const cacheItem = {
        value,
        timestamp: Date.now(),
        ttl
      };
      return this.set(key, cacheItem);
    }

    /**
     * Получает данные из кеша
     * @param {string} key
     * @returns {*|null}
     */
    getCache(key) {
      const cacheItem = this.get(key);

      if (!cacheItem) {
        return null;
      }

      // Проверяем TTL
      const age = Date.now() - cacheItem.timestamp;
      if (age > cacheItem.ttl) {
        this.remove(key);
        return null;
      }

      return cacheItem.value;
    }

    /**
     * Очищает устаревший кеш
     * @returns {number} - количество удаленных элементов
     */
    clearExpired() {
      let count = 0;
      const keys = this.keys();

      keys.forEach(key => {
        const cacheItem = this.get(key);
        if (cacheItem) {
          const age = Date.now() - cacheItem.timestamp;
          if (age > cacheItem.ttl) {
            this.remove(key);
            count++;
          }
        }
      });

      return count;
    }

    /**
     * Инвалидирует (удаляет) кеш по паттерну
     * @param {string} pattern - паттерн для поиска ключей
     * @returns {number} - количество удаленных элементов
     */
    invalidate(pattern) {
      let count = 0;
      const keys = this.keys();

      keys.forEach(key => {
        if (key.includes(pattern)) {
          this.remove(key);
          count++;
        }
      });

      return count;
    }
  }
  const draftManager = new DraftManager();
  const cacheManager = new CacheManager();

  // Автоматическая очистка устаревшего кеша при загрузке
  cacheManager.clearExpired();

  /**
   * Утилиты валидации форм
   */

  /**
   * Валидирует форму создания задания
   * @param {Object} state - состояние формы
   * @returns {Object} - объект с ошибками { field: 'error message' }
   */
  function validateAssignmentForm(state) {
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
   * Проверяет, является ли строка пустой или содержит только пробелы
   * @param {string} str
   * @returns {boolean}
   */
  function isEmpty(str) {
    return !str || str.trim().length === 0;
  }

  /**
   * Показывает ошибку на input элементе
   * @param {HTMLElement} input
   * @param {string} message
   */
  function showInputError(input, message) {
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
  function clearInputError(input) {
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
  function attachLiveValidation(input, validator) {
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
  function titleValidator(value) {
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
  function descriptionValidator(value) {
    if (value && value.length > 500) {
      return { valid: false, message: 'Максимум 500 символов' };
    }

    return { valid: true, message: '' };
  }

  /**
   * Утилиты для работы с UI элементами
   */

  /**
   * Показывает toast уведомление
   * @param {string} message
   * @param {string} type - 'success', 'error', 'warning', 'info'
   * @param {number} duration - длительность в мс
   */
  function showToast(message, type = 'info', duration = 3000) {
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
  function showLoadingScreen(message = 'Загрузка...') {
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
  function hideLoadingScreen() {
    const screen = document.getElementById('loading-screen');
    if (screen) {
      screen.style.display = 'none';
    }
  }

  /**
   * Показывает модальное окно
   * @param {string} id - ID модального окна
   */
  function showModal(id) {
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
  function hideModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.style.display = 'none';
      document.body.style.overflow = '';
    }
  }

  /**
   * Показывает пустое состояние
   * @param {HTMLElement} container
   * @param {Object} options
   */
  function showEmptyState(container, options = {}) {
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
  function createSpinner() {
    const spinner = document.createElement('div');
    spinner.className = 'spinner';
    return spinner;
  }

  /**
   * Обновляет индикатор прогресса
   * @param {number} current - текущий шаг (1-5)
   * @param {number} total - всего шагов
   */
  function updateProgress(current, total = 5) {
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
   * Показывает/скрывает элемент
   * @param {HTMLElement|string} element
   * @param {boolean} show
   */
  function toggle(element, show) {
    const el = typeof element === 'string'
      ? document.querySelector(element)
      : element;

    if (!el) return;

    {
      el.style.display = '';
    }
  }

  /**
   * Утилиты для форматирования данных
   */

  /**
   * Форматирует дату в читаемый вид
   * @param {string|Date} date
   * @param {boolean} includeTime - включать ли время
   * @returns {string}
   */
  function formatDate(date, includeTime = true) {
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
   * Форматирует число с разделителями разрядов
   * @param {number} num
   * @returns {string} - например, "1 000"
   */
  function formatNumber(num) {
    return new Intl.NumberFormat('ru-RU').format(num);
  }

  /**
   * Форматирует тип задания в читаемый вид
   * @param {string} type
   * @returns {string}
   */
  function formatAssignmentType(type) {
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
   * Pluralize - склонение числительных
   * @param {number} count
   * @param {string} one - для 1 (например, "задание")
   * @param {string} few - для 2-4 (например, "задания")
   * @param {string} many - для 5+ (например, "заданий")
   * @returns {string}
   */
  function pluralize(count, one, few, many) {
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
  function formatCount(count, one, few, many) {
    return `${formatNumber(count)} ${pluralize(count, one, few, many)}`;
  }

  /**
   * Debounce функция
   * @param {Function} func
   * @param {number} wait - время ожидания в мс
   * @returns {Function}
   */
  function debounce(func, wait) {
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
   * Простой Event Emitter для компонентов
   */
  class EventEmitter {
    constructor() {
      this.events = {};
    }

    /**
     * Подписывается на событие
     * @param {string} event
     * @param {Function} callback
     */
    on(event, callback) {
      if (!this.events[event]) {
        this.events[event] = [];
      }
      this.events[event].push(callback);
    }

    /**
     * Отписывается от события
     * @param {string} event
     * @param {Function} callback
     */
    off(event, callback) {
      if (!this.events[event]) return;

      this.events[event] = this.events[event].filter(cb => cb !== callback);
    }

    /**
     * Вызывает событие
     * @param {string} event
     * @param {*} data
     */
    emit(event, data) {
      if (!this.events[event]) return;

      this.events[event].forEach(callback => {
        callback(data);
      });
    }

    /**
     * Подписывается на событие один раз
     * @param {string} event
     * @param {Function} callback
     */
    once(event, callback) {
      const wrapper = (data) => {
        callback(data);
        this.off(event, wrapper);
      };
      this.on(event, wrapper);
    }
  }

  /**
   * Компонент браузера вопросов
   * Показывает список вопросов с поиском и пагинацией
   */


  class QuestionBrowser extends EventEmitter {
    constructor(container) {
      super();
      this.container = container;
      this.moduleCode = null;
      this.selectedIds = new Set();
      this.questions = [];
      this.currentPage = 1;
      this.pageSize = 20;
      this.totalQuestions = 0;
      this.searchQuery = '';
    }

    /**
     * Инициализация браузера
     * @param {string} moduleCode
     * @param {Array} preselectedIds - предвыбранные вопросы
     */
    async init(moduleCode, preselectedIds = []) {
      this.moduleCode = moduleCode;
      this.selectedIds = new Set(preselectedIds);

      this.render();
      await this.loadQuestions();
    }

    /**
     * Рендерит структуру браузера
     */
    render() {
      this.container.innerHTML = `
      <div class="question-browser">
        <div class="browser-controls">
          <input type="search"
                 class="form-input"
                 id="question-search"
                 placeholder="🔍 Поиск по тексту вопроса...">
        </div>

        <div class="question-list" id="question-list">
          ${createSpinner().outerHTML}
        </div>

        <div class="pagination" id="pagination" style="display: none;">
          <button class="btn-secondary" id="prev-page" disabled>← Назад</button>
          <span>Страница <span id="current-page">1</span> из <span id="total-pages">1</span></span>
          <button class="btn-secondary" id="next-page">Вперед →</button>
        </div>

        <div class="browser-info">
          Выбрано вопросов: <strong id="selected-count">0</strong>
        </div>
      </div>
    `;

      this.setupEventListeners();
    }

    /**
     * Настраивает обработчики событий
     */
    setupEventListeners() {
      const searchInput = this.container.querySelector('#question-search');
      if (searchInput) {
        searchInput.addEventListener('input', debounce((e) => {
          this.searchQuery = e.target.value;
          this.currentPage = 1;
          this.loadQuestions();
        }, 500));
      }

      const prevBtn = this.container.querySelector('#prev-page');
      if (prevBtn) {
        prevBtn.addEventListener('click', () => {
          if (this.currentPage > 1) {
            this.currentPage--;
            this.loadQuestions();
          }
        });
      }

      const nextBtn = this.container.querySelector('#next-page');
      if (nextBtn) {
        nextBtn.addEventListener('click', () => {
          const totalPages = Math.ceil(this.totalQuestions / this.pageSize);
          if (this.currentPage < totalPages) {
            this.currentPage++;
            this.loadQuestions();
          }
        });
      }
    }

    /**
     * Загружает вопросы с сервера
     */
    async loadQuestions() {
      try {
        const response = await api.getQuestions({
          module: this.moduleCode,
          search: this.searchQuery,
          limit: this.pageSize,
          offset: (this.currentPage - 1) * this.pageSize
        });

        this.questions = response.questions || [];
        this.totalQuestions = response.total || 0;

        this.renderQuestions();
        this.updatePagination();

      } catch (error) {
        console.error('Failed to load questions:', error);
        showToast('Ошибка загрузки вопросов', 'error');
        this.renderError();
      }
    }

    /**
     * Рендерит список вопросов
     */
    renderQuestions() {
      const listContainer = this.container.querySelector('#question-list');
      if (!listContainer) return;

      if (this.questions.length === 0) {
        showEmptyState(listContainer, {
          icon: '🔍',
          title: 'Вопросы не найдены',
          description: this.searchQuery ? 'Попробуйте изменить поисковый запрос' : ''
        });
        return;
      }

      const html = this.questions.map(q => `
      <div class="question-card ${this.selectedIds.has(q.id) ? 'selected' : ''}"
           data-id="${q.id}">
        <input type="checkbox"
               data-id="${q.id}"
               ${this.selectedIds.has(q.id) ? 'checked' : ''}>
        <div class="question-content">
          <span class="question-number">#${q.number || q.id}</span>
          <p class="question-text">${this.truncateText(q.text, 150)}</p>
          ${q.topic ? `<span class="question-topic">${q.topic}</span>` : ''}
        </div>
      </div>
    `).join('');

      listContainer.innerHTML = html;

      // Добавляем обработчики для карточек
      listContainer.querySelectorAll('.question-card').forEach(card => {
        card.addEventListener('click', (e) => {
          const questionId = card.dataset.id;
          const checkbox = card.querySelector('input[type="checkbox"]');

          // Если клик был не по checkbox, переключаем его
          if (e.target !== checkbox) {
            checkbox.checked = !checkbox.checked;
          }

          this.toggleSelection(questionId, checkbox.checked);
        });

        const checkbox = card.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', (e) => {
          e.stopPropagation();
          this.toggleSelection(card.dataset.id, e.target.checked);
        });
      });

      this.updateCounter();
    }

    /**
     * Рендерит ошибку
     */
    renderError() {
      const listContainer = this.container.querySelector('#question-list');
      if (!listContainer) return;

      showEmptyState(listContainer, {
        icon: '⚠️',
        title: 'Ошибка загрузки',
        description: 'Не удалось загрузить вопросы'
      });
    }

    /**
     * Обновляет пагинацию
     */
    updatePagination() {
      const paginationContainer = this.container.querySelector('#pagination');
      if (!paginationContainer) return;

      const totalPages = Math.ceil(this.totalQuestions / this.pageSize);

      if (totalPages <= 1) {
        paginationContainer.style.display = 'none';
        return;
      }

      paginationContainer.style.display = 'flex';

      const currentPageSpan = paginationContainer.querySelector('#current-page');
      const totalPagesSpan = paginationContainer.querySelector('#total-pages');
      const prevBtn = paginationContainer.querySelector('#prev-page');
      const nextBtn = paginationContainer.querySelector('#next-page');

      if (currentPageSpan) currentPageSpan.textContent = this.currentPage;
      if (totalPagesSpan) totalPagesSpan.textContent = totalPages;

      if (prevBtn) {
        prevBtn.disabled = this.currentPage === 1;
      }

      if (nextBtn) {
        nextBtn.disabled = this.currentPage === totalPages;
      }
    }

    /**
     * Переключает выбор вопроса
     * @param {string} questionId
     * @param {boolean} selected
     */
    toggleSelection(questionId, selected) {
      if (selected) {
        this.selectedIds.add(questionId);
      } else {
        this.selectedIds.delete(questionId);
      }

      // Обновляем UI карточки
      const card = this.container.querySelector(`.question-card[data-id="${questionId}"]`);
      if (card) {
        card.classList.toggle('selected', selected);
      }

      this.updateCounter();
      this.emit('change', Array.from(this.selectedIds));
    }

    /**
     * Обновляет счетчик выбранных вопросов
     */
    updateCounter() {
      const counter = this.container.querySelector('#selected-count');
      if (counter) {
        counter.textContent = this.selectedIds.size;
      }
    }

    /**
     * Обрезает текст
     * @param {string} text
     * @param {number} maxLength
     * @returns {string}
     */
    truncateText(text, maxLength) {
      if (text.length <= maxLength) return text;
      return text.substring(0, maxLength) + '...';
    }

    /**
     * Получает выбранные ID
     * @returns {Array}
     */
    getSelectedIds() {
      return Array.from(this.selectedIds);
    }

    /**
     * Устанавливает выбранные ID
     * @param {Array} ids
     */
    setSelectedIds(ids) {
      this.selectedIds = new Set(ids);
      this.updateCounter();
      this.renderQuestions();
    }

    /**
     * Очищает выбор
     */
    clearSelection() {
      this.selectedIds.clear();
      this.updateCounter();
      this.renderQuestions();
      this.emit('change', []);
    }

    /**
     * Уничтожает компонент
     */
    destroy() {
      this.container.innerHTML = '';
    }
  }

  /**
   * Компонент выбора учеников
   * Показывает список учеников с поиском и множественным выбором
   */


  class StudentSelector extends EventEmitter {
    constructor(container) {
      super();
      this.container = container;
      this.students = [];
      this.filteredStudents = [];
      this.selectedIds = new Set();
      this.searchQuery = '';
    }

    /**
     * Инициализация компонента
     * @param {Array} students - список учеников
     */
    async init(students) {
      this.students = students;
      this.filteredStudents = students;

      this.render();
      this.renderStudents();
    }

    /**
     * Рендерит структуру компонента
     */
    render() {
      this.container.innerHTML = `
      <div class="student-selector">
        <input type="search"
               class="form-input mb-md"
               id="student-search"
               placeholder="🔍 Поиск по имени или username...">

        <div class="quick-actions mb-md">
          <button class="btn-secondary" id="select-all">Выбрать всех</button>
          <button class="btn-secondary" id="select-none">Снять выбор</button>
        </div>

        <div class="student-list" id="student-list"></div>

        <div class="selector-info mt-md">
          Выбрано учеников: <strong id="selected-students-count">0</strong>
        </div>
      </div>
    `;

      this.setupEventListeners();
    }

    /**
     * Настраивает обработчики событий
     */
    setupEventListeners() {
      const searchInput = this.container.querySelector('#student-search');
      if (searchInput) {
        searchInput.addEventListener('input', debounce((e) => {
          this.searchQuery = e.target.value.toLowerCase();
          this.filterStudents();
          this.renderStudents();
        }, 300));
      }

      const selectAllBtn = this.container.querySelector('#select-all');
      if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => this.selectAll());
      }

      const selectNoneBtn = this.container.querySelector('#select-none');
      if (selectNoneBtn) {
        selectNoneBtn.addEventListener('click', () => this.selectNone());
      }
    }

    /**
     * Фильтрует учеников по поисковому запросу
     */
    filterStudents() {
      if (!this.searchQuery) {
        this.filteredStudents = this.students;
        return;
      }

      this.filteredStudents = this.students.filter(student => {
        const name = (student.name || '').toLowerCase();
        const username = (student.username || '').toLowerCase();
        return name.includes(this.searchQuery) || username.includes(this.searchQuery);
      });
    }

    /**
     * Рендерит список учеников
     */
    renderStudents() {
      const listContainer = this.container.querySelector('#student-list');
      if (!listContainer) return;

      if (this.filteredStudents.length === 0) {
        if (this.students.length === 0) {
          showEmptyState(listContainer, {
            icon: '👥',
            title: 'У вас пока нет учеников',
            description: 'Пригласите учеников подключиться к вам через код учителя'
          });
        } else {
          showEmptyState(listContainer, {
            icon: '🔍',
            title: 'Ученики не найдены',
            description: 'Попробуйте изменить поисковый запрос'
          });
        }
        return;
      }

      const html = this.filteredStudents.map(student => `
      <div class="student-card ${this.selectedIds.has(student.user_id) ? 'selected' : ''}"
           data-id="${student.user_id}">
        <input type="checkbox"
               data-id="${student.user_id}"
               ${this.selectedIds.has(student.user_id) ? 'checked' : ''}>
        <div class="student-info">
          <div class="student-name">${this.escapeHTML(student.name || 'Безымянный')}</div>
          ${student.username ? `<div class="student-username">@${student.username}</div>` : ''}
          ${student.stats ? `
            <div class="student-stats">
              <span>Выполнено: ${student.stats.completed_assignments || 0}</span>
              <span>Средний балл: ${(student.stats.average_score || 0).toFixed(1)}%</span>
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');

      listContainer.innerHTML = html;

      // Добавляем обработчики
      listContainer.querySelectorAll('.student-card').forEach(card => {
        card.addEventListener('click', (e) => {
          const studentId = parseInt(card.dataset.id);
          const checkbox = card.querySelector('input[type="checkbox"]');

          if (e.target !== checkbox) {
            checkbox.checked = !checkbox.checked;
          }

          this.toggleSelection(studentId, checkbox.checked);
        });

        const checkbox = card.querySelector('input[type="checkbox"]');
        checkbox.addEventListener('change', (e) => {
          e.stopPropagation();
          this.toggleSelection(parseInt(card.dataset.id), e.target.checked);
        });
      });

      this.updateCounter();
    }

    /**
     * Переключает выбор ученика
     * @param {number} studentId
     * @param {boolean} selected
     */
    toggleSelection(studentId, selected) {
      if (selected) {
        this.selectedIds.add(studentId);
      } else {
        this.selectedIds.delete(studentId);
      }

      // Обновляем UI карточки
      const card = this.container.querySelector(`.student-card[data-id="${studentId}"]`);
      if (card) {
        card.classList.toggle('selected', selected);
      }

      this.updateCounter();
      this.emit('change', Array.from(this.selectedIds));
    }

    /**
     * Выбирает всех учеников (из отфильтрованного списка)
     */
    selectAll() {
      this.filteredStudents.forEach(student => {
        this.selectedIds.add(student.id);
      });

      this.renderStudents();
      this.emit('change', Array.from(this.selectedIds));
    }

    /**
     * Снимает выбор со всех
     */
    selectNone() {
      this.selectedIds.clear();
      this.renderStudents();
      this.emit('change', []);
    }

    /**
     * Обновляет счетчик выбранных учеников
     */
    updateCounter() {
      const counter = this.container.querySelector('#selected-students-count');
      if (counter) {
        counter.textContent = this.selectedIds.size;
      }
    }

    /**
     * Получает выбранные ID
     * @returns {Array}
     */
    getSelected() {
      return Array.from(this.selectedIds);
    }

    /**
     * Устанавливает выбранные ID
     * @param {Array} ids
     */
    setSelected(ids) {
      this.selectedIds = new Set(ids);
      this.renderStudents();
      this.emit('change', Array.from(this.selectedIds));
    }

    /**
     * Экранирует HTML
     * @param {string} str
     * @returns {string}
     */
    escapeHTML(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    /**
     * Уничтожает компонент
     */
    destroy() {
      this.container.innerHTML = '';
    }
  }

  /**
   * Модальное окно предпросмотра задания
   * Показывает финальный вид задания перед отправкой
   */


  class PreviewModal {
    constructor(modalElement) {
      this.modal = modalElement;
      this.state = null;
      this.assignmentData = null;
    }

    /**
     * Показывает предпросмотр
     * @param {Object} state - состояние формы
     * @param {Object} assignmentData - данные для отправки
     */
    show(state, assignmentData) {
      this.state = state;
      this.assignmentData = assignmentData;

      this.render();
      showModal(this.modal.id);
      this.setupEventListeners();
    }

    /**
     * Рендерит содержимое модального окна
     */
    render() {
      const body = this.modal.querySelector('.modal-body');
      if (!body) return;

      const {
        title,
        description,
        assignmentType,
        studentIds,
        modules,
        deadline
      } = this.assignmentData;

      // Подсчитываем общее количество вопросов
      const totalQuestions = this.calculateTotalQuestions(modules);

      body.innerHTML = `
      <div class="preview-content">
        <h3 class="mb-md">${this.escapeHTML(title)}</h3>

        ${description ? `<p class="text-muted mb-lg">${this.escapeHTML(description)}</p>` : ''}

        <div class="preview-info mb-lg">
          <div class="info-item">
            <span class="label">Тип задания</span>
            <div class="value">${formatAssignmentType(assignmentType)}</div>
          </div>

          <div class="info-item">
            <span class="label">Вопросов</span>
            <div class="value">${totalQuestions}</div>
          </div>

          <div class="info-item">
            <span class="label">Учеников</span>
            <div class="value">${formatCount(studentIds.length, 'ученик', 'ученика', 'учеников')}</div>
          </div>

          <div class="info-item">
            <span class="label">Дедлайн</span>
            <div class="value">${deadline ? formatDate(deadline) : 'Без дедлайна'}</div>
          </div>
        </div>

        ${this.renderModulesInfo(modules, assignmentType)}

        <div class="preview-warning mt-lg">
          <p class="text-muted" style="font-size: 0.9rem;">
            ℹ️ После создания задание будет автоматически отправлено всем выбранным ученикам.
          </p>
        </div>
      </div>
    `;
    }

    /**
     * Рендерит информацию о модулях
     * @param {Array} modules
     * @param {string} assignmentType
     * @returns {string}
     */
    renderModulesInfo(modules, assignmentType) {
      if (assignmentType === 'full_exam') {
        return `
        <div class="preview-modules">
          <h4 class="mb-md">Состав задания:</h4>
          <p class="text-muted">Полный вариант ЕГЭ будет сгенерирован автоматически (20 заданий).</p>
        </div>
      `;
      }

      if (!modules || modules.length === 0) {
        return '';
      }

      const modulesHTML = modules.map(module => {
        let details = '';

        if (module.selection_mode === 'all') {
          details = 'Все доступные вопросы';
        } else if (module.selection_mode === 'random') {
          details = `${module.question_count} случайных вопросов`;
        } else if (module.selection_mode === 'specific') {
          details = `${module.question_ids.length} выбранных вопросов`;
        }

        return `
        <li>
          <strong>${this.getModuleName(module.module_code)}</strong>: ${details}
        </li>
      `;
      }).join('');

      return `
      <div class="preview-modules">
        <h4 class="mb-md">Состав задания:</h4>
        <ul class="preview-modules-list">
          ${modulesHTML}
        </ul>
      </div>
    `;
    }

    /**
     * Подсчитывает общее количество вопросов
     * @param {Array} modules
     * @returns {number}
     */
    calculateTotalQuestions(modules) {
      if (!modules || modules.length === 0) return 0;

      return modules.reduce((total, module) => {
        if (module.selection_mode === 'specific') {
          return total + module.question_ids.length;
        } else if (module.selection_mode === 'random') {
          return total + (module.question_count || 0);
        } else {
          // Для режима "all" нужно знать количество из модуля
          // В упрощенной версии возвращаем примерное значение
          return total;
        }
      }, 0);
    }

    /**
     * Настраивает обработчики событий
     */
    setupEventListeners() {
      const closeBtn = this.modal.querySelector('#preview-close-btn');
      if (closeBtn) {
        closeBtn.onclick = () => this.hide();
      }

      const editBtn = this.modal.querySelector('#preview-edit-btn');
      if (editBtn) {
        editBtn.onclick = () => this.hide();
      }

      // Кнопка подтверждения обрабатывается в main.js
    }

    /**
     * Скрывает модальное окно
     */
    hide() {
      hideModal(this.modal.id);
    }

    /**
     * Получает название модуля
     * @param {string} code
     * @returns {string}
     */
    getModuleName(code) {
      const names = {
        'test_part': '📝 Тестовая часть (1-16)',
        'task19': '💡 Задание 19',
        'task20': '⚙️ Задание 20',
        'task24': '📊 Задание 24',
        'task25': '💻 Задание 25'
      };
      return names[code] || code;
    }

    /**
     * Экранирует HTML
     * @param {string} str
     * @returns {string}
     */
    escapeHTML(str) {
      const div = document.createElement('div');
      div.textContent = str;
      return div.innerHTML;
    }

    /**
     * Уничтожает компонент
     */
    destroy() {
      this.hide();
    }
  }

  /**
   * Компонент формы создания задания
   * Главный компонент, управляющий всем процессом создания задания
   */


  class AssignmentForm {
    constructor(container) {
      this.container = container;

      // Состояние формы
      this.state = {
        assignmentType: null,
        modules: [],
        title: '',
        description: '',
        studentIds: [],
        deadline: null
      };

      // Компоненты
      this.questionBrowser = null;
      this.studentSelector = null;
      this.previewModal = null;

      // Флаги
      this.initialized = false;
      this.hasChanges = false;
      this.autoSaveInterval = null;

      // Данные с сервера
      this.availableModules = [];
      this.students = [];
    }

    /**
     * Инициализация компонента
     */
    async init() {
      console.log('Initializing AssignmentForm...');

      try {
        // Загружаем данные с сервера
        await this.loadData();

        // Настраиваем обработчики событий
        this.setupEventListeners();

        // Настраиваем валидацию
        this.setupValidation();

        // Запускаем автосохранение
        this.startAutoSave();

        // Создаем компоненты
        this.studentSelector = new StudentSelector(
          document.getElementById('student-selector-content')
        );
        await this.studentSelector.init(this.students);

        // Подписываемся на изменения StudentSelector ПОСЛЕ его создания
        this.studentSelector.on('change', (selectedIds) => {
          this.state.studentIds = selectedIds;
          console.log('[AssignmentForm] Students changed:', selectedIds);
          this.markAsChanged();
          this.updateCreateButton();
        });

        this.previewModal = new PreviewModal(
          document.getElementById('preview-modal')
        );

        this.initialized = true;
        console.log('AssignmentForm initialized');

      } catch (error) {
        console.error('AssignmentForm initialization error:', error);
        showToast('Ошибка инициализации формы', 'error');
      }
    }

    /**
     * Загружает данные с сервера
     */
    async loadData() {
      try {
        // Загружаем модули и учеников параллельно
        const [modulesResponse, studentsResponse] = await Promise.all([
          api.getModules(),
          api.getStudents({ limit: 100 })
        ]);

        this.availableModules = modulesResponse.modules || [];
        this.students = studentsResponse.students || [];

        console.log('Data loaded:', {
          modules: this.availableModules.length,
          students: this.students.length
        });

      } catch (error) {
        console.error('Failed to load data:', error);
        throw error;
      }
    }

    /**
     * Настраивает обработчики событий
     */
    setupEventListeners() {
      // Обработчики выбора типа задания
      const typeCards = this.container.querySelectorAll('.type-card');
      typeCards.forEach(card => {
        card.addEventListener('click', () => {
          const type = card.dataset.type;
          this.handleTypeSelection(type);
        });
      });

      // Обработчики полей формы
      const titleInput = document.getElementById('assignment-title');
      if (titleInput) {
        titleInput.addEventListener('input', (e) => {
          this.state.title = e.target.value;
          this.markAsChanged();
        });
      }

      const descriptionInput = document.getElementById('assignment-description');
      if (descriptionInput) {
        descriptionInput.addEventListener('input', (e) => {
          this.state.description = e.target.value;
          this.markAsChanged();
        });
      }

      // Обработчики дедлайна
      const deadlineQuickButtons = document.querySelectorAll('.deadline-quick-btn');
      deadlineQuickButtons.forEach(btn => {
        btn.addEventListener('click', () => {
          const days = parseInt(btn.dataset.days);
          this.setDeadlineFromDays(days);
          this.updateDeadlineButtons(btn);
        });
      });

      const deadlineInput = document.getElementById('deadline-input');
      if (deadlineInput) {
        deadlineInput.addEventListener('change', (e) => {
          this.state.deadline = e.target.value;
          this.markAsChanged();
          this.updateDeadlineButtons(null);
        });
      }

      const noDeadlineCheckbox = document.getElementById('no-deadline');
      if (noDeadlineCheckbox) {
        noDeadlineCheckbox.addEventListener('change', (e) => {
          if (e.target.checked) {
            this.state.deadline = null;
            if (deadlineInput) {
              deadlineInput.value = '';
              deadlineInput.disabled = true;
            }
            this.updateDeadlineButtons(null);
          } else {
            if (deadlineInput) {
              deadlineInput.disabled = false;
            }
          }
          this.markAsChanged();
        });
      }

      // УДАЛЕНО: Подписка перенесена в init() после создания studentSelector
    }

    /**
     * Настраивает валидацию полей
     */
    setupValidation() {
      const titleInput = document.getElementById('assignment-title');
      if (titleInput) {
        attachLiveValidation(titleInput, titleValidator);
      }

      const descriptionInput = document.getElementById('assignment-description');
      if (descriptionInput) {
        attachLiveValidation(descriptionInput, descriptionValidator);
      }
    }

    /**
     * Обрабатывает выбор типа задания
     * @param {string} type
     */
    async handleTypeSelection(type) {
      console.log('Type selected:', type);

      // Обновляем UI
      const typeCards = this.container.querySelectorAll('.type-card');
      typeCards.forEach(card => {
        card.classList.toggle('selected', card.dataset.type === type);
      });

      // Обновляем состояние
      this.state.assignmentType = type;
      this.markAsChanged();

      // Показываем следующие секции
      toggle('#question-selection-section');
      toggle('#details-section');
      toggle('#students-section');
      toggle('#deadline-section');

      // Обновляем прогресс
      updateProgress(2);

      // Загружаем интерфейс выбора вопросов
      await this.loadQuestionSelection(type);

      // Обновляем кнопку создания
      this.updateCreateButton();
    }

    /**
     * Загружает интерфейс выбора вопросов
     * @param {string} type
     */
    async loadQuestionSelection(type) {
      const container = document.getElementById('question-selection-content');
      if (!container) return;

      try {
        // Для смешанного типа показываем выбор модулей
        if (type === 'mixed') {
          await this.renderModuleSelection(container);
        }
        // Для конкретного модуля показываем браузер вопросов
        else if (['test_part', 'task19', 'task20', 'task24', 'task25'].includes(type)) {
          await this.renderQuestionBrowser(container, type);
        }
        // Для полного варианта ничего не показываем (автоматически генерируется)
        else if (type === 'full_exam') {
          container.innerHTML = `
          <p class="text-muted">Полный вариант ЕГЭ будет сгенерирован автоматически.</p>
        `;
        }

      } catch (error) {
        console.error('Failed to load question selection:', error);
        showToast('Ошибка загрузки вопросов', 'error');
      }
    }

    /**
     * Рендерит выбор модулей (для смешанного типа)
     * @param {HTMLElement} container
     */
    async renderModuleSelection(container) {
      container.innerHTML = `
      <div class="module-selector" id="module-selector">
        <p class="mb-md">Выберите модули для включения в задание:</p>
        <div id="module-list"></div>
      </div>
    `;

      const moduleList = container.querySelector('#module-list');

      this.availableModules.forEach(module => {
        const moduleItem = document.createElement('div');
        moduleItem.className = 'module-item';
        moduleItem.dataset.moduleCode = module.code;

        moduleItem.innerHTML = `
        <div class="module-header">
          <input type="checkbox" id="module-${module.code}" value="${module.code}">
          <label for="module-${module.code}" class="module-title">${module.name}</label>
          <span class="module-count">${module.total_questions} вопросов</span>
        </div>
        <div class="module-details">
          <div class="form-group">
            <label class="form-label">Способ отбора:</label>
            <select class="form-input module-selection-mode" data-module="${module.code}">
              <option value="random">Случайные вопросы</option>
              <option value="specific">Конкретные вопросы</option>
              <option value="all">Все вопросы</option>
            </select>
          </div>
          <div class="form-group module-count-group">
            <label class="form-label">Количество вопросов:</label>
            <input type="number" class="form-input module-question-count"
                   data-module="${module.code}"
                   min="1" max="${module.total_questions}"
                   placeholder="Введите количество">
          </div>
          <div class="form-group module-specific-group" style="display: none;">
            <button class="btn-secondary browse-questions-btn"
                    data-module="${module.code}">
              Выбрать вопросы
            </button>
            <div class="selected-questions-info" data-module="${module.code}">
              Выбрано: <strong>0</strong> вопросов
            </div>
          </div>
        </div>
      `;

        moduleList.appendChild(moduleItem);
      });

      // Настраиваем обработчики для модулей
      this.setupModuleEventListeners(container);
    }

    /**
     * Настраивает обработчики для модулей
     * @param {HTMLElement} container
     */
    setupModuleEventListeners(container) {
      // Обработчик checkbox модулей
      container.querySelectorAll('.module-item input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', (e) => {
          const moduleItem = e.target.closest('.module-item');
          const moduleCode = e.target.value;

          if (e.target.checked) {
            moduleItem.classList.add('selected');
            this.addModule(moduleCode);
          } else {
            moduleItem.classList.remove('selected');
            this.removeModule(moduleCode);
          }

          this.markAsChanged();
          this.updateCreateButton();
        });
      });

      // Обработчик изменения режима отбора
      container.querySelectorAll('.module-selection-mode').forEach(select => {
        select.addEventListener('change', (e) => {
          const moduleCode = e.target.dataset.module;
          const mode = e.target.value;
          const moduleItem = e.target.closest('.module-item');

          // Показываем/скрываем соответствующие поля
          const countGroup = moduleItem.querySelector('.module-count-group');
          const specificGroup = moduleItem.querySelector('.module-specific-group');

          if (mode === 'specific') {
            countGroup.style.display = 'none';
            specificGroup.style.display = 'block';
          } else if (mode === 'all') {
            countGroup.style.display = 'none';
            specificGroup.style.display = 'none';
          } else {
            countGroup.style.display = 'block';
            specificGroup.style.display = 'none';
          }

          this.updateModuleSelectionMode(moduleCode, mode);
          this.markAsChanged();
        });
      });

      // Обработчик ввода количества вопросов
      container.querySelectorAll('.module-question-count').forEach(input => {
        input.addEventListener('input', debounce((e) => {
          const moduleCode = e.target.dataset.module;
          const count = parseInt(e.target.value);

          this.updateModuleQuestionCount(moduleCode, count);
          this.markAsChanged();
        }, 500));
      });

      // Обработчик кнопок выбора конкретных вопросов
      container.querySelectorAll('.browse-questions-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const moduleCode = e.target.dataset.module;
          await this.openQuestionBrowser(moduleCode);
        });
      });
    }

    /**
     * Добавляет модуль в состояние
     * @param {string} moduleCode
     */
    addModule(moduleCode) {
      const existing = this.state.modules.find(m => m.module_code === moduleCode);
      if (!existing) {
        this.state.modules.push({
          module_code: moduleCode,
          selection_mode: 'random',
          question_count: null,
          question_ids: []
        });
      }
    }

    /**
     * Удаляет модуль из состояния
     * @param {string} moduleCode
     */
    removeModule(moduleCode) {
      this.state.modules = this.state.modules.filter(m => m.module_code !== moduleCode);
    }

    /**
     * Обновляет режим отбора для модуля
     * @param {string} moduleCode
     * @param {string} mode
     */
    updateModuleSelectionMode(moduleCode, mode) {
      const module = this.state.modules.find(m => m.module_code === moduleCode);
      if (module) {
        module.selection_mode = mode;

        // Сбрасываем данные в зависимости от режима
        if (mode === 'all') {
          module.question_count = null;
          module.question_ids = [];
        } else if (mode === 'random') {
          module.question_ids = [];
        } else if (mode === 'specific') {
          module.question_count = null;
        }
      }
    }

    /**
     * Обновляет количество вопросов для модуля
     * @param {string} moduleCode
     * @param {number} count
     */
    updateModuleQuestionCount(moduleCode, count) {
      const module = this.state.modules.find(m => m.module_code === moduleCode);
      if (module) {
        module.question_count = count;
      }
    }

    /**
     * Открывает браузер вопросов для модуля
     * @param {string} moduleCode
     */
    async openQuestionBrowser(moduleCode) {
      const module = this.state.modules.find(m => m.module_code === moduleCode);
      if (!module) return;

      try {
        // Создаем модальное окно с браузером вопросов
        const modal = document.createElement('div');
        modal.className = 'modal';
        modal.style.display = 'flex';

        modal.innerHTML = `
        <div class="modal-content" style="max-width: 800px;">
          <div class="modal-header">
            <h2>Выбор вопросов: ${this.getModuleName(moduleCode)}</h2>
            <button class="close-btn" id="browser-modal-close">×</button>
          </div>
          <div class="modal-body" id="browser-modal-body"></div>
          <div class="modal-footer">
            <button class="btn-secondary" id="browser-cancel">Отмена</button>
            <button class="btn-primary" id="browser-confirm">Применить</button>
          </div>
        </div>
      `;

        document.body.appendChild(modal);

        const browserContainer = modal.querySelector('#browser-modal-body');
        const questionBrowser = new QuestionBrowser(browserContainer);
        await questionBrowser.init(moduleCode, module.question_ids);

        // Обработчики кнопок
        modal.querySelector('#browser-modal-close').addEventListener('click', () => {
          document.body.removeChild(modal);
        });

        modal.querySelector('#browser-cancel').addEventListener('click', () => {
          document.body.removeChild(modal);
        });

        modal.querySelector('#browser-confirm').addEventListener('click', () => {
          const selectedIds = questionBrowser.getSelectedIds();
          module.question_ids = selectedIds;

          // Обновляем счетчик
          const infoElement = document.querySelector(`.selected-questions-info[data-module="${moduleCode}"]`);
          if (infoElement) {
            infoElement.innerHTML = `Выбрано: <strong>${selectedIds.length}</strong> ${this.pluralize(selectedIds.length)}`;
          }

          document.body.removeChild(modal);
          this.markAsChanged();
        });

      } catch (error) {
        console.error('Failed to open question browser:', error);
        showToast('Ошибка открытия браузера вопросов', 'error');
      }
    }

    /**
     * Рендерит браузер вопросов для одного модуля
     * @param {HTMLElement} container
     * @param {string} moduleCode
     */
    async renderQuestionBrowser(container, moduleCode) {
      this.questionBrowser = new QuestionBrowser(container);
      await this.questionBrowser.init(moduleCode);

      // ИСПРАВЛЕНО: Правильная инициализация модуля при выборе вопросов
      // Слушаем изменения выбора
      this.questionBrowser.on('change', (selectedIds) => {
        console.log('Questions selected:', selectedIds.length);

        // Ищем существующий модуль по module_code
        let module = this.state.modules.find(m => m.module_code === moduleCode);

        if (!module) {
          // Создаем новый модуль
          module = {
            module_code: moduleCode,
            selection_mode: 'specific',
            question_count: null,
            question_ids: selectedIds
          };
          this.state.modules.push(module);
          console.log('Created new module:', module);
        } else {
          // Обновляем существующий модуль
          module.selection_mode = 'specific';
          module.question_ids = selectedIds;
          module.question_count = null;
          console.log('Updated existing module:', module);
        }

        this.markAsChanged();
        this.updateCreateButton();
        console.log('Current state.modules:', this.state.modules);
      });
    }

    /**
     * Устанавливает дедлайн на N дней вперед
     * @param {number} days
     */
    setDeadlineFromDays(days) {
      const deadline = new Date();
      deadline.setDate(deadline.getDate() + days);
      deadline.setHours(23, 59, 0, 0);

      const deadlineInput = document.getElementById('deadline-input');
      if (deadlineInput) {
        // Форматируем для datetime-local input
        const formatted = deadline.toISOString().slice(0, 16);
        deadlineInput.value = formatted;
        deadlineInput.disabled = false;
      }

      const noDeadlineCheckbox = document.getElementById('no-deadline');
      if (noDeadlineCheckbox) {
        noDeadlineCheckbox.checked = false;
      }

      this.state.deadline = deadline.toISOString();
      this.markAsChanged();
    }

    /**
     * Обновляет визуальное состояние кнопок дедлайна
     * @param {HTMLElement|null} activeBtn
     */
    updateDeadlineButtons(activeBtn) {
      document.querySelectorAll('.deadline-quick-btn').forEach(btn => {
        btn.classList.toggle('selected', btn === activeBtn);
      });
    }

    /**
     * Валидирует форму
     * @returns {Object} - объект с ошибками
     */
    validate() {
      const errors = validateAssignmentForm(this.state);

      // Показываем ошибки в UI
      this.showErrors(errors);

      return errors;
    }

    /**
     * Показывает ошибки валидации в UI
     * @param {Object} errors
     */
    showErrors(errors) {
      // Очищаем все предыдущие ошибки
      document.querySelectorAll('.form-error.show').forEach(el => {
        el.classList.remove('show');
      });
      document.querySelectorAll('.form-input.error').forEach(el => {
        el.classList.remove('error');
      });

      // Показываем новые ошибки
      Object.entries(errors).forEach(([field, message]) => {
        let input = null;

        if (field === 'title') {
          input = document.getElementById('assignment-title');
        } else if (field === 'description') {
          input = document.getElementById('assignment-description');
        } else if (field === 'deadline') {
          input = document.getElementById('deadline-input');
        }

        if (input) {
          input.classList.add('error');
          const errorElement = input.parentElement?.querySelector('.form-error');
          if (errorElement) {
            errorElement.textContent = message;
            errorElement.classList.add('show');
          }
        }
      });
    }

    /**
     * Обновляет состояние кнопки создания задания
     */
    updateCreateButton() {
      const createBtn = document.getElementById('create-btn');
      const previewBtn = document.getElementById('preview-btn');

      if (!createBtn || !previewBtn) return;

      const isValid = this.isFormValid();

      // Отладочное логирование
      console.log('[updateCreateButton] isValid:', isValid);
      console.log('[updateCreateButton] state:', {
        assignmentType: this.state.assignmentType,
        title: this.state.title,
        titleLength: this.state.title?.trim()?.length,
        studentIds: this.state.studentIds,
        studentIdsLength: this.state.studentIds?.length,
        modules: this.state.modules,
        modulesLength: this.state.modules?.length
      });

      createBtn.disabled = !isValid;
      previewBtn.disabled = !isValid;
    }

    /**
     * Проверяет, валидна ли форма (базовая проверка)
     * @returns {boolean}
     */
    isFormValid() {
      // ИСПРАВЛЕНО: Добавлена проверка наличия выбранных вопросов для типов заданий, которые требуют их

      // Базовые проверки
      if (!this.state.assignmentType) return false;
      if (this.state.title.trim().length < 3) return false;
      if (this.state.studentIds.length === 0) return false;

      // ИСПРАВЛЕНО: Проверка наличия вопросов для типов, которые их требуют
      const needsModules = ['task19', 'task20', 'task24', 'task25', 'mixed', 'test_part'].includes(this.state.assignmentType);

      if (needsModules) {
        // Проверяем наличие модулей
        if (!this.state.modules || this.state.modules.length === 0) {
          return false;
        }

        // Проверяем что каждый модуль имеет выбранные вопросы
        for (const module of this.state.modules) {
          if (module.selection_mode === 'specific') {
            if (!module.question_ids || module.question_ids.length === 0) {
              return false;
            }
          } else if (module.selection_mode === 'random') {
            if (!module.question_count || module.question_count < 1) {
              return false;
            }
          }
          // Для 'all' модуль валиден по умолчанию
        }
      }

      return true;
    }

    /**
     * Показывает предпросмотр задания
     */
    showPreview() {
      if (this.previewModal) {
        this.previewModal.show(this.state, this.getAssignmentData());
      }
    }

    /**
     * Получает данные для отправки на сервер
     * @returns {Object}
     */
    getAssignmentData() {
      const data = {
        assignment_type: this.state.assignmentType,
        title: this.state.title.trim(),
        description: this.state.description.trim() || null,
        deadline: this.state.deadline || null,
        student_ids: this.state.studentIds,
        modules: this.state.modules
      };

      // Добавляем camelCase версии для PreviewModal
      data.assignmentType = data.assignment_type;
      data.studentIds = data.student_ids;

      return data;
    }

    /**
     * Получает текущее состояние формы
     * @returns {Object}
     */
    getState() {
      return { ...this.state };
    }

    /**
     * Загружает состояние в форму
     * @param {Object} state
     */
    loadState(state) {
      this.state = { ...state };

      // Обновляем UI в соответствии с загруженным состоянием
      this.updateUIFromState();
    }

    /**
     * Обновляет UI на основе текущего состояния
     */
    updateUIFromState() {
      // Тип задания
      if (this.state.assignmentType) {
        const typeCard = this.container.querySelector(
          `.type-card[data-type="${this.state.assignmentType}"]`
        );
        if (typeCard) {
          typeCard.click();
        }
      }

      // Название и описание
      const titleInput = document.getElementById('assignment-title');
      if (titleInput) {
        titleInput.value = this.state.title;
      }

      const descriptionInput = document.getElementById('assignment-description');
      if (descriptionInput) {
        descriptionInput.value = this.state.description;
      }

      // Дедлайн
      if (this.state.deadline) {
        const deadlineInput = document.getElementById('deadline-input');
        if (deadlineInput) {
          const formatted = new Date(this.state.deadline).toISOString().slice(0, 16);
          deadlineInput.value = formatted;
        }
      }

      // Ученики
      if (this.studentSelector && this.state.studentIds.length > 0) {
        this.studentSelector.setSelected(this.state.studentIds);
      }

      this.updateCreateButton();
    }

    /**
     * Проверяет наличие несохраненных изменений
     * @returns {boolean}
     */
    hasUnsavedChanges() {
      return this.hasChanges;
    }

    /**
     * Помечает форму как измененную
     */
    markAsChanged() {
      this.hasChanges = true;
    }

    /**
     * Сбрасывает флаг изменений
     */
    resetChanges() {
      this.hasChanges = false;
    }

    /**
     * Запускает автосохранение черновика
     */
    startAutoSave() {
      this.autoSaveInterval = setInterval(() => {
        if (this.hasChanges && this.isFormValid()) {
          draftManager.saveCurrent(this.state);
          console.log('Draft auto-saved');
        }
      }, 30000); // Каждые 30 секунд
    }

    /**
     * Останавливает автосохранение
     */
    stopAutoSave() {
      if (this.autoSaveInterval) {
        clearInterval(this.autoSaveInterval);
        this.autoSaveInterval = null;
      }
    }

    /**
     * Получает название модуля по коду
     * @param {string} code
     * @returns {string}
     */
    getModuleName(code) {
      const module = this.availableModules.find(m => m.code === code);
      return module ? module.name : code;
    }

    /**
     * Склонение слова "вопрос"
     * @param {number} count
     * @returns {string}
     */
    pluralize(count) {
      const mod10 = count % 10;
      const mod100 = count % 100;

      if (mod10 === 1 && mod100 !== 11) {
        return 'вопрос';
      } else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) {
        return 'вопроса';
      } else {
        return 'вопросов';
      }
    }

    /**
     * Очищает форму
     */
    clear() {
      this.state = {
        assignmentType: null,
        modules: [],
        title: '',
        description: '',
        studentIds: [],
        deadline: null
      };

      this.updateUIFromState();
      this.resetChanges();
    }

    /**
     * Уничтожает компонент
     */
    destroy() {
      this.stopAutoSave();

      if (this.questionBrowser) {
        this.questionBrowser.destroy();
      }

      if (this.studentSelector) {
        this.studentSelector.destroy();
      }

      if (this.previewModal) {
        this.previewModal.destroy();
      }
    }
  }

  /**
   * Главный файл приложения WebApp для учителей
   * Точка входа и инициализация всех компонентов
   */


  class TeacherApp {
    constructor() {
      this.initialized = false;
      this.teacherProfile = null;
      this.assignmentForm = null;
    }

    /**
     * Инициализация приложения
     */
    async init() {
      console.log('Initializing Teacher WebApp...');

      try {
        // 1. Инициализация Telegram WebApp
        const telegramInitialized = telegramAuth.init();
        if (!telegramInitialized) {
          this.showError('Ошибка инициализации Telegram WebApp');
          return;
        }

        // 2. Проверка аутентификации и загрузка профиля
        await this.loadTeacherProfile();

        // 3. Инициализация компонентов
        await this.initComponents();

        // 4. Настройка обработчиков событий
        this.setupEventListeners();

        // 5. Загрузка черновика (если есть)
        this.loadDraft();

        // 6. Скрываем экран загрузки
        hideLoadingScreen();

        // 7. Показываем приложение
        document.getElementById('app').style.display = 'block';

        this.initialized = true;
        console.log('Teacher WebApp initialized successfully');

      } catch (error) {
        console.error('Initialization error:', error);
        this.showError(error.message || 'Ошибка инициализации приложения');
      }
    }

    /**
     * Загружает профиль учителя
     */
    async loadTeacherProfile() {
      try {
        console.log('Loading teacher profile...');
        this.teacherProfile = await api.getTeacherProfile();
        console.log('Teacher profile loaded:', this.teacherProfile);
      } catch (error) {
        console.error('Failed to load teacher profile:', error);

        if (error instanceof APIError && error.isAuthError()) {
          throw new Error('Ошибка аутентификации. У вас нет доступа к режиму учителя.');
        }

        throw new Error('Не удалось загрузить профиль учителя. Попробуйте позже.');
      }
    }

    /**
     * Инициализирует компоненты
     */
    async initComponents() {
      console.log('Initializing components...');

      // Создаем форму создания задания
      const formContainer = document.getElementById('assignment-form');
      if (formContainer) {
        this.assignmentForm = new AssignmentForm(formContainer);
        await this.assignmentForm.init();
      }
    }

    /**
     * Настраивает обработчики событий
     */
    setupEventListeners() {
      // Кнопка закрытия
      const closeBtn = document.getElementById('close-btn');
      if (closeBtn) {
        closeBtn.addEventListener('click', () => this.handleClose());
      }

      // Кнопка сохранения черновика
      const saveDraftBtn = document.getElementById('save-draft-btn');
      if (saveDraftBtn) {
        saveDraftBtn.addEventListener('click', () => this.handleSaveDraft());
      }

      // Кнопка предпросмотра
      const previewBtn = document.getElementById('preview-btn');
      if (previewBtn) {
        previewBtn.addEventListener('click', () => this.handlePreview());
      }

      // Кнопка создания задания
      const createBtn = document.getElementById('create-btn');
      if (createBtn) {
        createBtn.addEventListener('click', () => this.handleCreate());
      }

      // Предотвращаем закрытие при несохраненных изменениях
      window.addEventListener('beforeunload', (e) => {
        if (this.assignmentForm?.hasUnsavedChanges()) {
          e.preventDefault();
          e.returnValue = '';
        }
      });

      // Telegram WebApp события
      if (telegramAuth.tg) {
        // Обработка закрытия WebApp
        telegramAuth.tg.onEvent('backButtonClicked', () => {
          this.handleClose();
        });
      }
    }

    /**
     * Загружает черновик из LocalStorage
     */
    loadDraft() {
      if (!this.assignmentForm) return;

      const draft = draftManager.loadCurrent();
      if (draft) {
        console.log('Draft found, loading...');

        const age = draftManager.getCurrentAge();
        const ageMinutes = Math.floor(age / 60000);

        // Спрашиваем пользователя, хочет ли он загрузить черновик
        const message = `Найден черновик задания (создан ${ageMinutes} мин. назад). Загрузить его?`;

        telegramAuth.showPopup({
          title: 'Черновик найден',
          message,
          buttons: [
            { id: 'load', type: 'default', text: 'Загрузить' },
            { id: 'discard', type: 'destructive', text: 'Отменить' }
          ]
        }, (buttonId) => {
          if (buttonId === 'load') {
            this.assignmentForm.loadState(draft);
            showToast('Черновик загружен', 'success');
          } else {
            draftManager.removeCurrent();
          }
        });
      }
    }

    /**
     * Обработчик закрытия приложения
     */
    async handleClose() {
      if (this.assignmentForm?.hasUnsavedChanges()) {
        const confirmed = await telegramAuth.showConfirm(
          'У вас есть несохраненные изменения. Вы уверены, что хотите выйти?'
        );

        if (!confirmed) {
          return;
        }
      }

      telegramAuth.close();
    }

    /**
     * Обработчик сохранения черновика
     */
    handleSaveDraft() {
      if (!this.assignmentForm) return;

      try {
        const state = this.assignmentForm.getState();
        draftManager.saveCurrent(state);

        showToast('Черновик сохранен', 'success');
        telegramAuth.hapticFeedback('success');

        // Также сохраняем на сервер (опционально)
        this.saveDraftToServer(state);

      } catch (error) {
        console.error('Failed to save draft:', error);
        showToast('Ошибка сохранения черновика', 'error');
      }
    }

    /**
     * Сохраняет черновик на сервер
     */
    async saveDraftToServer(state) {
      try {
        await api.saveDraft(state);
        console.log('Draft saved to server');
      } catch (error) {
        console.error('Failed to save draft to server:', error);
        // Не показываем ошибку пользователю, т.к. черновик уже сохранен локально
      }
    }

    /**
     * Обработчик предпросмотра
     */
    handlePreview() {
      if (!this.assignmentForm) return;

      try {
        const errors = this.assignmentForm.validate();

        if (Object.keys(errors).length > 0) {
          showToast('Исправьте ошибки в форме', 'warning');
          return;
        }

        this.assignmentForm.showPreview();
        telegramAuth.hapticFeedback('light');

      } catch (error) {
        console.error('Preview error:', error);
        showToast('Ошибка создания предпросмотра', 'error');
      }
    }

    /**
     * Обработчик создания задания
     */
    async handleCreate() {
      if (!this.assignmentForm) return;

      try {
        // Валидация
        const errors = this.assignmentForm.validate();
        if (Object.keys(errors).length > 0) {
          showToast('Исправьте ошибки в форме', 'warning');
          return;
        }

        // Подтверждение
        const confirmed = await telegramAuth.showConfirm(
          'Вы уверены, что хотите создать это задание?'
        );

        if (!confirmed) {
          return;
        }

        // Показываем загрузку
        showLoadingScreen('Создание задания...');

        // Получаем данные формы
        const assignmentData = this.assignmentForm.getAssignmentData();

        // Отправляем на сервер
        const response = await api.createAssignment(assignmentData);

        // Удаляем черновик
        draftManager.removeCurrent();

        // Показываем успех
        hideLoadingScreen();
        telegramAuth.hapticFeedback('success');

        const message = `Задание "${assignmentData.title}" успешно создано и отправлено ${response.students_notified} ученикам!`;

        telegramAuth.showPopup({
          title: 'Успех!',
          message,
          buttons: [
            { id: 'close', type: 'default', text: 'Закрыть' }
          ]
        }, () => {
          telegramAuth.close();
        });

      } catch (error) {
        hideLoadingScreen();
        console.error('Failed to create assignment:', error);

        let errorMessage = 'Не удалось создать задание. Попробуйте еще раз.';

        if (error instanceof APIError) {
          errorMessage = error.getUserMessage();

          if (error.isValidationError()) {
            const validationErrors = error.getValidationErrors();
            this.assignmentForm.showErrors(validationErrors);
          }
        }

        showToast(errorMessage, 'error');
        telegramAuth.hapticFeedback('error');
      }
    }

    /**
     * Показывает ошибку
     */
    showError(message) {
      hideLoadingScreen();

      const errorContainer = document.createElement('div');
      errorContainer.style.cssText = `
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 2rem;
      text-align: center;
    `;

      errorContainer.innerHTML = `
      <div style="font-size: 3rem; margin-bottom: 1rem;">⚠️</div>
      <h2 style="margin-bottom: 1rem;">Ошибка</h2>
      <p style="color: var(--tg-theme-hint-color); margin-bottom: 2rem;">${message}</p>
      <button onclick="window.Telegram.WebApp.close()" style="
        padding: 12px 24px;
        background: var(--tg-theme-button-color);
        color: var(--tg-theme-button-text-color);
        border: none;
        border-radius: 8px;
        font-size: 16px;
        cursor: pointer;
      ">Закрыть</button>
    `;

      document.body.innerHTML = '';
      document.body.appendChild(errorContainer);
    }
  }

  // Инициализация приложения при загрузке DOM
  document.addEventListener('DOMContentLoaded', () => {
    const app = new TeacherApp();
    app.init();

    // Для отладки - сохраняем в window (временно для диагностики)
    window.teacherApp = app;

    // После инициализации assignmentForm может быть еще undefined
    // Сохраняем его после полной инициализации
    setTimeout(() => {
      window.assignmentForm = app.assignmentForm;
      console.log('Debug: assignmentForm set to window', !!window.assignmentForm);
    }, 100);
  });

  exports.TeacherApp = TeacherApp;

  return exports;

})({});
//# sourceMappingURL=bundle-v2.js.map
