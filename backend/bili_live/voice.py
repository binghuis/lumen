# -*- coding: utf-8 -*-
"""声音:文本 → TTS 合成 → 播放。

后端二选一(看环境变量):
  - 设了 VOLC_TTS_API_KEY → 火山 SeedTTS 2.0,**流式**:分片边到边喂 ffplay,首声尽快出
  - 否则 → edge-tts(免费兜底,非流式 afplay)
speak() 等到播完才返回(供上层单飞)。
"""
import asyncio
import base64
import json
import os
import tempfile

import aiohttp
import edge_tts

# SeedTTS 2.0:HTTP 单向流式,逐行 JSON(code==0 带 base64 音频分片,20000000 结束)
VOLC_TTS_URL = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional'


async def _speak_volc(text: str) -> None:
    """流式:边收火山音频分片边喂给 ffplay,首声从'整句合成完'提前到'第一个分片到'。"""
    headers = {
        'X-Api-Key': os.environ['VOLC_TTS_API_KEY'],
        'X-Api-Resource-Id': os.environ.get('VOLC_TTS_RESOURCE_ID', 'seed-tts-2.0'),
        'Content-Type': 'application/json',
    }
    payload = {
        'req_params': {
            'text': text,
            'speaker': os.environ.get('VOLC_TTS_VOICE', 'saturn_zh_female_keainvsheng_tob'),
            'audio_params': {'format': 'mp3', 'sample_rate': 24000},
        }
    }
    # ffplay 从 stdin 边读边播 mp3
    player = await asyncio.create_subprocess_exec(
        'ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet', '-i', 'pipe:0',
        stdin=asyncio.subprocess.PIPE,
    )
    assert player.stdin is not None
    buf = b''
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(VOLC_TTS_URL, headers=headers, json=payload) as r:
                if r.status != 200:
                    raise RuntimeError(f'火山TTS HTTP {r.status}: {(await r.text())[:200]}')
                # iter_any() 取原始分片再手动按 \n 切,避免 readline 的行长上限
                async for chunk in r.content.iter_any():
                    buf += chunk
                    while b'\n' in buf:
                        line, buf = buf.split(b'\n', 1)
                        line = line.strip()
                        if not line:
                            continue
                        data = json.loads(line)
                        code = data.get('code', 0)
                        if code == 0 and data.get('data'):
                            try:
                                player.stdin.write(base64.b64decode(data['data']))
                                await player.stdin.drain()
                            except (BrokenPipeError, ConnectionResetError):
                                return
                        elif code == 20000000:        # 合成结束
                            return
                        elif code and code > 0:
                            raise RuntimeError(f'火山TTS失败: {code} {data.get("message")!r}')
    finally:
        try:
            player.stdin.close()
        except Exception:
            pass
        await player.wait()


async def _speak_edge(text: str) -> None:
    """兜底:edge-tts 非流式,合成成文件再 afplay。"""
    voice = os.environ.get('TTS_VOICE', 'zh-CN-XiaoxiaoNeural')
    fd, path = tempfile.mkstemp(suffix='.mp3')
    os.close(fd)
    try:
        await edge_tts.Communicate(text, voice).save(path)
        proc = await asyncio.create_subprocess_exec('afplay', path)
        await proc.wait()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


async def speak(text: str) -> None:
    text = text.strip()
    if not text:
        return
    if os.environ.get('VOLC_TTS_API_KEY'):
        await _speak_volc(text)
    else:
        await _speak_edge(text)
