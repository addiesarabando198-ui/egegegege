"""
Валидация URL для защиты от SSRF-атак.

Запрещает:
- Приватные IP-диапазоны (RFC 1918)
- Localhost, loopback
- Link-local адреса
- Cloud metadata endpoints
- Не-HTTPS схемы
"""

import ipaddress
import logging
from urllib.parse import urlparse
from typing import Optional

logger = logging.getLogger(__name__)

# Запрещённые хосты
_BLOCKED_HOSTNAMES = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.google",
    "169.254.169.254",
    "metadata",
    "[::1]",
})


def is_private_ip(ip_str: str) -> bool:
    """Проверяет, является ли IP приватным или зарезервированным."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    except ValueError:
        return False


def validate_callback_url(url: str) -> Optional[str]:
    """
    Валидирует callback URL.

    Returns:
        None если URL безопасный, строку с описанием ошибки если нет.
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format"

    # Только HTTPS
    if parsed.scheme != "https":
        return "callback_url must use HTTPS scheme"

    hostname = parsed.hostname
    if not hostname:
        return "callback_url must have a valid hostname"

    # Проверяем на запрещённые хосты
    if hostname.lower() in _BLOCKED_HOSTNAMES:
        return f"callback_url hostname '{hostname}' is not allowed"

    # Проверяем на приватные IP
    if is_private_ip(hostname):
        return f"callback_url must not point to a private IP address"

    # Проверяем порт (запрещаем нестандартные порты для metadata)
    port = parsed.port
    if port and port not in (443, 8443):
        return "callback_url must use standard HTTPS port (443 or 8443)"

    # Максимальная длина URL
    if len(url) > 2048:
        return "callback_url must not exceed 2048 characters"

    return None
