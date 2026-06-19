# B站弹幕/礼物接收器

把 B站 直播间的弹幕、礼物、醒目留言(SC)、上舰事件归一成 `LiveEvent`,经 `dispatch()` 下发。
目标:先跑通"事件流入"这条管线。`dispatch()` 是后续接大脑/导演层的边界。

## 两种模式

| 模式 | 何时用 | 需要的凭据 |
|---|---|---|
| `web` | 申请审核前先跑通(非官方接口) | 直播间 `room_id`(+可选 `SESSDATA`) |
| `open_live` | 正式用(官方直播开放平台,稳定合规) | 开放平台密钥 + `app_id` + 主播身份码 |

## 安装(uv)

```bash
cd backend/bili_live
uv sync          # 读 pyproject.toml,创建 .venv 并装好依赖(blivedm 从 git 构建)
```

## 跑通 web 模式(今天就能测)

`room_id` 看直播间 URL 末尾数字。`SESSDATA` 从已登录浏览器 Cookie 复制。
**实测:不填 `SESSDATA` 弹幕文本照样能收到,只是用户名打码(如 `正***`)、UID 为 0;要完整用户名/UID 才需要填。**

```bash
export LUMEN_BILI_MODE=web
export BILI_ROOM_ID=<直播间ID>
export BILI_SESSDATA=<可选>
uv run python receiver.py
```

随便找个在播的直播间,终端应实时打印 `[弹幕] xxx: ...` / `[礼物] ...`。

## 发弹幕闭环 auto_reply.py(mode A:AI 当弹幕机器人)

读到弹幕 → 自动回发一条弹幕。**发弹幕必须登录**,要 `SESSDATA` + `bili_jct`(同一个 Cookie 面板复制)。

```bash
export BILI_ROOM_ID=<直播间ID>
export BILI_SESSDATA=<你的> BILI_BILI_JCT=<你的>
export REPLY_MIN_INTERVAL=5
uv run python auto_reply.py
```

回复内容由 `auto_reply.py` 的 `make_reply()` 决定,当前是占位 echo(`收到:xxx`),后续替换成调用豆包 LLM。

> ⚠️ 注意:
> - 这是**测试/辅助形态**。VTuber 产品的真回应是 **TTS 语音 + 字幕**,不是发弹幕。
> - 自动发弹幕有**被限流/封号**风险:用测试账号、低频率(`REPLY_MIN_INTERVAL` 别调太低)、在自己/测试房间跑。
> - 已内置**节流**和**自过滤**(跳过自己刚发的弹幕,防自激循环)。

## 语音回复 live_vtuber.py(mode B:大模型 + TTS 语音播报)

读弹幕 → 火山豆包生成口语回复 → edge-tts 合成 → 本机扬声器播。这是 VTuber 的真形态(语音,不发弹幕)。

```bash
export BILI_ROOM_ID=<直播间ID>
export ARK_API_KEY=<方舟key> ARK_MODEL=<接入点ID>
# 可选:export BILI_SESSDATA=<...>(用户名不打码) TTS_VOICE=zh-CN-XiaoxiaoNeural
uv run python live_vtuber.py
```

有弹幕进来就会听到 AI 语音回应。**单飞**:一句说完再说下一句,说话时新弹幕进队列(`VTUBER_QUEUE_MAX`,默认 2),满了丢弃保新鲜。

- 回复人格 = `brain.py` 的 `SYSTEM_PROMPT`,在那里打磨角色。
- v1 用 edge-tts(免费)+ 本机扬声器;v2 换火山 TTS(声音复刻)+ 流式 + 虚拟声卡接 OBS,并加 Live2D 口型。
- 播放用 macOS `afplay`(本机假定 macOS)。

## 切到 open_live 模式(审核通过后)

需要你本人在 B站 完成的一次性开通(代码替不了):

1. 去 https://open-live.bilibili.com/ → 创作者服务中心,注册开发者,提交审核(约 2 工作日)。
2. 审核通过后,在【个人资料】拿 `access_key_id` / `access_key_secret`。
3. 【我的项目】→ 创建项目,类型选「互动玩法」,得到 `app_id`(项目ID)。
4. 主播在「个人中心 → 我的直播间 → 开播设置」点开始直播,生成**身份码**。

```bash
export LUMEN_BILI_MODE=open_live
export BILI_ACCESS_KEY_ID=<...>
export BILI_ACCESS_KEY_SECRET=<...>
export BILI_APP_ID=<项目ID>
export BILI_ROOM_OWNER_AUTH_CODE=<主播身份码>
uv run python receiver.py
```

两种模式打印的 `LiveEvent` 结构完全一致,下游无需区分来源。

## 归一事件

`LiveEvent.type`: `danmaku` | `gift` | `super_chat` | `guard`;
金额统一折算到 `price_rmb`(元),`guard_level`: 1=总督 2=提督 3=舰长。
