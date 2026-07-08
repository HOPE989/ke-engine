"""Agent API 进程入口。"""

from app.services.agent_api.app import create_app

app = create_app()
