# 流明 · AI VTuber

> **现行技术决策与进度以子文档为准**(本文件是概览):
> [docs/implementation-plan.md](docs/implementation-plan.md) — 决策与 why ·
> [docs/项目进度.md](docs/项目进度.md) — 进度/问题/上报 ·
> [backend/bili_live/README.md](backend/bili_live/README.md) — 操作与配置

## 产品形态

- **定位**:AI-native 陪伴/互动型虚拟主播——读弹幕 → AI 即兴、有人格地**语音回应**;目标是"像活人一样陪聊 + 接梗 + 答谢礼物"。
- **不是**:3D 唱跳偶像、电商口播数字人。
- **首发平台**:**B站**(原计划抖音已否决,见[决策一](docs/implementation-plan.md))。

## 技术架构(实际)

```
B站 弹幕/礼物/SC/上舰 ──(blivedm,实时)──┐
                                       ▼
       豆包 LLM〔火山 Ark〕→ 人格「流明」+ 短期记忆 → 一句口语回应
                                       │
                                       ▼
       火山 SeedTTS 2.0〔云〕→ 语音 mp3 → 本机播放(afplay)
                                       │
                                       ▼
       BlackHole 虚拟声卡 → OBS 采集 → B站 推流〔⚠️ 5000 粉门槛〕
                                       ▲
                           Live2D 形象 / 口型(待做)
```

与最初设想的两处大改:**平台 抖音 → B站**、**渲染 UE5/云GPU → 2D Live2D**(LLM/TTS 都是云 API,本机不吃 GPU)。
**核心增量**仍是"LLM 意图 → 动作/表情"的导演层——难的不是生成动作,是 LLM 在对的时机选对反馈;只是落在 2D 上比 UE5 轻一个量级。

## 现状一句话

核心闭环"弹幕 → 豆包 → 火山语音"**已在真实 B站 直播间跑通**;卡在三处:正式推流上播(Mac+低粉门槛)、响应速度偏慢、Live2D 画面未做。详见 [项目进度](docs/项目进度.md)。

## 技术栈(实际)

| 环节 | 选型 | 状态 |
|---|---|---|
| 弹幕接入 | blivedm(B站,web 模式) | ✅ |
| 大脑 | 火山豆包 Ark(OpenAI 兼容)+ 人格 + 短期记忆 | ✅ |
| 语音 | 火山 SeedTTS 2.0(流式 ffplay)+ edge-tts 兜底 | ✅ |
| 编排 | 自建轻量直连管线(非 Open-LLM-VTuber fork) | ✅ |
| 形象 | 2D Live2D(自购/委托,商用授权) | ❌ 未做 |
| 采集/推流 | 本机 BlackHole+OBS → B站 rtmp | ⚠️ 受 5000 粉门槛阻塞 |
| 内容安全 | 双向敏感词 + AI生成标注 | ❌ 未做(上线前必须) |

完整选型与 why 见 [implementation-plan.md](docs/implementation-plan.md)。

## MVP 验证范围

**只验一件事**:纯 AI 能不能跑出"弹幕来了 → 对的话 + 像活人不僵硬"的 liveness,以及能不能触发打赏。
策略**先借后造**:开源/占位先把对话闭环验掉,Live2D 形象与导演层动作放在内容验证之后。

## 开放问题(落地前要解)

- **B站 推流门槛**:OBS 推流码需 ≥5000 粉;直播姬仅 Windows → Mac+低粉走不通(见[项目进度·问题1](docs/项目进度.md))。
- **首响慢**:流式已做(火山 TTS 首包 0.57s),但豆包免费档 TTFT 3-8s 是真瓶颈 → 需 TPM保障包/换云(见[项目进度·问题2](docs/项目进度.md))。
- **合规**:AI生成标注 + 双向内容安全未做。
