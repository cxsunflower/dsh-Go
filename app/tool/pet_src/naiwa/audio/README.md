# 奶蛙音效输入

`python3 app/tool/make_pet_sounds.py` 校验这里的六个 WAV，再打包到 `app/assets/pet_sounds/naiwa/`；`--check` 只读校验。普通构建与测试只用 Python 标准库，不联网、不需要 FFmpeg、NumPy 或 Pillow。

六段全部来自 Valve《Deadlock》的一个 addon 资源包，不是网上流传的奶蛙梗录音：

- 压缩包：`nawa_pak50_dir_bf496.7z` → `nawa_pak50_dir.vpk`，1,427,634 字节，SHA-256 `093ace9eef9b133e923fd08a3d7c70472f84855df8731e704b3855349483af13`（Valve VPK v2）。
- 包内命名空间：`citadel_addons/naiwa`，即把英雄 Dynamo 的语音/技能音换成奶蛙的 mod。
- 包里的 50 条 VO 是空壳（每条固定 5671 字节、无真实语音），只有 6 个技能音有内容，也就是下表这六段。
- 解包流程：`vsnd_c` 里的 KV3 资源头 + MP3 数据段取出 MP3，再解码为 PCM16 单声道 22050 Hz WAV。本目录保存的是解码后的 WAV，`sources.json` 同时记着 pak、包内条目与原 `vsnd_c` 的 SHA-256。重新提取用 `python3 extract_from_pak.py <nawa_pak50_dir.vpk> --ffmpeg <ffmpeg>`（只这一步需要 ffmpeg，构建与测试仍只用 Python 标准库）：它按 `sources.json` 核验每个 `vsnd_c` 与产出的 WAV 哈希，逐字节复现本目录的文件。

| 输入（= clip id） | 角色 / cue | pak 内条目 | 时长 | 处理 |
|---|---|---|---|---|
| `hahahahahahaha.wav` | 大笑 `laugh`、`laugh-point`、`laugh-roll`、`laugh-belly` | `sounds/abilities/dynamo/dynamo_singularity_lp.vsnd_c` | 25.286531 秒 | **保留整段**；22050 Hz 的 PCM 有 1,115,214 字节，超过 SoundPool 单段上限，故降为 11025 Hz（278,784 帧 = 557,568 字节 PCM） |
| `dajiaosei.wav` | 戳左 `poke-left` | `sounds/abilities/dynamo/dynamo_a1_stomp_prestomp_01.vsnd_c` | 1.071020 秒 | 逐字节复制，22050 Hz |
| `diu.wav` | 戳右 `poke-right` | `sounds/abilities/dynamo/dynamo_a1_stomp_prestomp_02.vsnd_c` | 1.071020 秒 | 逐字节复制，22050 Hz |
| `andi.wav` | 叫醒 `wake` | `sounds/abilities/dynamo/dyanmo_a2_quantum_cast.vsnd_c`（包内拼写即 `dyanmo`） | 1.306122 秒 | 逐字节复制，22050 Hz |
| `gagadilaxia.wav` | 趴着吃 `prone-eat` | `sounds/abilities/dynamo/a3_heal/dynamo_a3_heal_cast_01.vsnd_c` | 1.384490 秒 | 逐字节复制，22050 Hz |
| `houla.wav` | 通知 `alert` | `sounds/abilities/dynamo/a3_heal/dynamo_a3_heal_cast_02.vsnd_c` | 2.089796 秒 | 逐字节复制，22050 Hz |

## 打包与限制

- 资产文件名与 `sounds.json` 的 clip id 一律用上表的用户名；pak 原条目只出现在本文件和 `sources.json` 里。id 满足 `^[a-z0-9-]+$`，文件名满足 `*.wav`。
- 格式固定 PCM16 单声道。**为绕开 SoundPool 单段上限，只有笑声降到 11025 Hz，其余五段仍 22050 Hz**。整套 ≤1,500,000 字节；每段解码 PCM ≤1,000,000 字节（SoundPool 会截断更大的样本）。
- 除笑声的半速率重采样外不重新编码、不截断、不做 EQ、压限、响度归一化、变速、变调、淡入淡出或混响。重采样用标准库线性插值：输出第 i 帧映射到源区间 `i × (F−1) / (N−1)`，在相邻样本间按小数部分插值，两端落在源首帧和末帧，时长保持 25.286531 秒；`make_pet_sounds.py` 只改写 `fmt` 与 `data` 块，保留其它块。
- `sounds.json` 每段带 `gain: 1.0`、`vary: 0.0` 与 `ms`（该段实际长度，四舍五入到毫秒；笑声为 25287）。`ms` 让有录音的一次性反应保持到录音结束；`vary: 0` 表示没有随机变调，保留原始录音的音高。
- `@bite`（吃字）、`@drop`（落地）以及其余没有列出的动作仍然静音，不生成咀嚼、弹簧或提示音。

## 映射

| cue | clip |
|---|---|
| `laugh`、`laugh-point`、`laugh-roll`、`laugh-belly` | `hahahahahahaha` |
| `poke-left` | `dajiaosei` |
| `poke-right` | `diu` |
| `wake` | `andi` |
| `prone-eat` | `gagadilaxia` |
| `alert` | `houla` |

## 授权

这六段是 Valve 游戏《Deadlock》附带资源里的音频，**再分发许可未确认**。它们不纳入本仓库 AGPL-3.0，也不随公开构建分发：仅按用户要求在本地个人包中使用，权利归原权利人。正式公开发布前须取得许可或换成可再分发素材。登记见 [ASSETS.md](../../../../ASSETS.md) 与 [THIRD_PARTY_NOTICES.md](../../../../THIRD_PARTY_NOTICES.md)。

`sources.json` 保存每段的 pak 名、pak SHA-256、包内条目、原 `vsnd_c` SHA-256、输入 WAV SHA-256、帧数、字节数、时长和重采样说明；`make_pet_sounds.py` 在打包前逐条核对。
