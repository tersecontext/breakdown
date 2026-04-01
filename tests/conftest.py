import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("SOURCE_DIRS", "/tmp")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
