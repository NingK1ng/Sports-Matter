"""
DeepSeek API客户端

提供LLM对话能力（用于模块3-6）
"""

from typing import List, Dict, Any, Optional, AsyncGenerator, Union

import httpx
import logging

from core.config import settings
from core.external.base import BaseAPIClient


logger = logging.getLogger(__name__)

DEEPSEEK_V4_FLASH_MODEL = "deepseek-v4-flash"
LEGACY_DEEPSEEK_MODELS = {"deepseek-chat", "deepseek-reasoner"}
THINKING_DISABLED = {"type": "disabled"}


def normalize_deepseek_model(model: Optional[str]) -> str:
    """Route legacy DeepSeek v3 aliases to the current v4-flash model."""
    model_name = (model or DEEPSEEK_V4_FLASH_MODEL).strip()
    if model_name in LEGACY_DEEPSEEK_MODELS:
        return DEEPSEEK_V4_FLASH_MODEL
    return model_name


class DeepSeekClient(BaseAPIClient):
    """DeepSeek API客户端"""

    def __init__(self):
        super().__init__(
            base_url=settings.deepseek_base_url,
            timeout=120,  # 增大以容纳JSON mode响应
            enable_cache=False,  # LLM响应不缓存
        )

        self.api_key = settings.deepseek_api_key

        if not self.api_key:
            print("⚠️  DeepSeek API Key未配置，某些功能将不可用")

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: str = DEEPSEEK_V4_FLASH_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[Dict[str, str]] = None,
        fallback_model: Optional[str] = None,
        return_message: bool = False,
        disable_thinking: bool = True,
    ) -> Union[Optional[str], Dict[str, Any]]:
        """
        非流式对话

        Args:
            messages: 消息列表 [{"role": "user", "content": "..."}]
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式，如 {"type": "json_object"} 启用JSON mode
            disable_thinking: v4-flash 默认带思考；普通分类/翻译/JSON任务显式关闭思考

        Returns:
            Optional[str]: 模型回复

        Example:
            client = DeepSeekClient()
            response = await client.chat([
                {"role": "user", "content": "What is basketball?"}
            ])
        """
        if not self.api_key:
            raise ValueError("DeepSeek API Key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        models_to_try: List[str] = [model]
        if (
            response_format
            and fallback_model
            and fallback_model not in models_to_try
            and fallback_model != model
        ):
            models_to_try.append(fallback_model)

        last_content: Optional[str] = None
        last_usage: Dict[str, Any] = {}
        last_message: Optional[Dict[str, Any]] = None

        tried_models: set[str] = set()
        for current_model in models_to_try:
            normalized_model = normalize_deepseek_model(current_model)
            if normalized_model in tried_models:
                continue
            tried_models.add(normalized_model)
            payload = {
                "model": normalized_model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            }
            if disable_thinking and normalized_model == DEEPSEEK_V4_FLASH_MODEL:
                payload["thinking"] = THINKING_DISABLED
            if response_format:
                payload["response_format"] = response_format

            data = await self._request(
                "POST",
                "/chat/completions",
                headers=headers,
                json=payload,
            )
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {}) or {}
            content = message.get("content", "")
            reasoning_content = (
                message.get("reasoning_content")
                if isinstance(message.get("reasoning_content"), (str, list, dict))
                else None
            )
            if reasoning_content is None:
                reasoning_content = message.get("parsed_thoughts")

            finish_reason = choice.get("finish_reason")
            usage = data.get("usage", {})

            if content:
                logger.debug(
                    "DeepSeek response preview | model=%s finish_reason=%s usage=%s preview=%s",
                    normalized_model,
                    finish_reason,
                    usage,
                    content[:160],
                )
            else:
                logger.warning(
                    "DeepSeek returned empty content | model=%s finish_reason=%s usage=%s reasoning_preview=%s",
                    normalized_model,
                    finish_reason,
                    usage,
                    (
                        reasoning_content[:160]
                        if isinstance(reasoning_content, str)
                        else reasoning_content
                    ),
                )

            print(
                f"🤖 DeepSeek[{normalized_model}]: {usage.get('total_tokens', 0)} tokens "
                f"(prompt: {usage.get('prompt_tokens', 0)}, "
                f"completion: {usage.get('completion_tokens', 0)})"
            )

            message_payload = {
                "content": content,
                "reasoning": reasoning_content,
                "usage": usage,
                "model": normalized_model,
                "finish_reason": finish_reason,
                "raw_message": message,
            }

            if content:
                if current_model != model or normalized_model != current_model:
                    logger.info(
                        "DeepSeek fallback model succeeded | original_model=%s fallback_model=%s",
                        model,
                        normalized_model,
                    )
                if return_message:
                    return message_payload
                return content

            last_content = content
            last_usage = usage
            last_message = message_payload

        logger.debug(
            "DeepSeek exhausted model attempts | tried=%s last_usage=%s",
            models_to_try,
            last_usage,
        )
        if return_message:
            return last_message or {}
        return last_content

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: str = DEEPSEEK_V4_FLASH_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        disable_thinking: bool = True,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            max_tokens: 最大token数

        Yields:
            str: 逐个生成的文本片段

        Example:
            async for chunk in client.chat_stream(messages):
                print(chunk, end="", flush=True)
        """
        if not self.api_key:
            raise ValueError("DeepSeek API Key not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        normalized_model = normalize_deepseek_model(model)
        payload = {
            "model": normalized_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if disable_thinking and normalized_model == DEEPSEEK_V4_FLASH_MODEL:
            payload["thinking"] = THINKING_DISABLED

        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            ) as response:
                response.raise_for_status()

                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        import json

                        try:
                            data = json.loads(data_str)
                            delta = (
                                data.get("choices", [{}])[0]
                                .get("delta", {})
                                .get("content", "")
                            )
                            if delta:
                                yield delta
                        except json.JSONDecodeError:
                            continue


def get_deepseek_client() -> DeepSeekClient:
    """获取DeepSeek客户端"""
    return DeepSeekClient()
