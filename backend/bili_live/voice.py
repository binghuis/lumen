# -*- coding: utf-8 -*-
"""声音:文本 → edge-tts 合成 → 本机扬声器播放。

edge-tts 免费、免 key。播放用 macOS 自带的 afplay(本模块假定 macOS)。
v1 非流式:整句合成成 mp3 再播。后续换火山 TTS + 流式 + 虚拟声卡接 OBS。
speak() 会等到这句播完才返回——上层据此做"单飞"(说话时不抢)。
"""
import asyncio
import os
import tempfile

import edge_tts


async def speak(text: str) -> None:
    text = text.strip()
    if not text:
        return
    voice = os.environ.get('TTS_VOICE', 'zh-CN-XiaoxiaoNeural')
    fd, path = tempfile.mkstemp(suffix='.mp3')
    os.close(fd)
    try:
        await edge_tts.Communicate(text, voice).save(path)
        proc = await asyncio.create_subprocess_exec('afplay', path)
        await proc.wait()                       # 等播完,实现单飞
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
