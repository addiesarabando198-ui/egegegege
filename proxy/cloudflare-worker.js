/**
 * Cloudflare Worker — прокси для Claude API (Anthropic).
 *
 * Ключевые особенности:
 * - Тело запроса и ответа передаётся как ReadableStream (без буферизации)
 * - Это позволяет проксировать большие payload'ы (base64-изображения для Vision)
 *   и streaming-ответы (SSE) без таймаутов
 * - Health check на /health для проверки работоспособности
 * - Обработка ошибок с информативными сообщениями
 *
 * ВАЖНО: Этот код нужно ЗАДЕПЛОИТЬ в Cloudflare!
 *
 * Деплой через CLI:
 *   cd proxy && npx wrangler deploy
 *
 * Или через дашборд Cloudflare:
 *   1. Workers & Pages → ваш Worker (claude-api-proxy)
 *   2. Кнопка «Edit code» / «Quick edit»
 *   3. Вставить ВЕСЬ этот код (заменив старый)
 *   4. Нажать «Save and deploy»
 */

const TARGET_BASE = "https://api.anthropic.com";

// Заголовки, которые пробрасываем от клиента к Claude API
const FORWARD_REQUEST_HEADERS = [
  "x-api-key",
  "anthropic-version",
  "content-type",
  "anthropic-beta",
  "accept",
];

// Заголовки, которые пробрасываем от Claude API к клиенту
const FORWARD_RESPONSE_HEADERS = [
  "content-type",
  "request-id",
  "x-request-id",
  "retry-after",
];

export default {
  async fetch(request) {
    // Health check
    const url = new URL(request.url);
    if (url.pathname === "/health") {
      return new Response(
        JSON.stringify({ status: "ok", proxy: "claude-api", ts: Date.now() }),
        { status: 200, headers: { "content-type": "application/json" } }
      );
    }

    // CORS preflight
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: {
          "Access-Control-Allow-Origin": "*",
          "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
          "Access-Control-Allow-Headers": FORWARD_REQUEST_HEADERS.join(", "),
          "Access-Control-Max-Age": "86400",
        },
      });
    }

    try {
      // Формируем целевой URL (сохраняем путь и query string)
      const targetUrl = `${TARGET_BASE}${url.pathname}${url.search}`;

      // Собираем заголовки для проксируемого запроса
      const headers = new Headers();
      for (const name of FORWARD_REQUEST_HEADERS) {
        const value = request.headers.get(name);
        if (value) {
          headers.set(name, value);
        }
      }

      // Проксируем запрос — тело передаём как stream (без буферизации!)
      // Это критично для Vision-запросов с base64-изображениями
      const response = await fetch(targetUrl, {
        method: request.method,
        headers,
        body: request.body, // ReadableStream — НЕ буферизуется
      });

      // Собираем заголовки ответа
      const responseHeaders = new Headers();
      responseHeaders.set("Access-Control-Allow-Origin", "*");
      for (const name of FORWARD_RESPONSE_HEADERS) {
        const value = response.headers.get(name);
        if (value) {
          responseHeaders.set(name, value);
        }
      }

      // Возвращаем ответ — тело тоже как stream (без буферизации!)
      // Это критично для SSE streaming-ответов от Claude API
      return new Response(response.body, {
        status: response.status,
        headers: responseHeaders,
      });
    } catch (err) {
      // Ошибка подключения к upstream (Claude API)
      return new Response(
        JSON.stringify({
          type: "error",
          error: {
            type: "proxy_error",
            message: `Proxy error: ${err.message}`,
          },
        }),
        {
          status: 502,
          headers: {
            "content-type": "application/json",
            "Access-Control-Allow-Origin": "*",
          },
        }
      );
    }
  },
};
