"""
Routes для B2B API.
"""

from b2b_api.routes.check import router as check_router
from b2b_api.routes.questions import router as questions_router
from b2b_api.routes.client import router as client_router
from b2b_api.routes.admin import router as admin_router

__all__ = [
    'check_router',
    'questions_router',
    'client_router',
    'admin_router',
]
