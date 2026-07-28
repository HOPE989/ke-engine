"""显式验证 Chat -> MCP -> 文档检索 -> Grounded Answer 的本地闭环。"""

import argparse
import asyncio
import json

import httpx


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--user-id", default="mock-user")
    parser.add_argument(
        "--chat-url",
        default="http://127.0.0.1:8001/api/v1/chat/completions",
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            args.chat_url,
            headers={"X-Mock-User-Id": args.user_id},
            json={"content": args.question},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line.removeprefix("data: "))
                    if "content" in payload:
                        print(payload["content"], end="", flush=True)
                    if payload.get("code") == "COMPLETION_FAILED":
                        raise RuntimeError(payload["message"])
    print()


if __name__ == "__main__":
    asyncio.run(main())
