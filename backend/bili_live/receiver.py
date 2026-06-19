# -*- coding: utf-8 -*-
"""B站直播弹幕/礼物接收器。

两种接入模式,通过环境变量 LUMEN_BILI_MODE 切换:
  - web       : 非官方 WebSocket 接口,只需 room_id(+可选 SESSDATA),申请审核前用来先跑通
  - open_live : 官方直播开放平台「互动玩法」接口,需开发者密钥 + app_id + 主播身份码

所有事件统一归一成 LiveEvent,经单一出口 dispatch() 下发。
dispatch 就是后续接「大脑/导演层」的边界:现在只打印,以后把它换成投递到对话管线。
"""
import asyncio
import http.cookies
import os
from dataclasses import dataclass, field

import aiohttp

import blivedm
import blivedm.models.open_live as open_models
import blivedm.models.web as web_models

# ---- 归一事件:接收器对外的唯一数据契约 -------------------------------------

@dataclass
class LiveEvent:
    type: str                      # danmaku | gift | super_chat | guard
    uname: str                     # 用户名(web 模式未带 SESSDATA 时会打码)
    room_id: int
    text: str = ''                 # 弹幕/SC 文本
    gift_name: str = ''
    gift_num: int = 0
    price_rmb: float = 0.0         # 付费金额(人民币元),非付费为 0
    guard_level: int = 0           # 1=总督 2=提督 3=舰长
    extra: dict = field(default_factory=dict)

    def __str__(self) -> str:
        if self.type == 'danmaku':
            return f'[弹幕] {self.uname}: {self.text}'
        if self.type == 'gift':
            paid = f' ¥{self.price_rmb:.2f}' if self.price_rmb else ' (免费)'
            return f'[礼物] {self.uname} 送 {self.gift_name}x{self.gift_num}{paid}'
        if self.type == 'super_chat':
            return f'[SC ¥{self.price_rmb:.0f}] {self.uname}: {self.text}'
        if self.type == 'guard':
            return f'[上舰] {self.uname} guard_level={self.guard_level}'
        return f'[{self.type}] {self.uname}'


def dispatch(event: LiveEvent) -> None:
    """下游集成点。当前只打印;接大脑时在这里投递到对话管线。"""
    print(event, flush=True)


# ---- 同一个 Handler 同时实现 web 与 open_live 两套回调 ----------------------

class LumenHandler(blivedm.BaseHandler):
    # web 接口回调
    def _on_danmaku(self, client, message: web_models.DanmakuMessage):
        dispatch(LiveEvent('danmaku', message.uname, client.room_id, text=message.msg))

    def _on_gift(self, client, message: web_models.GiftMessage):
        # 金瓜子才是付费;total_coin 单位为瓜子,1000 金瓜子 = 1 元
        rmb = message.total_coin / 1000 if message.coin_type == 'gold' else 0.0
        dispatch(LiveEvent(
            'gift', message.uname, client.room_id,
            gift_name=message.gift_name, gift_num=message.num, price_rmb=rmb,
        ))

    def _on_super_chat(self, client, message: web_models.SuperChatMessage):
        dispatch(LiveEvent(
            'super_chat', message.uname, client.room_id,
            text=message.message, price_rmb=float(message.price),
        ))

    def _on_user_toast_v2(self, client, message: web_models.UserToastV2Message):
        # source==2 是续费提示,过滤掉只保留实际开通/上舰
        if message.source != 2:
            dispatch(LiveEvent(
                'guard', message.username, client.room_id,
                guard_level=message.guard_level,
            ))

    # open_live 接口回调
    def _on_open_live_danmaku(self, client, message: open_models.DanmakuMessage):
        dispatch(LiveEvent('danmaku', message.uname, message.room_id, text=message.msg))

    def _on_open_live_gift(self, client, message: open_models.GiftMessage):
        rmb = (message.price * message.gift_num) / 1000 if message.paid else 0.0
        dispatch(LiveEvent(
            'gift', message.uname, message.room_id,
            gift_name=message.gift_name, gift_num=message.gift_num, price_rmb=rmb,
        ))

    def _on_open_live_super_chat(self, client, message: open_models.SuperChatMessage):
        dispatch(LiveEvent(
            'super_chat', message.uname, message.room_id,
            text=message.message, price_rmb=float(message.rmb),
        ))

    def _on_open_live_buy_guard(self, client, message: open_models.GuardBuyMessage):
        dispatch(LiveEvent(
            'guard', message.user_info.uname, message.room_id,
            guard_level=message.guard_level,
        ))


# ---- 按模式构建 client 并运行 ----------------------------------------------

async def run_web() -> None:
    room_id = int(os.environ['BILI_ROOM_ID'])
    sessdata = os.environ.get('BILI_SESSDATA', '')
    if not sessdata:
        print('[warn] 未设置 BILI_SESSDATA,用户名会打码、UID 为 0', flush=True)

    cookies = http.cookies.SimpleCookie()
    cookies['SESSDATA'] = sessdata
    cookies['SESSDATA']['domain'] = 'bilibili.com'
    session = aiohttp.ClientSession()
    session.cookie_jar.update_cookies(cookies)

    client = blivedm.BLiveClient(room_id, session=session)
    client.set_handler(LumenHandler())
    client.start()
    print(f'[web] 已连接直播间 {room_id},等待事件...', flush=True)
    try:
        await client.join()
    finally:
        await client.stop_and_close()
        await session.close()


async def run_open_live() -> None:
    client = blivedm.OpenLiveClient(
        access_key_id=os.environ['BILI_ACCESS_KEY_ID'],
        access_key_secret=os.environ['BILI_ACCESS_KEY_SECRET'],
        app_id=int(os.environ['BILI_APP_ID']),
        room_owner_auth_code=os.environ['BILI_ROOM_OWNER_AUTH_CODE'],
    )
    client.set_handler(LumenHandler())
    client.start()
    print('[open_live] 已通过开放平台连接,等待事件...', flush=True)
    try:
        await client.join()
    finally:
        await client.stop_and_close()


async def main() -> None:
    mode = os.environ.get('LUMEN_BILI_MODE', 'web')
    if mode == 'open_live':
        await run_open_live()
    elif mode == 'web':
        await run_web()
    else:
        raise SystemExit(f'未知 LUMEN_BILI_MODE={mode!r},应为 web 或 open_live')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n已停止', flush=True)
