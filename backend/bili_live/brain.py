# -*- coding: utf-8 -*-
"""大脑:把弹幕喂给大模型,生成一句口语化回复。

火山豆包(Ark)走 OpenAI 兼容接口。环境变量:
  ARK_API_KEY   方舟 API Key
  ARK_BASE_URL  方舟兼容 endpoint,默认 https://ark.cn-beijing.volces.com/api/v3
  ARK_MODEL     推理接入点 ID(在方舟控制台拿)

SYSTEM_PROMPT 是人格占位,后续在这里打磨角色。
"""
import os

import httpx
from openai import AsyncOpenAI

SYSTEM_PROMPT = (
    '你是一名 B 站虚拟主播,正在直播。观众发来弹幕,你要用活泼、简短、口语化的中文回应,'
    '像真人主播即兴接话。每次只说一两句,不超过 30 个字,不要解释、不要列点、不要用括号动作。'
)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=os.environ['ARK_API_KEY'],
            base_url=os.environ.get('ARK_BASE_URL', 'https://ark.cn-beijing.volces.com/api/v3'),
            # 火山是境内服务,不走本机(翻墙)代理;也避免 httpx 的 SOCKS 代理依赖问题
            http_client=httpx.AsyncClient(trust_env=False),
        )
    return _client


async def reply(danmaku_text: str) -> str:
    """单轮:一条弹幕 → 一句回复。v1 不带历史,先验通,后续再加上下文/记忆。"""
    resp = await _get_client().chat.completions.create(
        model=os.environ['ARK_MODEL'],
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': danmaku_text},
        ],
        max_tokens=120,
        temperature=0.8,
    )
    return (resp.choices[0].message.content or '').strip()
