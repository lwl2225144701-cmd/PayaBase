"""LLM Client.

LLM calling client (OpenAI / Ollama / OpenAI-compatible REST).

设计原则:
- 对外方法保持稳定: chat / stream_chat / chat_with_tools / chat_with_image
- provider 在构造时规范化,内部只识别三种: ollama / openai(包含 openai_compatible)
- 业务层不直接 new LLMClient,统一通过 core.llm.factory.get_llm_client() 取得
"""

from typing import Any, Generator, Optional
import logging
import json
import requests

from openai import OpenAI

from core.config import settings
from core.llm.profiles import (
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_OPENAI_COMPATIBLE,
)

logger = logging.getLogger(__name__)


def _normalize_provider(provider: Optional[str], base_url: Optional[str], fallback: str) -> str:
    """统一 provider 命名:openai_compatible -> openai;其他/空 -> 推断或回退。"""
    if provider:
        p = provider.strip().lower()
        if p == PROVIDER_OPENAI_COMPATIBLE:
            return PROVIDER_OPENAI
        if p in (PROVIDER_OPENAI, PROVIDER_OLLAMA):
            return p
    if base_url and "ollama" in base_url:
        return PROVIDER_OLLAMA
    return fallback or PROVIDER_OPENAI


class LLMClient:
    """LLM calling client."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        timeout: float = 30.0,
        api_header_name: Optional[str] = None,
        api_header_prefix: Optional[str] = None,
    ):
        """Initialize LLM client.

        Args:
            api_key: API key
            base_url: API base URL
            model: Model name
            provider: "ollama" or "openai" (default: auto-detect from base_url, then settings)
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or settings.llm_base_url
        self.model = model or settings.llm_model
        self.api_key = api_key or settings.llm_api_key
        self.timeout = timeout
        self.api_header_name = (api_header_name or "").strip()
        self.api_header_prefix = "Bearer " if api_header_prefix is None else api_header_prefix

        # Determine provider: explicit > auto-detect > global setting
        self.provider = _normalize_provider(provider, base_url, settings.llm_provider)

        if self.provider == "ollama":
            self.client = None
            # Strip /v1 suffix so native /api/chat endpoint works
            if self.base_url.rstrip("/").endswith("/v1"):
                self.base_url = self.base_url.rstrip("/")[:-3]
        else:
            self.client = None
            if not self._use_custom_openai_rest():
                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=timeout,
                )

    def chat(
        self,
        messages: list[dict],
        stream: bool = False,
        temperature: float = 0.7,
    ) -> str | Generator:
        """Chat completion.

        Args:
            messages: Message list
            stream: Enable streaming
            temperature: Temperature

        Returns:
            Response content or generator
        """
        stream = bool(stream)  # ensure bool (handle int 0/1 passed in)
        logger.info(f"[LLM] chat请求, provider={self.provider}, model={self.model}, stream={stream}, messages={len(messages)}")

        if self.provider == "ollama":
            return self._ollama_chat(messages, stream)

        if self._use_custom_openai_rest():
            return self._openai_rest_chat(messages, stream=stream, temperature=temperature)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=stream,
            temperature=temperature,
        )

        if stream:
            return response

        return response.choices[0].message.content

    def _ollama_chat(self, messages: list[dict], stream: bool = False) -> str | Generator:
        """Ollama chat completion."""
        # Convert messages to Ollama format
        ollama_messages = []
        for msg in messages:
            ollama_messages.append({
                "role": msg["role"],
                "content": msg["content"],
            })

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": stream,
        }

        if stream:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=120,
            )
            return self._stream_ollama(response)
        else:
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=120,
            )
            result = response.json()
            return result.get("message", {}).get("content", "")

    def _stream_ollama(self, response) -> Generator[str, None, None]:
        """Stream Ollama response."""
        import json
        for line in response.iter_lines():
            if line:
                data = line.decode("utf-8")
                try:
                    if data.startswith("data: "):
                        chunk = json.loads(data[6:])
                    else:
                        chunk = json.loads(data)
                    if "message" in chunk:
                        msg = chunk["message"]
                        content = msg.get("content", "")
                        if content:
                            yield content
                except:
                    pass

    def chat_with_tools(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        stream: bool = False,
    ) -> dict:
        """Chat with tool calling.

        Args:
            messages: Message list
            tools: Tool definitions
            stream: Enable streaming

        Returns:
            Response with tool calls
        """
        if self.provider == "ollama":
            content = self._ollama_chat(messages, False)
            return {"content": content, "tool_calls": []}

        if self._use_custom_openai_rest():
            return self._openai_rest_chat(messages, stream=False, tools=tools)

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=stream,
        )

        message = response.choices[0].message
        return {
            "content": message.content,
            "tool_calls": message.tool_calls or [],
        }

    def chat_with_image(
        self,
        image_base64: str,
        prompt: str,
        mime_type: str = "image/jpeg",
    ) -> str:
        """Chat with image input via OpenAI-compatible vision API.

        Args:
            image_base64: Base64-encoded image data
            prompt: Text prompt for image analysis
            mime_type: Image MIME type

        Returns:
            Model response text

        Raises:
            RuntimeError: If vision model is not configured or provider doesn't support vision
        """
        if not settings.llm_vision_model:
            raise RuntimeError(
                "未配置 Vision 模型。请设置 LLM_VISION_MODEL 环境变量（如 qwen-vl-plus）。"
            )

        # 本地 Ollama 默认不支持 vision
        if self.provider == PROVIDER_OLLAMA:
            raise RuntimeError(
                "当前 provider=ollama 不支持 Vision API,请在 .env 配置 LLM_VISION_PROVIDER "
                "为 openai / openai_compatible,并提供 LLM_VISION_API_KEY / LLM_VISION_BASE_URL。"
            )

        # Vision may use a different API endpoint than the main LLM
        vision_api_key = settings.llm_vision_api_key or settings.llm_api_key
        vision_base_url = settings.llm_vision_base_url or settings.llm_base_url

        client = OpenAI(api_key=vision_api_key, base_url=vision_base_url)
        model = settings.llm_vision_model

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_base64}",
                        },
                    },
                ],
            }
        ]

        response = client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
        )
        return response.choices[0].message.content or ""

    def stream_chat(self, messages: list[dict], temperature: float = 0.7) -> Generator[str, None, None]:
        """Stream chat response.

        Args:
            messages: Message list
            temperature: Temperature for generation

        Yields:
            Response chunks
        """
        logger.info(f"[LLM] stream_chat请求, provider={self.provider}")

        if self.provider == "ollama":
            logger.info(f"[LLM] 使用Ollama流式请求")
            response = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": messages, "stream": True, "options": {"temperature": temperature}},
                stream=True,
                timeout=120,
            )
            # 先读完所有内容，再 yield（解决生成器在HTTP请求中的问题）
            chunks = []
            for line in response.iter_lines():
                if line:
                    data = line.decode("utf-8")
                    import json
                    try:
                        if data.startswith("data: "):
                            chunk = json.loads(data[6:])
                        else:
                            chunk = json.loads(data)
                        if "message" in chunk:
                            msg = chunk["message"]
                            content = msg.get("content", "")
                            if content:
                                chunks.append(content)
                    except:
                        pass
            # 现在作为生成器返回
            logger.info(f"[LLM] Ollama流式响应完成, chunks_count={len(chunks)}")
            for c in chunks:
                yield c
            return

        if self._use_custom_openai_rest():
            logger.info(f"[LLM] 使用OpenAI兼容REST流式请求")
            for chunk in self._openai_rest_chat(messages, stream=True, temperature=temperature):
                yield chunk
            return

        logger.info(f"[LLM] 使用OpenAI流式请求")
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            stream=True,
            temperature=temperature,
        )

        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _use_custom_openai_rest(self) -> bool:
        return self.provider != "ollama" and bool(self.api_header_name) and self.api_header_name.lower() != "authorization"

    def _openai_rest_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_header_name:
            value = self.api_key
            if self.api_header_prefix:
                value = f"{self.api_header_prefix}{self.api_key}"
            headers[self.api_header_name] = value
        else:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _openai_rest_chat(
        self,
        messages: list[dict],
        stream: bool = False,
        temperature: float = 0.7,
        tools: Optional[list[dict]] = None,
    ) -> str | dict[str, Any] | Generator[str, None, None]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        response = requests.post(
            f"{self.base_url.rstrip('/')}/chat/completions",
            headers=self._openai_rest_headers(),
            json=payload,
            stream=stream,
            timeout=self.timeout,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            body_preview = response.text[:1000]
            logger.error(
                "[LLM] OpenAI-compatible REST request failed: status=%s, body=%s",
                response.status_code,
                body_preview,
            )
            raise exc

        if stream:
            return self._stream_openai_rest(response)

        data = response.json()
        message = (data.get("choices") or [{}])[0].get("message") or {}
        if tools is not None:
            return {
                "content": message.get("content"),
                "tool_calls": message.get("tool_calls") or [],
            }
        return message.get("content") or ""

    def _stream_openai_rest(self, response) -> Generator[str, None, None]:
        for raw_line in response.iter_lines(decode_unicode=False):
            if not raw_line:
                continue
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = str(raw_line)
            if not line:
                continue
            if line.startswith("data: "):
                line = line[6:]
            if line == "[DONE]":
                break
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            choices = chunk.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            content = delta.get("content")
            if content:
                yield content


class QwenClient(LLMClient):
    """Qwen LLM client."""

    def __init__(self):
        """Initialize Qwen client."""
        super().__init__(
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            model="qwen-plus",
        )
