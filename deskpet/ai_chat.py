"""Optional OpenAI-compatible AI client. It never runs unless explicitly enabled."""

from __future__ import annotations

import json
import queue
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class AiReply:
    request_id: int
    text: str
    error: str | None = None


class OptionalAiClient:
    def __init__(self) -> None:
        self._requests: queue.Queue[tuple[int, str, dict[str, str]]] = queue.Queue()
        self._replies: queue.Queue[AiReply] = queue.Queue()
        self._next_id = 1
        self._worker = threading.Thread(target=self._run, name="DeskPetAI", daemon=True)
        self._worker.start()

    def submit(self, message: str, config: dict[str, str]) -> int:
        request_id = self._next_id
        self._next_id += 1
        self._requests.put((request_id, message[:4000], dict(config)))
        return request_id

    def poll(self) -> list[AiReply]:
        replies: list[AiReply] = []
        while True:
            try:
                replies.append(self._replies.get_nowait())
            except queue.Empty:
                return replies

    def _run(self) -> None:
        while True:
            request_id, message, config = self._requests.get()
            try:
                endpoint = config["base_url"].rstrip("/")
                if not endpoint.endswith("/chat/completions"):
                    endpoint += "/chat/completions"
                payload = json.dumps({
                    "model": config["model"],
                    "messages": [
                        {"role": "system", "content": "你是桌宠小狗，回答简短、友好，使用中文。"},
                        {"role": "user", "content": message},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 180,
                }).encode("utf-8")
                request = urllib.request.Request(
                    endpoint, data=payload, method="POST",
                    headers={"Content-Type": "application/json", "Authorization": "Bearer " + config["api_key"]},
                )
                with urllib.request.urlopen(request, timeout=25) as response:
                    raw = response.read(1024 * 1024)
                data = json.loads(raw.decode("utf-8"))
                text = str(data["choices"][0]["message"]["content"]).strip()
                self._replies.put(AiReply(request_id, text or "我一时不知道怎么回答。"))
            except (KeyError, ValueError, urllib.error.URLError, urllib.error.HTTPError, OSError) as error:
                self._replies.put(AiReply(request_id, "", "AI 请求失败：" + str(error)[:120]))
