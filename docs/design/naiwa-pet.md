# 像素奶蛙：动画与宠物包说明

像素奶蛙（Pixel Naiwa，`naiwa`）是供 DSH Go 导入的无声像素宠物包。经典黄色身体、奶油色肚皮、浅绿眼圈和灰褐色小爪绘制在 64×64 透明画布上，共 **25 段动画、254 帧**。全部帧见 [总览大图](../assets/naiwa-frames.png)，调色板、每段帧数和绘制方法见 [素材说明](../../app/tool/pet_src/naiwa/README.md)。

## 1. 播放规则

以 main 的 schema 1 解析器、状态归约和手势入口为准。App 保留原有内置宠物，奶蛙通过「设置 → 宠物 → 导入」安装；不需要奶蛙专属 App 接口。

动画中的代码字符已绘制在 PNG 帧里，不读取或吞掉聊天内容。拖动、游走和镜像遵循通用宠物规则；正视素材使用 `roam.faces: front`，不启用页面自由拖动。声音资源仅保留参考，动作不等待录音。

## 2. 场景与动画分配

| 入口 | 动画 | 触发与结束 |
|---|---|---|
| `idle` | `idle` | 范围内没有运行中的任务，呼吸、眨眼循环 |
| 待机池 | `idle-look`、`idle-giggle`、`snack`、`dance` | 四项等权；分别播放 2、2、1、2 遍，然后回待机 |
| `thinking` | `thinking` | 等模型、推理或重试期间 |
| `working` | `eat-code`、`eat-code-fast`、`feast` | 工具运行或流式回复；按全局运行会话数分成 1、2、3+ 档 |
| `juggling` | `juggle`、`juggle-many` | 子代理运行，按 1、2+ 档 |
| `attention` | `laugh` | 一轮完成后 1.5 秒内没有新一轮；基础完成态 3180 ms |
| 完成彩蛋 | `laugh-point`、`dance` | 进入完成态时以 50% 概率抽彩蛋，两项等概率；各播一遍再回 `laugh` |
| `carrying` | `juggle` | 导入宠物包期间复用抛接代码块，成功或失败后清除信号 |
| `error` | `shocked` | 一轮失败，默认显示 2180 ms |
| `notification` | `alert` | 有待确认、待回答事项，持续到处理完成 |
| `sweeping` | `devour` | 上下文压缩期间 |
| `sleeping` / `waking` | `sleep` / `wake` | 无任务且 60 秒无交互后睡眠；触摸或任务唤醒，`wake` 播 1720 ms |
| `roam.anim` | `walk` | 聊天页待机时由 App 安排游走 |
| `tapLeft` / `tapRight` | `poke-left` / `poke-right` | 点身体左右半边，播放 900 ms |
| `tickle` / `tickle2` / `tickle3` | `tickle` / `laugh-belly` / `laugh-roll` | 1.1 秒内三连点，三项等概率，分别播放 1420 / 780 / 880 ms |
| `annoyed` | `shocked` | 同一窗口内继续到第六下，打断当前反应，播放 1090 ms 并清空点击计数 |
| `drag` | `prone` | 拖动时交替伸爪、蹬腿趴行，配合轻微起伏和眨眼；松手后由 App 返回当前状态 |

`shocked` 在六连点场景表现为「被连续戳后的惊跳」，复用现有画面；`juggle` 在导入场景表现为整理数据。所有 25 段都有状态、档位、待机、彩蛋或交互入口。

待机间隔是 `min: 10000`、`mean: 18000`、`max: 25000` 毫秒，每段插播结束后重新等待。待机小动作不延长 60 秒休眠计时；正在工作、拖动、隐藏或播放反应时不会强行插播。四种动作各有 25% 的抽取概率，不保证一轮清醒时间里全部出现。

三连点后的第 4、5 下继续按 main 规则抽取挠痒反应，第 6 下转为 `annoyed`。睡着时先唤醒；有待处理事项时，点按按 App 的跳转规则执行。反应和彩蛋到时返回当前状态；即使素材本身可循环，也不延长为完整录音时长。

