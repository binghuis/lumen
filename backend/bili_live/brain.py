# -*- coding: utf-8 -*-
"""大脑:把弹幕喂给大模型,生成一句口语化回复。

火山豆包(Ark)走 OpenAI 兼容接口。环境变量:
  ARK_API_KEY   方舟 API Key
  ARK_BASE_URL  方舟兼容 endpoint,默认 https://ark.cn-beijing.volces.com/api/v3
  ARK_MODEL     推理接入点 ID(在方舟控制台拿)
  BRAIN_HISTORY_TURNS  短期记忆轮数,默认 6;设 0 退回纯单轮无记忆

SYSTEM_PROMPT 是人格占位,后续在这里打磨角色。
短期记忆见 _history:全场最近几轮「现场情况→我的回应」,给回应连续性(接梗、跟话头、不复读)。
"""
import os
from collections import deque
from collections.abc import AsyncIterator

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

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

# 短期记忆:最近若干轮 (现场情况, 我的回应)。直播是「主播一个意识流」,记的是全场最近发生过
# 什么 + 我怎么接的,不按观众分线(分人是长期 per-UID 记忆的事)。窗口大小每轮按 env 现读,
# 便于以后 web 配置热改;退化到 0 即清空、回到纯单轮。
_history: deque[tuple[str, str]] = deque()


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


_SENT_ENDS = frozenset('。!?！?…\n')


def _first_sentence_end(s: str) -> int | None:
    for i, ch in enumerate(s):
        if ch in _SENT_ENDS:
            return i
    return None


def _build_messages(situation: str) -> list[ChatCompletionMessageParam]:
    messages: list[ChatCompletionMessageParam] = [{'role': 'system', 'content': SYSTEM_PROMPT}]
    for past_sit, past_reply in _history:
        messages.append({'role': 'user', 'content': past_sit})
        messages.append({'role': 'assistant', 'content': past_reply})
    messages.append({'role': 'user', 'content': situation})
    return messages


def _remember(situation: str, text: str) -> None:
    maxlen = int(os.environ.get('BRAIN_HISTORY_TURNS', '6'))
    if maxlen > 0 and text:
        _history.append((situation, text))
        while len(_history) > maxlen:
            _history.popleft()
    elif maxlen <= 0 and _history:
        _history.clear()


async def reply_stream(situation: str) -> AsyncIterator[str]:
    """流式:豆包 stream=True,按句边出边 yield——让 TTS 边出边播,首句先开口(提速核心)。

    带最近几轮短期记忆(`BRAIN_HISTORY_TURNS`,默认 6、0 关闭),不分观众(分人是长期记忆的事)。
    整段成功后才记入历史:出错的这轮不污染记忆。
    """
    stream = await _get_client().chat.completions.create(
        model=os.environ['ARK_MODEL'],
        messages=_build_messages(situation),
        max_tokens=120,
        temperature=0.8,
        stream=True,
    )
    full = ''
    buf = ''
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if not delta:
            continue
        full += delta
        buf += delta
        while (idx := _first_sentence_end(buf)) is not None:
            sentence = buf[:idx + 1].strip()
            buf = buf[idx + 1:]
            if sentence:
                yield sentence
    tail = buf.strip()
    if tail:
        yield tail
    _remember(situation, full.strip())


async def reply(situation: str) -> str:
    """非流式入口:把流式结果收集成整段。供测试/不需要边播的场景。"""
    return ''.join([s async for s in reply_stream(situation)])
