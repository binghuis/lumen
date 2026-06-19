# -*- coding: utf-8 -*-
"""mode B v1:读弹幕 → 大模型生成回复 → TTS 语音播报。

接收用 web 模式(blivedm)。单飞:一条说完再说下一条,说话时新弹幕进有限队列,
满了就丢(保新鲜,不堆积过时回复)。

环境变量:
  BILI_ROOM_ID       直播间号
  BILI_SESSDATA      可选,填了弹幕用户名不打码
  ARK_API_KEY / ARK_MODEL / ARK_BASE_URL   见 brain.py
  TTS_VOICE          edge-tts 音色,默认 zh-CN-XiaoxiaoNeural
  VTUBER_QUEUE_MAX   说话时最多积压几条,默认 2
"""
import asyncio
import os

import brain
import receiver
import voice
from receiver import LiveEvent


async def main() -> None:
    if not os.environ.get('BILI_ROOM_ID'):
        raise SystemExit('请设置 BILI_ROOM_ID')
    os.environ['LUMEN_BILI_MODE'] = 'web'

    queue: asyncio.Queue[LiveEvent] = asyncio.Queue(maxsize=int(os.environ.get('VTUBER_QUEUE_MAX', '2')))

    def on_event(ev: LiveEvent) -> None:
        if ev.type != 'danmaku':
            return
        try:
            queue.put_nowait(ev)
        except asyncio.QueueFull:
            print(f'[skip] 说话中,丢弃: {ev.text}', flush=True)

    async def worker() -> None:
        while True:
            ev = await queue.get()
            try:
                text = await brain.reply(ev.text)
                print(f'[brain] {ev.uname}: {ev.text}  ->  {text}', flush=True)
                await voice.speak(text)
            except Exception as e:
                print(f'[worker] 跳过(出错): {e!r}', flush=True)
            finally:
                queue.task_done()

    w = asyncio.create_task(worker())
    try:
        await receiver.run_web(on_event=on_event)
    finally:
        w.cancel()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n已停止', flush=True)
