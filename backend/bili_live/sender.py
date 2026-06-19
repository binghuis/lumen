# -*- coding: utf-8 -*-
"""向 B站 直播间发送弹幕(mode A:AI 当弹幕机器人用)。

注意:发弹幕必须登录(SESSDATA + bili_jct),且 B站 有频率/长度限制和反自动化,
本模块内置节流、长度截断、和"自己刚发的"记录(供上层过滤自激)。
blivedm 只负责收,发是这里独立的 HTTP 接口。
"""
import http.cookies
import time

import aiohttp

ROOM_INIT_URL = 'https://api.live.bilibili.com/room/v1/Room/room_init'
SEND_URL = 'https://api.live.bilibili.com/msg/send'
_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36'


async def resolve_real_room_id(session: aiohttp.ClientSession, room_id: int) -> int:
    """短号 → 真实房间号。发弹幕的 roomid 要用真实房间号。无需登录。"""
    async with session.get(ROOM_INIT_URL, params={'id': room_id},
                           headers={'User-Agent': _UA}) as r:
        data = await r.json(content_type=None)
    if data.get('code') != 0:
        raise RuntimeError(f'room_init 失败: {data}')
    return data['data']['room_id']


class BiliSender:
    def __init__(self, real_room_id: int, sessdata: str, bili_jct: str,
                 min_interval: float = 5.0, max_len: int = 20):
        self.real_room_id = real_room_id
        self._sessdata = sessdata
        self._bili_jct = bili_jct
        self.min_interval = min_interval          # 两条之间最短间隔(秒),防被限流
        self.max_len = max_len                    # 截断长度,防超长被拒
        self._last_send = 0.0
        self._recent_sent: list[tuple[str, float]] = []
        self._session: aiohttp.ClientSession | None = None

    async def setup(self) -> None:
        cookies = http.cookies.SimpleCookie()
        for k, v in (('SESSDATA', self._sessdata), ('bili_jct', self._bili_jct)):
            cookies[k] = v
            cookies[k]['domain'] = '.bilibili.com'
        self._session = aiohttp.ClientSession(headers={
            'User-Agent': _UA,
            'Referer': f'https://live.bilibili.com/{self.real_room_id}',
        })
        self._session.cookie_jar.update_cookies(cookies)

    def can_send(self) -> bool:
        return (time.monotonic() - self._last_send) >= self.min_interval

    def is_recent_self(self, text: str, window: float = 30.0) -> bool:
        """这条文本是不是我们自己最近发的(收到自己弹幕时用来跳过,防自激)。"""
        now = time.monotonic()
        self._recent_sent = [(t, ts) for t, ts in self._recent_sent if now - ts < window]
        return any(t == text for t, _ in self._recent_sent)

    def note_send(self, text: str) -> None:
        """登记一次发送(同步占位):更新节流时间 + 记录文本。在调度 send 前同步调用。"""
        self._last_send = time.monotonic()
        self._recent_sent.append((text, self._last_send))

    async def send(self, msg: str) -> dict:
        if self._session is None:
            raise RuntimeError('请先 await setup()')
        msg = msg.strip()[: self.max_len]
        data = {
            'bubble': '0', 'msg': msg, 'color': '16777215', 'mode': '1',
            'fontsize': '25', 'rnd': str(int(time.time())),
            'roomid': str(self.real_room_id),
            'csrf': self._bili_jct, 'csrf_token': self._bili_jct,
        }
        async with self._session.post(SEND_URL, data=data) as r:
            res = await r.json()
        if res.get('code') == 0:
            print(f'[send] ✅ {msg}', flush=True)
        else:
            print(f'[send] ❌ code={res.get("code")} msg={res.get("message")!r} ({msg})', flush=True)
        return res

    async def close(self) -> None:
        if self._session:
            await self._session.close()
