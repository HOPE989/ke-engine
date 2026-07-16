"""Chat API 进程入口。"""

from app.services.chat_api.app import create_app

app = create_app()
