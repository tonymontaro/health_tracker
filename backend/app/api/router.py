from fastapi import APIRouter

from app.api import auth, chat, history, profile, shopping, today

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(today.router)
api_router.include_router(history.router)
api_router.include_router(shopping.router)
api_router.include_router(chat.router)
api_router.include_router(profile.router)
