/**
 * API клиент для взаимодействия с backend
 * Все запросы автоматически включают аутентификационные данные
 */

import { telegramAuth } from './auth.js';

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
export const api = new APIClient();
export { APIError };
