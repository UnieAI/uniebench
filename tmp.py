import asyncio
import json
import logging

import aiohttp

# 設定 logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def send_request(request_number=-1):
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "http://localhost:30000/v1/completions",
            json={
                "model": "pearl",
                "prompt": "Hello",
                "stream": True,
                "max_tokens": 768,
            },
        ) as response:
            logger.info(f"Status: {response.status}")

            full_response = ""
            async for line in response.content:
                if line:
                    line_str = line.decode("utf-8").strip()
                    if line_str.startswith("data: "):
                        data = line_str[6:]  # 移除 "data: " 前綴
                        if data == "[DONE]":
                            logger.info(f"No. {request_number} Done.")
                            # logger.info(f"No. {request_number} 完整回應: {full_response}")
                            break
                        try:
                            chunk = json.loads(data)
                            if "choices" in chunk and chunk["choices"]:
                                delta = chunk["choices"][0].get("delta", {})
                                if "text" in delta:
                                    full_response += delta["text"]
                                elif "content" in delta:
                                    full_response += delta["content"]
                        except json.JSONDecodeError:
                            continue


async def main():
    NUMBERS = 128
    # NUMBERS = 2

    # 第一次執行
    tasks = [send_request(i) for i in range(NUMBERS)]
    await asyncio.gather(*tasks)

    # # 第二次執行 - 重新建立 tasks
    # tasks = [send_request() for _ in range(NUMBERS)]
    # await asyncio.gather(*tasks)

    # # 第三次執行 - 重新建立 tasks
    # tasks = [send_request() for _ in range(NUMBERS)]
    # await asyncio.gather(*tasks)

    # await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
