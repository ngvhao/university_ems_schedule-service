from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
from sqlalchemy import text
from app.middleware.auth_middleware import AuthMiddleware
from app.routes import schedule
from app.database import get_db
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.services.class_weekly_schedule import ClassWeeklyScheduleService

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("app.log")
    ]
)

app = FastAPI(title="Schedule Service")

@app.middleware("http")
async def custom_error_handling_middleware(request: Request, call_next):
    try:
        response = await call_next(request)
        logger.debug(f"Response status: {response.status_code} for {request.url.path}")
        return response
    except HTTPException as e:
        logger.debug(f"Caught HTTPException: {str(e)}")
        return JSONResponse(
            status_code=e.status_code,
            content={"detail": e.detail},
            headers=e.headers
        )
    except Exception as e:
        logger.error(f"Unexpected error for {request.url.path}: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_PATHS = [
    "/docs",
    "/redoc",
    "/openapi.json",
    "/testing-db",
    "/schedules/calculating"
]

app.add_middleware(AuthMiddleware, public_paths=PUBLIC_PATHS)

app.include_router(schedule.router)

@app.get("/testing-db")
async def root(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT 1"))
        # value = result.scalar()  
        logger.debug("Successfully tested database connection")
        result_2 = await ClassWeeklyScheduleService.getClassWeeklySchedule(1, db)
        print(result_2)
        return {"message": "Welcome to the API", "db_test": result_2}
    except Exception as e:
        logger.error(f"Error in root endpoint: {str(e)}")
        return {"error": str(e)}

handler = Mangum(app)