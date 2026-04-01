from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import engine
from app.routes.repos import router as repos_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Engine is created on import; nothing extra needed at startup
    yield
    await engine.dispose()


app = FastAPI(title="Breakdown", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(repos_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
