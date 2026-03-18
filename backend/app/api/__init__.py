from fastapi import APIRouter

from .admin import router as admin_router
from .auth import router as auth_router
from .carousel import router as carousel_router
from .cases import router as cases_router
from .config import router as config_router
from .fracture import router as fracture_router
from .review import router as review_router
from .worker import router as worker_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(admin_router)
api_router.include_router(cases_router)
api_router.include_router(config_router)
api_router.include_router(worker_router)
api_router.include_router(review_router)
api_router.include_router(carousel_router)
api_router.include_router(fracture_router)

__all__ = ["api_router"]
