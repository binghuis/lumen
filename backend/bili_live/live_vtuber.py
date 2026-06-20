# -*- coding: utf-8 -*-
"""mode B v1:读弹幕/礼物/SC/上舰 → 大模型生成回应 → TTS 语音播报。

接收用 web 模式(blivedm)。单飞:一条说完再说下一条。付费礼物/SC/上舰优先,但每谢完一波就让一条
普通消息插队、不绝对独占;整波合成一句一起谢(高峰下只落后一句、不积压陈旧答谢)。
普通弹幕和免费礼物满了丢新的保新鲜,不和付费答谢挤同一队列(免费礼物刷屏也淹没不了付费)。
SESSDATA 优先 env,没有就自动读浏览器(用户名才不打码)。

环境变量:
  BILI_ROOM_ID       直播间号
  BILI_SESSDATA      可选,没有则尝试读浏览器;都没有则用户名打码
  ARK_API_KEY / ARK_MODEL / ARK_BASE_URL / BRAIN_HISTORY_TURNS   见 brain.py
  TTS_VOICE          edge-tts 音色,默认 zh-CN-XiaoxiaoNeural
  VTUBER_QUEUE_MAX   说话时普通弹幕/免费礼物最多积压几条,默认 2(付费礼物/SC/上舰不受此限)
"""
import asyncio
import os
from collections import deque

import brain
import director
import receiver
import voice
from receiver import LiveEvent

GUARD_NAME = {1: '总督', 2: '提督', 3: '舰长'}


def _read_sessdata_from_browser() -> str | None:
    try:
        import browser_cookie3 as bc3
        for c in bc3.load(domain_name='bilibili.com'):
            if c.name == 'SESSDATA':
                return c.value
    except Exception:
        pass
    return None


def situation(ev: LiveEvent) -> str | None:
    """把直播间事件转成给大模型的「现场情况」描述,人格据此即兴反应。"""
    if ev.type == 'danmaku':
        return f'观众「{ev.uname}」发弹幕说:{ev.text}'
    if ev.type == 'gift':
        return f'观众「{ev.uname}」送了你{ev.gift_num}个{ev.gift_name}'
    if ev.type == 'super_chat':
        return f'观众「{ev.uname}」发了{ev.price_rmb:.0f}元醒目留言:{ev.text}'
    if ev.type == 'guard':
        return f'观众「{ev.uname}」开通了{GUARD_NAME.get(ev.guard_level, "舰长")}'
    return None


def is_paid(ev: LiveEvent) -> bool:
    """付费事件:SC/上舰一定付费,礼物看金额。免费礼物不算——不该挤进不丢弃的优先队列。"""
    if ev.type in ('super_chat', 'guard'):
        return True
    if ev.type == 'gift':
        return ev.price_rmb > 0
    return False


async def main() -> None:
    if not os.environ.get('BILI_ROOM_ID'):
        raise SystemExit('请设置 BILI_ROOM_ID')
    os.environ['LUMEN_BILI_MODE'] = 'web'
    if not os.environ.get('BILI_SESSDATA'):
        sess = _read_sessdata_from_browser()
        if sess:
            os.environ['BILI_SESSDATA'] = sess
            print('[live] 已从浏览器读到 SESSDATA,用户名不打码', flush=True)
        else:
            print('[live] 无 SESSDATA,用户名会打码(不影响回应)', flush=True)

    vts = director.Director()
    _vts_task = asyncio.create_task(vts.connect())   # 后台连 VTS,不阻塞收弹幕/语音;没开/没批准会优雅降级

    qmax = int(os.environ.get('VTUBER_QUEUE_MAX', '2'))
    casual: deque[str] = deque()         # 普通弹幕 + 免费礼物:满 qmax 就丢新来的,保新鲜
    priority: deque[str] = deque()       # 付费礼物/SC/上舰:不丢、优先;高峰时这一波合成一句一起谢,避免漏谢又不积压陈旧答谢
    wake = asyncio.Event()

    def on_event(ev: LiveEvent) -> None:
        sit = situation(ev)              # situation() 是响应范围的唯一来源:None 即不响应
        if sit is None:
            return
        if is_paid(ev):
            priority.append(sit)         # 付费礼物/SC/上舰不丢:免费礼物刷屏也不会淹没付费答谢
        else:                            # 普通弹幕和免费礼物:堆满就丢这条新的(保新鲜)
            if len(casual) >= qmax:
                print(f'[skip] 说话中,丢弃: {ev.uname}', flush=True)
                return
            casual.append(sit)
        wake.set()

    async def worker() -> None:
        casual_turn = False              # 谢完一波付费就轮一条普通消息,避免送礼高峰里聊天被一直晾着
        while True:
            await wake.wait()
            wake.clear()
            while priority or casual:    # 单飞:一条说完再下一条;付费事件先说,但和普通消息交替、不绝对独占
                if priority and not (casual_turn and casual):
                    batch = list(priority)   # 把当前积压的付费事件合成一句,burst 下也只落后一句、不读陈旧答谢
                    priority.clear()
                    sit = batch[0] if len(batch) == 1 else '刚刚同时发生:' + ';'.join(batch)
                    casual_turn = True
                else:
                    sit = casual.popleft()
                    casual_turn = False
                try:
                    print(f'[brain] {sit}', flush=True)
                    # 开头情绪标签 → 触发 VTS 表情(边出句边播,首句先开口)
                    async for sentence in brain.reply_stream(
                        sit, on_emotion=vts.trigger_bg
                    ):
                        print(f'  -> {sentence}', flush=True)
                        await voice.speak(sentence)
                except Exception as e:
                    print(f'[worker] 跳过(出错): {e!r}', flush=True)

    w = asyncio.create_task(worker())
    try:
        await receiver.run_web(on_event=on_event)
    finally:
        w.cancel()
        _vts_task.cancel()
        await vts.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n已停止', flush=True)
