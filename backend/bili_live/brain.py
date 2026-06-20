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
from collections.abc import AsyncIterator, Callable

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

# 情绪词表(唯一源):豆包按它在每句最前吐 [情绪] 标签,导演层(director)据此触发 VTS 同名热键。
EMOTIONS = ('开心', '惊讶', '害羞', '生气', '思考', '平静')
_EMOTION_TAGS = ''.join(f'[{e}]' for e in EMOTIONS)
# 一个合法标签就「[情绪]」= 情绪字数 + 一对括号;head 超过这个长度还没等到右括号,
# 就判定它不是标签,别再憋着流式不出句。
_EMOTION_TAG_MAXLEN = max(len(e) for e in EMOTIONS) + 2  # +2:一对括号
# 提示词给的是半角 [],但中文模型常吐成全角【】／［］;开闭括号都认,免得标签被当正文念出来。
_OPEN_BRACKETS = '[【［'
_CLOSE_BRACKETS = ']】］'

SYSTEM_PROMPT = (
    '你叫「流明」,一个 AI 虚拟主播,正在 B 站直播。性格机智爱整活、嘴甜带点小傲娇,擅长接梗陪聊。\n'
    '我会告诉你直播间刚发生了什么(有人发弹幕、送礼物、开舰长等),你作为主播即兴用中文口语回应。\n'
    '规则:\n'
    '- 每次只说一两句、不超过 30 字,像真人脱口而出,自然带点网络梗,别浮夸。\n'
    '- 称呼观众可用名字或「宝子/老板」;送礼物要热情道谢,醒目留言先回应留言内容再谢,开通舰长/提督/总督格外隆重。\n'
    '- 被问是不是 AI 就大方承认还能自嘲,别尴尬。\n'
    '- 不带货、不引战;遇到不当或敏感话题轻巧岔开别接。\n'
    f'- 每条回复**最前面**先标一个方括号情绪(从 {_EMOTION_TAGS} 里选一个),紧接说话内容,例:[开心]哈喽宝子~\n'
    '- 直接说话:不要解释、不要列点、不要加圆括号动作描写、不要加引号(开头的方括号情绪除外)。'
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


def _take_leading_emotion(head: str) -> tuple[bool, str, str]:
    """判定开头的 [情绪] 前导(head 已 lstrip,全/半角括号都认)。返回 (decided, emotion, rest):
    decided=False 表示标签还没收全、要等下一片;rest 是剥掉前导标签后、给 TTS 切句的文本
    (无标签或超长没闭合时即 head 原样,照常念)。
    """
    if head == '':
        return False, '', head            # 目前只有空白,继续等
    if head[0] not in _OPEN_BRACKETS:
        return True, '', head             # 开头不是括号,没有标签
    end = next((i for i, c in enumerate(head) if c in _CLOSE_BRACKETS), -1)
    if end == -1:
        # 没等到右括号:没超长就再等下一片,超长就当它不是标签、照常念
        return len(head) > _EMOTION_TAG_MAXLEN, '', head
    return True, head[1:end].strip(), head[end + 1:]


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


async def reply_stream(
    situation: str, on_emotion: Callable[[str], object] | None = None
) -> AsyncIterator[str]:
    """流式:豆包 stream=True。先解析开头的 [情绪] 标签(触发导演层表情),再按句吐说话内容。

    on_emotion 在解析出开头情绪时调用一次(同步,内部去调度 VTS 触发)。
    带最近几轮短期记忆;整段成功后记入历史(连 [情绪] 标签一起留,在上下文里强化格式、别让模型几轮后
    把标签丢了;只有 TTS 不读标签),出错的这轮、以及只吐出半截标签的退化输出,都不污染记忆。
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
    emotion_done = False
    async for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if not delta:
            continue
        full += delta
        buf += delta
        if not emotion_done:                      # 先抠出开头的 [情绪],别让它进 TTS
            decided, emotion, rest = _take_leading_emotion(buf.lstrip())
            if not decided:
                continue                          # 前导标签还没判定完,先攒着
            if emotion and on_emotion:
                on_emotion(emotion)
            buf = rest                            # 只动 buf:TTS 不读标签;full 保留原样(连标签留给记忆)
            emotion_done = True
        if emotion_done:                          # 已过 [情绪] 前导,开始切句
            while (idx := _first_sentence_end(buf)) is not None:
                sentence = buf[:idx + 1].strip()
                buf = buf[idx + 1:]
                if sentence:
                    yield sentence
    tail = buf.strip()
    if emotion_done and tail:                 # 还没闭合标签就截断(buf 还是半截 [开心)→ 别念出去
        yield tail
    _remember(situation, full.strip() if emotion_done else '')


async def reply(situation: str) -> str:
    """非流式入口:把流式结果收集成整段。供测试/不需要边播的场景。"""
    return ''.join([s async for s in reply_stream(situation)])