App 外悬浮窗支持状态、左右点按及拖动，但不游走、不触发三连点和六连点。将多个 `reactions` 候选写成基础名与编号键，旧版可读取基础项；完整的变体、六连点和导入状态行为以当前 main 为准。

## 3. 美术约束

- `prone` 为 16 帧、1720 ms 的纯趴行循环，没有代码道具、张嘴或咀嚼；其它 24 段的像素和时长不变。透明像素为 `(0,0,0,0)`，其它 alpha 为 255。
- 正视待机是比例基准：上臂约 4.61 像素、前臂 4 像素、爪半径 1.75 像素；趴爬沿用相同比例。
- 脚底线 y = 60，身体中轴 x = 32；命中区只量身体，离体字符、气泡和音符不计入。
- 睁眼高光、眼睛与嘴型逐帧检查；捂嘴、吞字符和睡眠泡泡可有意遮挡嘴部。
- 直立进食的嘴中心为 (32,39)，只用于绘图一致性检查，不输出聊天粒子接口。
- `wake`、`poke-left`、`poke-right`、`tickle` 不循环并回到待机姿势。其它动画保持原循环标记，实际播放时长由状态或反应入口控制。

## 4. 来源、生成与打包

`app/tool/pet_src/naiwa/draw.py` 是画面和映射的输入，生成 `pet.json` 与 `sheets/*.png`。`app/tool/make_pet_pack.py` 裁切、去重、量命中框，生成 `app/assets/pets/naiwa/pack.json` 与 25 张 PNG；不要手改这些生成物。

源格式的 `states`、`tiers`、`bonus`、`reactions` 引用既有动画。`holds` 将状态保持遍数换算成毫秒；`idlePool[].loops` 换算成插播时长。源格式的 `states.roam` 用来生成 `roam.anim`，App 的游走只读后者。编号反应值均为字符串，构建器检查基础名存在及动画引用有效。

生成的清单保持 `schema: 1`，不包含 `sounds`、`snack`、`roam.free` 或 `drag.mirror`。使用如下命令：

```bash
python app/tool/pet_src/naiwa/draw.py
python app/tool/pet_src/naiwa/draw.py --check --preview docs/assets/naiwa-frames.png
python app/tool/pet_src/naiwa/draw.py --check --strip prone --gif prone
python app/tool/make_pet_pack.py --only naiwa
python tooling/pets/build_pet_pack.py --src app/assets/pets/naiwa --out app/build/pet_main_compat/naiwa.zip
```

ZIP 只有顶层 `pack.json` 和它引用的 25 张 PNG。导入后 App 使用 `user-naiwa` 安装目录；同名再次导入更新同一只宠物。

## 5. 保留的声音资源

六段原始 WAV、来源记录、提取与生成脚本，以及 `app/assets/pet_sounds/naiwa/` 的已生成资源继续保留。原笑声约 25.286531 秒，录音及重采样字节均不改变；它不决定当前动画播放时长。

音频不注册到 App、不随 APK 或宠物 ZIP 打包。`sounds.json` 的旧 cue 对应关系仅作为资源参考。详细来源与许可见 [音频说明](../../app/tool/pet_src/naiwa/audio/README.md)、[ASSETS.md](../../ASSETS.md) 与 [THIRD_PARTY_NOTICES.md](../../THIRD_PARTY_NOTICES.md)。

## 6. 验证

绘图自检验证帧数、颜色、透明度、身体连通块、手臂长度、五官和嘴部锚点；构建测试验证源图与打包图逐像素一致、所有引用有效、全部动画可达和重复构建一致。

App 测试使用 main 的解析器与导入库验证包，按真实聊天页播放器覆盖四种待机小动作、工作档位、完成彩蛋、导入、三连点候选及六连点。声音资源单独校验，不能把资源校验通过写成 App 支持声音。
