# B站 AI VTuber 后端(弹幕 → 豆包 → 火山 TTS)

读 B站 直播间弹幕/礼物/SC/上舰(归一成 `LiveEvent`),交给大模型生成有人格的回复,再用 TTS 语音播报。
三个入口:`receiver.py`(只收事件)、`auto_reply.py`(读到→回发弹幕,mode A)、`live_vtuber.py`(读到→豆包→语音,mode B,产品主形态)。
`dispatch()` / `on_event` 是事件下游的边界。

## 两种模式

| 模式 | 何时用 | 需要的凭据 |
|---|---|---|
| `web` | 申请审核前先跑通(非官方接口) | 直播间 `room_id`(+可选 `SESSDATA`) |
| `open_live` | 正式用(官方直播开放平台,稳定合规) | 开放平台密钥 + `app_id` + 主播身份码 |

## 部署 / 换机(从零)

换电脑**不用重搭环境**——代码和依赖跟着仓库走,系统音频另配。

```bash
git clone <仓库> && cd backend/bili_live
uv sync                              # 复现整个 Python 环境(.venv + 锁定依赖,Python 由 uv 自动下)
brew install ffmpeg                  # 火山 TTS 流式播放用 ffplay(edge-tts 兜底用内置 afplay 则不需要)
cp .env.example .env                 # 再把 key 填进 .env(或直接拷旧机的 .env 过来)
set -a && source .env && set +a      # 加载环境变量
uv run python live_vtuber.py
```

| 资产 | 进 git? | 换机怎么办 |
|---|---|---|
| 代码 + `pyproject.toml` + **`uv.lock`** | ✅ | `git clone` + `uv sync`,零手工、版本一致 |
| `.env.example` | ✅ | 模板,照着填 |
| `.env`(密钥) | ❌ gitignore | 拷旧机的,或按模板重填(key 是账号级,到处通用) |
| `.venv` | ❌ gitignore | `uv sync` 自动重建,不用管 |
| BlackHole / OBS / 多输出设备 | ❌(系统级) | **仅推流那台**机器重配一次(~10 分钟) |

> 前提:这些得先 `git commit` + `push`,才谈得上"跟项目走"。`.env`/`.venv` 已被 gitignore,不会上传。

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

读弹幕 → 火山豆包生成口语回复 → 火山/edge-tts 合成 → 本机扬声器播(**流式边出边播**)。这是 VTuber 的真形态(语音,不发弹幕)。

```bash
export BILI_ROOM_ID=<直播间ID>
export ARK_API_KEY=<方舟key> ARK_MODEL=<接入点ID>
# 可选:export BILI_SESSDATA=<...>(用户名不打码) TTS_VOICE=zh-CN-XiaoxiaoNeural
uv run python live_vtuber.py
```

有弹幕进来就会听到 AI 语音回应。**单飞**:一句说完再说下一句,说话时新弹幕进队列(`VTUBER_QUEUE_MAX`,默认 2),满了丢弃保新鲜。

- 回复人格 = `brain.py` 的 `SYSTEM_PROMPT`,在那里打磨角色。
- **流式**:豆包 `stream=True` 按句吐 + 火山 SeedTTS 边出边播,首句先开口(`brain.reply_stream` + `voice.speak`)。
- **TTS**:设了 `VOLC_TTS_API_KEY` → 火山 SeedTTS 2.0(saturn 可爱女声等,**流式 ffplay**,需 `brew install ffmpeg`);否则回落 edge-tts(afplay)。`VOLC_TTS_API_KEY` 是语音控制台**专门的 API Key**,不是 app 的 Access Token/Secret、也不是 Ark key。
- ⚠️ **首响仍慢**:实测豆包免费「按Token付费」档 TTFT 3-8s 是瓶颈,流式解不了(火山 TTS 首包仅 0.57s)。需 TPM保障包 / 换云,详见 `docs/项目进度.md` 问题2。
- v2 待办:声音复刻统一音色 + 首响降延迟(豆包 TTFT)+ 干净的 OBS 合成上播。Live2D 口型/导演层见下一节(已做)。

