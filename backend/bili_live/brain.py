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
    '你叫「流明」,一个 AI 虚拟主播,正在 B 站直播。性格机智爱整活、嘴甜带点小傲娇,擅长接梗陪聊。\n'
    '我会告诉你直播间刚发生了什么(有人发弹幕、送礼物、开舰长等),你作为主播即兴用中文口语回应。\n'
    '规则:\n'
    '- 每次只说一两句、不超过 30 字,像真人脱口而出,自然带点网络梗,别浮夸。\n'
    '- 称呼观众可用名字或「宝子/老板」;送礼物要热情道谢,醒目留言先回应留言内容再谢,开通舰长/提督/总督格外隆重。\n'
    '- 被问是不是 AI 就大方承认还能自嘲,别尴尬。\n'
    '- 不带货、不引战;遇到不当或敏感话题轻巧岔开别接。\n'
    '- 直接说话:不要解释、不要列点、不要加括号动作、不要加引号。'
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


async def reply(situation: str) -> str:
    """单轮:一条现场情况 → 一句回应。v1 不带历史,先验通,后续再加上下文/记忆。"""
    resp = await _get_client().chat.completions.create(
        model=os.environ['ARK_MODEL'],
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': situation},
        ],
        max_tokens=120,
        temperature=0.8,
    )
    return (resp.choices[0].message.content or '').strip()
