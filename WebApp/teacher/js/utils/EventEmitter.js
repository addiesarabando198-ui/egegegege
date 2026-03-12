/**
 * Простой Event Emitter для компонентов
 */
export class EventEmitter {
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