**火山 SeedTTS 2.0 接口要点(踩坑记录)**:
- 端点 `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`
- 头 `X-Api-Key` = 语音控制台**专门的 API Key**(UUID 形如 `e08a...`);app 凭据页的 **Access Token / Secret Key、方舟 Ark key 都无效**(报 `45000010 Invalid X-Api-Key`)
- 头 `X-Api-Resource-Id: seed-tts-2.0`
- 体 `req_params{text, speaker=<音色>, audio_params{format:mp3, sample_rate:24000}}`
- 返回逐行 JSON:`code==0` 带 base64 音频分片、`20000000` 结束
- 音色示例:`saturn_zh_female_keainvsheng_tob`(可爱女声)

## 音频上流(本机 macOS)

让 TTS 语音进直播流的本机方案:TTS(afplay)→ 多输出设备 → 扬声器(自己听)+ BlackHole(虚拟声卡)→ 采集软件 → 推流。

1. `brew install --cask blackhole-2ch obs`(BlackHole 是音频驱动,装后跑 `sudo killall coreaudiod` 或重启,设备才出现)
2. 「音频 MIDI 设置」→ 建**多输出设备**(命名如 `Lumen上流`):勾 **BlackHole 2ch** + **扬声器**;主设备=扬声器,给 **BlackHole** 勾「漂移校正」
3. 系统设置 → 声音 → 输出 → 选该多输出设备
4. 采集软件加「音频输入采集」→ 设备选 **BlackHole 2ch**
5. 验证:播一句 TTS,采集软件电平条跳动即通(已实测通过)

> ⚠️ 多输出设备会把**所有**系统声音(通知音等)灌进流——直播时静音其他 app;且多输出设备下系统音量键失效(macOS 限制)。
> ⚠️ **推流约束**:OBS/第三方推流码需**粉丝 ≥5000**;B站直播姬仅 Windows;**Mac + 低粉账号此路不通**(详见 `docs/implementation-plan.md` 开放问题)。

## Live2D 形象 + 导演层(情绪 → 表情/动作)

形象用 **VTube Studio**(Mac 版,Steam,免费);口型 + 表情/动作复用已配的 BlackHole。

### 口型(音量驱动)
1. VTS 麦克风设置 → 输入选 **BlackHole 2ch** + 打开「使用麦克风」。
2. 系统输出设为「Lumen上流」(语音同时进扬声器 + BlackHole)。
3. **两个坑**:
   - macOS 要给 **VTube Studio 麦克风权限**(系统设置 → 隐私与安全性 → 麦克风),改完**重启 VTS**;
   - 模型参数里把 **Mouth Open 的输入从 `MouthOpen`(摄像头追脸)改成 `VoiceVolume`(麦克风音量)**——没摄像头时前者恒为 0、嘴不动。

### 导演层(`director.py`):情绪 → VTS 热键
机制:豆包每条回复开头吐 `[情绪]` → `brain.reply_stream` 解析剥离 → `director` 触发 VTS **同名热键**(表情/动作)。情绪集 = `brain.EMOTIONS`(单一源:开心/惊讶/害羞/生气/思考/平静)。

设置:
1. VTS **紫色天线图标 → 开启 API**(端口 8001,对应默认 `VTS_API_URL=ws://localhost:8001`)。
2. 在 VTS 建**热键**,**名字 = 情绪词**(如 `开心`),动作绑「激活表情」或「播放动画 motion3」。建几个支持几个,没建的情绪静默跳过。
3. 首次跑 `live_vtuber.py` → VTS 弹"Lumen 想连接" → 点**允许**(token 存 `.vts_token`,下次免弹窗)。
4. 连接闲置会被 VTS 关,触发时**自动重连**;VTS 没开/没批准则优雅降级,不影响语音。

> 肢体动作(挥手/鼓掌)取决于**模型有没有绑手臂 + 有没有对应动画**;免费 Hiyori 多是轻微姿势,大幅手势要换"绑了肢体"的好模型(美术)。机制不变,换模型即可。

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
