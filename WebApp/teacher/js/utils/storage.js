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

// Экспортируем экземпляры
export const storage = new Storage();
export const draftManager = new DraftManager();
export const cacheManager = new CacheManager();

// Автоматическая очистка устаревшего кеша при загрузке
cacheManager.clearExpired();
