# 像素奶蛙

简体中文 · [English](README.en.md)

面向 DSH Go 的像素宠物包，包名为 `naiwa`。经典奶黄色身体、奶油色肚皮、浅绿眼圈和灰褐色小爪，采用 64×64 透明画布，以逐帧动画表现思考、工作、大笑和日常互动。

整套包含 **25 段动画、254 帧**。所有动画帧都收在下方大图中，按动作分组，逐帧标注编号和时长，可用于查看造型、动作节奏和制作参考。

[![像素奶蛙全部 25 段动画、254 帧总览](docs/assets/naiwa-frames.png)](docs/assets/naiwa-frames.png)

点击大图可查看原始尺寸。各组从左到右、从上到下排列，`loop` 表示循环播放，`once` 表示播放一次。

| 场景 | 动作 |
| --- | --- |
| 待机 | 呼吸眨眼 `idle`、左右张望 `idle-look`、捂嘴偷笑 `idle-giggle`、吃点心 `snack`、摇摆跳舞 `dance` |
| 思考 | 托腮沉思 `thinking` |
| 工作 | 吃代码 `eat-code`、加速进食 `eat-code-fast`、狼吞虎咽 `feast`，对应 1、2、3 个及以上运行中的会话 |
| 子代理运行 | 抛接代码块 `juggle`、多块抛接 `juggle-many`，对应 1、2 个及以上子代理 |
| 任务完成 | 大笑 `laugh`，以及指着笑 `laugh-point`、翻滚笑 `laugh-roll`、捧腹起伏 `laugh-belly` |
| 出错与提醒 | 抬爪惊讶 `shocked`、挥手提醒 `alert` |
| 上下文压缩 | 吞下代码条 `devour` |
| 休息与游走 | 打盹 `sleep`、醒来伸懒腰 `wake`、走路 `walk` |
| 点按互动 | 左右被戳 `poke-left` / `poke-right`、连续点按后的大笑 `tickle` |
| 拖动 | 趴着爬行和咀嚼 `prone-eat` |

聊天页正常待机时，每隔 10–25 秒随机插播张望、偷笑、吃点心或跳舞。无任务且 60 秒没有交互后进入睡眠，待机动作不会延长清醒时间。

动作以待机正视帧为造型基准，上臂、前臂长度和爪子尺寸统一。身体随动作轻微伸缩，眼睛与嘴型保持清楚，点按和唤醒动作在末帧回到待机姿势。吃代码时出现的字符绘制在动画帧内。

制作与格式参考可从下面的文件查看。

| 参考内容 | 位置 |
| --- | --- |
| 宠物包清单与动画图集 | [app/assets/pets/naiwa/](app/assets/pets/naiwa/) |
| 绘制说明、调色板与生成命令 | [素材说明](app/tool/pet_src/naiwa/README.md) |
| 逐帧绘制脚本 | [draw.py](app/tool/pet_src/naiwa/draw.py) |
| 帧时长与动作映射 | [pet.json](app/tool/pet_src/naiwa/pet.json) |
| DSH Go 宠物包格式 | [宠物设计与格式](docs/design/pets.md) |

像素绘制来自 cxsunflower，形象参考网络二创「奶蛙」。角色形象权利归原权利人，来源与素材条款见仓库声明。[cxsunflower](https://github.com/cxsunflower) · [形象参考](https://github.com/Orliss/nailong) · [素材声明](ASSETS.md)

宠物包使用 ccch1mneyyy 维护的 DSH Go 宠物系统。仓库代码采用 AGPL-3.0，`sdk/` 和 `examples/` 采用 MIT，第三方内容按各自声明授权。[DSH Go](https://github.com/ccch1mneyyy/dsh-Go) · [LICENSE](LICENSE) · [第三方声明](THIRD_PARTY_NOTICES.md)
