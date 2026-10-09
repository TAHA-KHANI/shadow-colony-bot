import os

os.environ.setdefault("BOT_TOKEN", "123456:TEST_TOKEN")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/test")
os.environ.setdefault("GROUP_ID", "-100123456")
os.environ.setdefault("ADMIN_IDS", "123")
os.environ.setdefault("GAME_SECRET", "game-secret-for-test-suite")
os.environ.setdefault("BACKUP_SECRET", "backup-secret-for-test-suite")

