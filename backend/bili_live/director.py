# -*- coding: utf-8 -*-
"""导演层:豆包的情绪标签 → 触发 VTube Studio 的热键(表情/动作)。

机制:连 VTS 插件 API(WebSocket)→ 鉴权(首次在 VTS 弹窗点"允许",token 存盘复用)
→ 按名字触发热键。**豆包情绪词 = VTS 里热键的名字**。
连接闲置会被 VTS 关掉,所以触发时若发现断了就**自动重连**(用存盘 token,不再弹窗)。
VTS 没开/没批准时优雅降级:不驱动表情,但不影响语音。

环境变量:VTS_API_URL(默认 ws://localhost:8001)
"""
import asyncio
import os
import uuid

import aiohttp

VTS_URL = os.environ.get('VTS_API_URL', 'ws://localhost:8001')
_TOKEN_FILE = os.path.join(os.path.dirname(__file__), '.vts_token')
_PLUGIN = {'pluginName': 'Lumen', 'pluginDeveloper': 'lumen'}

# 情绪词表是 brain.EMOTIONS(豆包按它吐 [情绪] 标签);在 VTS 里给热键起同名,导演层按名触发。


class Director:
    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._hotkeys: dict[str, str] = {}      # 热键名 -> hotkeyID(连上一次后缓存)
        self._lock = asyncio.Lock()             # 串行化「重连+收发」整段:connect/trigger 全程持锁,杜绝并发重连互踩
        self._bg: set[asyncio.Task] = set()     # 后台触发任务:留引用防被提前回收
        self.ready = False

    async def _req(self, mtype: str, data: dict | None = None) -> dict:
        # 调用方(connect/trigger)须全程持有 self._lock:把「重连+收发」整段串起来,这里不再单独加锁
        assert self._ws is not None
        await self._ws.send_json({
            'apiName': 'VTubeStudioPublicAPI', 'apiVersion': '1.0',
            'requestID': str(uuid.uuid4()), 'messageType': mtype, 'data': data or {},
        })
        return await self._ws.receive_json()

    async def _auth(self, token: str) -> bool:
        resp = await self._req('AuthenticationRequest', {**_PLUGIN, 'authenticationToken': token})
        return bool(resp.get('data', {}).get('authenticated'))

    async def _connect_ws(self) -> bool:
        """(重)建 ws 并鉴权。有存盘 token 就免弹窗;没有则申请(VTS 弹窗点允许)。"""
        await self._close_ws()
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(VTS_URL)
        token = ''
        if os.path.exists(_TOKEN_FILE):
            with open(_TOKEN_FILE) as f:
                token = f.read().strip()
        ok = await self._auth(token) if token else False
        if not ok:
            resp = await self._req('AuthenticationTokenRequest', _PLUGIN)
            token = resp.get('data', {}).get('authenticationToken', '')
            if token:
                with open(_TOKEN_FILE, 'w') as f:
                    f.write(token)
                ok = await self._auth(token)
        return ok

    async def connect(self) -> bool:
        async with self._lock:                  # 全程持锁,和 trigger 的重连互斥
            try:
                if await self._connect_ws():
                    resp = await self._req('HotkeysInCurrentModelRequest')
                    for hk in resp.get('data', {}).get('availableHotkeys', []):
                        if hk.get('name'):
                            self._hotkeys[hk['name']] = hk.get('hotkeyID', '')
                    self.ready = True
                    print(f'[director] VTS 已连接,可触发热键: {list(self._hotkeys)}', flush=True)
                else:
                    print('[director] VTS 鉴权失败——在 VTS 弹窗点允许后重启', flush=True)
            except Exception as e:
                print(f'[director] VTS 未连上(无表情驱动,不影响语音): {e!r}', flush=True)
                self.ready = False
        return self.ready

    async def trigger(self, emotion: str) -> None:
        if not self.ready:
            return
        hk = self._hotkeys.get(emotion)
        if not hk:                              # 这个情绪没建对应热键 → 跳过
            print(f'[director] 情绪「{emotion}」没有对应热键,跳过', flush=True)
            return
        async with self._lock:                  # 「检查+重连+收发」整段持锁,杜绝并发触发互踩重连
            for attempt in (1, 2):
                try:
                    if self._ws is None or self._ws.closed:
                        if not await self._connect_ws():   # 断了就重连(token 免弹窗)
                            return
                    await self._req('HotkeyTriggerRequest', {'hotkeyID': hk})
                    print(f'[director] 触发表情/动作「{emotion}」✅', flush=True)
                    return
                except Exception as e:
                    await self._close_ws()          # 坏了就丢掉,下一轮重连
                    if attempt == 2:
                        print(f'[director] 触发「{emotion}」失败: {e!r}', flush=True)

    def trigger_bg(self, emotion: str) -> None:
        """非阻塞触发:丢后台跑,留引用防任务被 GC 提前回收。供 on_emotion 回调直接用。"""
        t = asyncio.create_task(self.trigger(emotion))
        self._bg.add(t)
        t.add_done_callback(self._bg.discard)

    async def _close_ws(self) -> None:
        try:
            if self._ws is not None:
                await self._ws.close()
        except Exception:
            pass
        try:
            if self._session is not None:
                await self._session.close()
        except Exception:
            pass
        self._ws = None
        self._session = None

    async def close(self) -> None:
        for t in list(self._bg):
            t.cancel()
        await self._close_ws()
