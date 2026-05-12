"""Dashscope MultiModalConversation wrapper.

Encapsulates Phase 2 (sync OCR with ``ocr_model``) and Phase 3 (async VLM with
caller-supplied ``model``) calls. Owns: dashscope import, base64 encoding,
retry loop, key rotation, health recording. Caller owns: prompt construction
and response parsing (so chart/table/figure logic stays in ``page_processor``).
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any, List, Mapping, Optional

from .api_key_pool import APIKeyHealthMonitor
from .error_log import log_api_error
from .retry import RetryConfig, calculate_retry_delay, should_retry


def safe_get_text_from_response(response: Any) -> str:
    """Extract text content from a dashscope response, tolerating shape drift."""
    try:
        if not hasattr(response, "output"):
            return ""
        if not hasattr(response.output, "choices") or len(response.output.choices) == 0:
            return ""
        content = response.output.choices[0].message.content

        if isinstance(content, list):
            if len(content) == 0:
                return ""
            first_item = content[0]
            if isinstance(first_item, dict):
                return first_item.get("text", "")
            if isinstance(first_item, str):
                return first_item
            return str(first_item)

        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            return content.get("text", str(content))
        return str(content)
    except Exception:
        return ""


def _image_to_base64_png(image: Any) -> str:
    buffered = BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()


@dataclass
class CallResult:
    """Outcome of a VLM call after the internal retry loop terminates."""

    success: bool
    response: Any = None
    error: Optional[str] = None


_OCR_PROMPT = """请提取这张图片中的所有文字内容。
只需要纯文本，保持原有的段落结构和换行。
不要添加任何解释或格式化。"""


class QwenClient:
    """Dashscope client with retry + key rotation."""

    def __init__(
        self,
        key_pool: Optional[APIKeyHealthMonitor],
        retry_config: RetryConfig,
        ocr_model: str,
    ):
        self.key_pool = key_pool
        self.retry = retry_config
        self.ocr_model = ocr_model

    def simple_ocr_sync(
        self,
        image: Any,
        *,
        context: Optional[Mapping[str, Any]] = None,
    ) -> str:
        """Phase 2 OCR: extract raw text from a single page image.

        Returns ``""`` after exhausting retries. Designed to run inside
        ``loop.run_in_executor``. ``context`` (e.g. ``{"pdf_name": ..., "page": ...}``)
        is propagated to the JSONL error log.
        """
        from dashscope import MultiModalConversation
        import dashscope

        img_base64 = _image_to_base64_png(image)
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{img_base64}"},
                    {"text": _OCR_PROMPT},
                ],
            }
        ]

        last_error: Optional[Exception] = None

        for attempt in range(self.retry.max_retries + 1):
            api_key = self._sync_pick_key()
            call_start = time.time()

            try:
                dashscope.api_key = api_key
                response = MultiModalConversation.call(
                    model=self.ocr_model,
                    messages=messages,
                )
                latency = time.time() - call_start

                if response.status_code == 200:
                    if self.key_pool:
                        self.key_pool.record_success_sync(api_key, latency)
                    return safe_get_text_from_response(response)

                error_msg = f"{response.code} - {response.message}"
                last_error = Exception(error_msg)
                if self.key_pool:
                    self.key_pool.record_failure_sync(api_key)

                log_api_error(
                    phase="ocr",
                    attempt=attempt + 1,
                    max_attempts=self.retry.max_retries + 1,
                    model=self.ocr_model,
                    api_key=api_key,
                    context=context,
                    status_code=response.status_code,
                    dashscope_code=response.code,
                    request_id=getattr(response, "request_id", None),
                    latency_s=latency,
                    message=response.message,
                )

                if response.status_code in self.retry.retry_on_status_codes:
                    if attempt < self.retry.max_retries:
                        delay = calculate_retry_delay(attempt, self.retry)
                        print(
                            f"      🔄 OCR重试 ({attempt + 1}/{self.retry.max_retries}): "
                            f"状态码 {response.status_code}, 等待 {delay:.1f}s"
                        )
                        time.sleep(delay)
                        continue
                return ""

            except Exception as e:
                last_error = e
                latency = time.time() - call_start
                if self.key_pool:
                    self.key_pool.record_failure_sync(api_key)

                log_api_error(
                    phase="ocr",
                    attempt=attempt + 1,
                    max_attempts=self.retry.max_retries + 1,
                    model=self.ocr_model,
                    api_key=api_key,
                    context=context,
                    latency_s=latency,
                    exception=e,
                    message=str(e),
                )

                if should_retry(e, self.retry) and attempt < self.retry.max_retries:
                    delay = calculate_retry_delay(attempt, self.retry)
                    print(
                        f"      🔄 OCR重试 ({attempt + 1}/{self.retry.max_retries}): "
                        f"{type(e).__name__}, 等待 {delay:.1f}s"
                    )
                    time.sleep(delay)
                    continue

                print(f"      ⚠️ OCR提取失败: {e}")
                return ""

        print(f"      ❌ OCR提取失败(重试{self.retry.max_retries}次后): {last_error}")
        return ""

    async def call_vlm(
        self,
        image: Any,
        prompt: str,
        *,
        model: str,
        max_tokens: int = 16384,
        log_prefix: str = "",
        context: Optional[Mapping[str, Any]] = None,
    ) -> CallResult:
        """Phase 3 VLM: send image+prompt, return ``CallResult``.

        Retries on transient errors per ``retry_config``. Treats
        ``DataInspectionFailed`` as fatal (non-retriable) per legacy behavior.
        ``context`` (e.g. ``{"pdf_name": ..., "page": ...}``) is propagated to
        the JSONL error log.
        """
        from dashscope import MultiModalConversation
        import dashscope

        img_base64 = _image_to_base64_png(image)
        messages = [
            {
                "role": "user",
                "content": [
                    {"image": f"data:image/png;base64,{img_base64}"},
                    {"text": prompt},
                ],
            }
        ]

        last_error: Optional[Exception] = None
        response = None

        for attempt in range(self.retry.max_retries + 1):
            api_key = await self._async_pick_key()
            dashscope.api_key = api_key
            call_start = time.time()

            try:
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    lambda: MultiModalConversation.call(
                        model=model,
                        messages=messages,
                        max_tokens=max_tokens,
                    ),
                )
                latency = time.time() - call_start

                if response.status_code == 200:
                    if self.key_pool:
                        await self.key_pool.record_success(api_key, latency)
                    return CallResult(success=True, response=response)

                error_msg = f"{response.code} - {response.message}"
                last_error = Exception(error_msg)
                if self.key_pool:
                    await self.key_pool.record_failure(api_key)

                log_api_error(
                    phase="vlm",
                    attempt=attempt + 1,
                    max_attempts=self.retry.max_retries + 1,
                    model=model,
                    api_key=api_key,
                    context=context,
                    status_code=response.status_code,
                    dashscope_code=response.code,
                    request_id=getattr(response, "request_id", None),
                    latency_s=latency,
                    message=response.message,
                )

                if "DataInspectionFailed" not in error_msg and attempt < self.retry.max_retries:
                    if (
                        response.status_code in self.retry.retry_on_status_codes
                        or response.status_code >= 500
                    ):
                        delay = calculate_retry_delay(attempt, self.retry)
                        print(
                            f"      🔄 {log_prefix}重试 ({attempt + 1}/{self.retry.max_retries}): "
                            f"状态码 {response.status_code}, 等待 {delay:.1f}s"
                        )
                        await asyncio.sleep(delay)
                        continue

                return CallResult(success=False, error=error_msg)

            except Exception as e:
                last_error = e
                latency = time.time() - call_start
                if self.key_pool:
                    await self.key_pool.record_failure(api_key)

                log_api_error(
                    phase="vlm",
                    attempt=attempt + 1,
                    max_attempts=self.retry.max_retries + 1,
                    model=model,
                    api_key=api_key,
                    context=context,
                    latency_s=latency,
                    exception=e,
                    message=str(e),
                )

                if should_retry(e, self.retry) and attempt < self.retry.max_retries:
                    delay = calculate_retry_delay(attempt, self.retry)
                    print(
                        f"      🔄 {log_prefix}重试 ({attempt + 1}/{self.retry.max_retries}): "
                        f"{type(e).__name__}, 等待 {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                    continue

                return CallResult(success=False, error=str(e))

        return CallResult(
            success=False,
            error=str(last_error) if last_error else "Unknown error after retries",
        )

    async def _async_pick_key(self) -> Optional[str]:
        if self.key_pool:
            return await self.key_pool.get_healthy_key()
        import os
        return os.environ.get("DASHSCOPE_API_KEY")

    def _sync_pick_key(self) -> Optional[str]:
        if self.key_pool:
            return self.key_pool.get_healthy_key_sync()
        import os
        return os.environ.get("DASHSCOPE_API_KEY")
