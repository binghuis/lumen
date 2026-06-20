# -*- coding: utf-8 -*-
"""声音:文本 → TTS 合成 → 本机扬声器播放(macOS afplay)。

后端二选一(看环境变量):
  - 设了 VOLC_TTS_API_KEY → 火山 SeedTTS 2.0(v3 单向流式 HTTP)
  - 否则 → edge-tts(免费兜底)
非流式播放:分片收完拼成 mp3 再播。speak() 等到播完才返回(供上层单飞)。
"""
import asyncio
import base64
import json
import os
import tempfile

import aiohttp
import edge_tts

# SeedTTS 2.0:HTTP 单向流式,逐行 JSON(code==0 带 base64 音频,20000000 结束)
VOLC_TTS_URL = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional'


async def _synth_volc(text: str, path: str) -> None:
    api_key = os.environ['VOLC_TTS_API_KEY']
    voice = os.environ.get('VOLC_TTS_VOICE', 'saturn_zh_female_keainvsheng_tob')
    headers = {
        'X-Api-Key': api_key,
        'X-Api-Resource-Id': os.environ.get('VOLC_TTS_RESOURCE_ID', 'seed-tts-2.0'),
        'Content-Type': 'application/json',
    }
    payload = {
        'req_params': {
            'text': text,
            'speaker': voice,
            'audio_params': {'format': 'mp3', 'sample_rate': 24000},
        }
    }
    audio = bytearray()
    # aiohttp 默认不读环境代理,境内请求不受 SOCKS 代理影响;设总超时,卡住时放弃这句别让主播长时间静音
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.post(VOLC_TTS_URL, headers=headers, json=payload) as r:
            if r.status != 200:
                raise RuntimeError(f'火山TTS HTTP {r.status}: {(await r.text())[:300]}')
            raw = await r.text()
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        data = json.loads(line)
        code = data.get('code', 0)
        if code == 0 and data.get('data'):
            audio.extend(base64.b64decode(data['data']))
        elif code == 20000000:          # 合成结束
            break
        elif code and code > 0:
            raise RuntimeError(f'火山TTS失败: {code} {data.get("message")!r}')
    if not audio:
        raise RuntimeError(f'火山TTS无音频返回: {raw[:300]}')
    with open(path, 'wb') as f:
        f.write(bytes(audio))


async def _synth_edge(text: str, path: str) -> None:
    voice = os.environ.get('TTS_VOICE', 'zh-CN-XiaoxiaoNeural')
    await edge_tts.Communicate(text, voice).save(path)


async def speak(text: str) -> None:
    text = text.strip()
    if not text:
        return
    fd, path = tempfile.mkstemp(suffix='.mp3')
    os.close(fd)
    try:
        if os.environ.get('VOLC_TTS_API_KEY'):
            await _synth_volc(text, path)
        else:
            await _synth_edge(text, path)
        proc = await asyncio.create_subprocess_exec('afplay', path)
        await proc.wait()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
