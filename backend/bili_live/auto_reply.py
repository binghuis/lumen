# -*- coding: utf-8 -*-
"""mode A 闭环:读到弹幕 → 触发判断 → 生成回复 → 自动发回一条弹幕。

接收用 web 模式(blivedm),发送用 sender.BiliSender。
当前 make_reply 是占位逻辑(echo),后续把它替换成调用豆包 LLM 即可。

环境变量:
  BILI_ROOM_ID         直播间号(URL 末尾)
  BILI_SESSDATA        登录态(收+发都用),发弹幕必填
  BILI_BILI_JCT        bili_jct(CSRF),发弹幕必填
  REPLY_MIN_INTERVAL   两条回复最短间隔秒,默认 5

注意:这是测试/辅助形态(AI 当弹幕机器人)。VTuber 产品的真回应是 TTS 语音+字幕,不是发弹幕。
自动发弹幕有被限流/封号风险,请用测试账号、低频率、在自己或测试房间跑。
"""
import asyncio
import os

import aiohttp

import receiver
import sender as sender_mod
from receiver import LiveEvent


def load_bili_cookies_from_browser() -> tuple[str, str]:
    """从本地已登录的浏览器读取 B站 cookie。只在你的机器上执行,不经过网络/对话。"""
    import browser_cookie3 as bc3
    jar = {c.name: c.value for c in bc3.load(domain_name='bilibili.com')}
    sessdata, bili_jct = jar.get('SESSDATA'), jar.get('bili_jct')
    if not sessdata or not bili_jct:
        raise RuntimeError('浏览器里没找到 B站 登录 cookie,请先在浏览器登录 bilibili.com')
    return sessdata, bili_jct


def make_reply(event: LiveEvent) -> str | None:
    """回复生成的唯一钩子。现在是占位 echo,之后换成调用豆包 LLM。"""
    if event.type != 'danmaku':
        return None
    text = event.text.strip()
    if not text:
        return None
    return f'收到:{text}'


async def main() -> None:
    room_id = int(os.environ['BILI_ROOM_ID'])
    # 登录态:env 优先;没有就自动从本地浏览器读(在你机器上,不经过对话)
    sessdata = os.environ.get('BILI_SESSDATA')
    bili_jct = os.environ.get('BILI_BILI_JCT')
    if not (sessdata and bili_jct):
        print('[auto_reply] 环境变量无登录态,尝试从本地浏览器读取 ...', flush=True)
        sessdata, bili_jct = load_bili_cookies_from_browser()
        print('[auto_reply] 已从浏览器读到登录态(值不打印)', flush=True)
    interval = float(os.environ.get('REPLY_MIN_INTERVAL', '5'))
    os.environ['LUMEN_BILI_MODE'] = 'web'          # 接收走 web 模式
    os.environ['BILI_SESSDATA'] = sessdata         # 接收端也带登录态,弹幕用户名不打码

    async with aiohttp.ClientSession() as s:
        real_room_id = await sender_mod.resolve_real_room_id(s, room_id)
    snd = sender_mod.BiliSender(real_room_id, sessdata, bili_jct, min_interval=interval)
    await snd.setup()
    print(f'[auto_reply] 房间 {room_id}(真实 {real_room_id}),每 {interval}s 最多回一条', flush=True)

    def on_event(ev: LiveEvent) -> None:
        if ev.type != 'danmaku':
            return
        if snd.is_recent_self(ev.text):            # 跳过自己刚发的,防自激
            return
        if not snd.can_send():                     # 节流
            print(f'[throttle] 冷却中,跳过: {ev.text}', flush=True)
            return
        reply = make_reply(ev)
        if not reply:
            return
        print(f'[reply] {ev.uname}: {ev.text}  ->  {reply}', flush=True)
        snd.note_send(reply)                       # 同步登记(节流+自过滤),再异步发
        asyncio.create_task(snd.send(reply))

    try:
        await receiver.run_web(on_event=on_event)
    finally:
        await snd.close()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n已停止', flush=True)
