# 奶蛙 · 方案 A「经典奶蛙」（宠物包 `naiwa`）

形象参考网络二创『奶蛙』用脚本重画，非官方，仓库不含任何参考图。

经典黄色版本：梨形身体，头和身子连成一体，没有脖子；奶油色肚皮，浅绿色眼圈配黑瞳孔，灰褐色的小爪和脚。大笑时眼睛弯成两道弧，嘴巴张到半张脸那么大。所有帧都由 `draw.py` 用 numpy + Pillow 逐像素画出，不读取任何外部图片。动画清单和状态映射见 [docs/design/naiwa-pet.md](../../../../docs/design/naiwa-pet.md) 第 3、4 节。

## 文件

| 文件 | 说明 |
|---|---|
| `draw.py` | 生成脚本，唯一的源文件 |
| `pet.json` | 由 `draw.py` 写出：帧时长、状态映射、档位、待机池、反应、`snack` |
| `sheets/<anim>.png` | 由 `draw.py` 写出：1 倍单行横条，每帧 64×64，共 26 段 |

`pet.json` 和 `sheets/` 是生成物，不要手改，改 `draw.py` 后重新生成。

## 重新生成

在仓库根目录运行（需要 numpy 和 Pillow）：

```bash
python app/tool/pet_src/naiwa/draw.py              # 重画并写出 sheets/ 和 pet.json，然后自检
python app/tool/pet_src/naiwa/draw.py --check      # 只在内存里重画并自检；磁盘上的文件过期也算失败
python app/tool/pet_src/naiwa/draw.py --preview    # 另写全帧总览 app/build/pet_src_preview/naiwa.png
python app/tool/pet_src/naiwa/draw.py --strip laugh feast   # 另写单段放大图 app/build/pet_src_preview/naiwa/<anim>.png
```

脚本不读时钟、不用随机数，两次运行的输出字节相同。打包试跑（只输出到 `app/build/`）：

```bash
python app/tool/make_pet_pack.py --only naiwa --out app/build/pet_try --preview app/build/pet_try_preview
```

## 画布与尺寸

- 画布 64×64，透明像素一律是 `(0, 0, 0, 0)`，其余 alpha 都是 255，不抗锯齿。
- 待机身体约 30×34：躯干最宽 30 像素（含描边），加上两侧小爪是 32 像素，占 x 16–47；高 34 像素，占 y 26–59。
- 身体中轴 x = 32，脚底线 y = 60（最低的不透明行是 59）。待机各帧脚底线不变，不带离体道具。
- `snack.mouth` = (32, 39)，是张大嘴（10×8 的 `eat` 嘴形）的中心。所有进食动画张嘴帧的嘴中心都在它 ±1 像素以内。

## 调色板

| 名字 | 颜色 | 用途 |
|---|---|---|
| `line` | `#4A2E12` | 1 像素深棕描边 |
| `body` / `body_hi` | `#F6D24A` / `#FFE98A` | 身体主色 / 头顶高光（光从左上来） |
| `body_lo` / `body_lo2` | `#DDA92F` / `#B98522` | 两级暗部（右下边缘） |
| `belly` / `belly_lo` | `#F8EBC8` / `#E6D3A3` | 奶油色肚皮及其暗部 |
| `eye` / `pupil` / `white` | `#A6DC78` / `#141414` / `#FFFFFF` | 浅绿眼圈 / 黑瞳孔 / 眼睛反光、牙齿、嗝气、鼻涕泡高光 |
| `mouth` / `tongue` | `#4A1222` / `#E86A7C` | 口腔 / 舌头 |
| `paw` / `paw_lo` | `#6F665A` / `#4F483F` | 灰褐色爪和脚及其暗部 |
| `blush` | `#F6A08E` | 腮红 |
| `ha` / `bang` / `ask` / `zz` | `#FF5A3C` / `#FF4040` / `#6FB7FF` / `#8FA6D8` | 「哈」字 / 感叹号 / 问号和思考的点点 / Zzz |
| `sweat` / `snot` | `#8ED8FF` / `#CFF4FF` | 汗滴 / 鼻涕泡 |
| `code_line` / `tile` | `#282C34` / `#3E4451` | 代码字符和代码方块的描边 / 代码方块底色 |
| `c1`–`c6` | `#C678DD` `#98C379` `#D19A66` `#61AFEF` `#E5C07B` `#ABB2BF` | 代码字符的语法高亮色 |
| `box` / `box_lo` / `box_hi` / `paper` | `#D9A05B` / `#B07A3A` / `#F0C987` / `#FFF8E6` | 搬运的文件箱和纸 |
| `ghost_r` / `ghost_c` | `#FF3D6E` / `#2EE6FF` | 鬼畜残影 |

鬼畜段落的单帧换色另有两套身体色：粉 `#FF8FC8` 系、青 `#6FE0F0` 系（见 `draw.py` 的 `TINTS`）。每段动画实际用到 12–36 种颜色。

## 画法

- 躯干是绕 x = 32 的逐行半宽轮廓：圆顶、两侧向下变宽、低处的肚子、圆底。姿势在这个轮廓上做挤压/拉伸、斜切（身体倾斜）、平移和旋转。
- 肚皮是躯干内的椭圆；手臂是两段胶囊加一个小圆爪；腿是短胶囊加半椭圆脚。
- 光从左上来：右下边缘两级暗部，头顶一块高光。描边是所有部件的 4 邻域膨胀减去部件本身；挡在躯干前面的手臂在重叠处也有自己的描边。
- 眼睛、嘴、道具是手绘的小位图，按骨架锚点盖上去；左右对称的五官按中轴对称取整，落在镜像的像素上。
- 离体道具（哈、Z、!、?、代码字符和方块、碎屑、汗滴）带 8 邻域描边，并和身体至少隔 1 个透明像素，打包工具按「最大连通块」找身体时不会把它们算进去。爪里拿着的道具、搬运的箱子和鼻涕泡故意贴着身体。

## 动画

| 动画 | 帧数 | 总时长 | 内容 |
|---|---|---|---|
| `idle` | 12 | 2540 ms | 原地呼吸，身体一伸一缩，偶尔眨眼 |
| `idle-look` | 10 | 2260 ms | 身体歪向左边张望，再歪向右边，小爪跟着摆 |
| `idle-giggle` | 10 | 1290 ms | 想到什么，捂嘴偷笑，肩膀一抖一抖 |
| `snack` | 10 | 2010 ms | 瞄到右边飘着一个分号，伸手抓来塞进嘴里，嚼几下，打个小嗝 |
| `dance` | 10 | 1520 ms | 张开双臂左右摇摆，轮流抬脚 |
| `thinking` | 8 | 2060 ms | 托下巴往上看，旁边的点点变成问号 |
| `eat-code` | 12 | 1340 ms | 代码字符从右边飞进张大的嘴，嚼两口 |
| `eat-code-fast` | 10 | 850 ms | 两只爪轮流往嘴里塞代码，一只喂一只抓下一个 |
| `feast` | 14 | 880 ms | 狼吞虎咽：两边飞来代码，嚼得碎屑四溅、冒汗，带残影和换色 |
| `juggle` | 8 | 1040 ms | 两只爪各抛一块代码方块，此起彼落 |
| `juggle-many` | 12 | 1200 ms | 四块代码方块轮流抛接，边抛边扭边笑 |
| `shocked` | 12 | 1090 ms | 抱头大惊，头上冒「!?」，身体乱抖，冒冷汗 |
| `laugh` | 10 | 1060 ms | 抱头大笑，嘴张到半张脸，「哈」字左右轮流冒出 |
| `laugh-point` | 8 | 860 ms | 一手叉腰一手指着你笑 |
| `laugh-roll` | 8 | 880 ms | 笑到仰面躺倒，左右翻滚，双脚朝天乱蹬 |
| `laugh-belly` | 8 | 780 ms | 捧着肚子笑，肚子一鼓一鼓 |
| `alert` | 8 | 1280 ms | 叉腰挥手，头顶感叹号一跳一跳 |
| `devour` | 12 | 1360 ms | 一行代码 `fn(x)=>{` 平移过来，一口吃一个字符 |
| `carry` | 8 | 1120 ms | 双手举着文件箱，小步走 |
| `sleep` | 8 | 3040 ms | 坐着打盹，鼻涕泡随呼吸一大一小，飘 Zzz |
| `wake` | 8 | 1720 ms | 睁眼、站起来伸懒腰打哈欠，最后回到待机第 0 帧（不循环） |
| `walk` | 8 | 1000 ms | 左右脚交替迈步，身体跟着倾斜 |
| `poke-left` | 8 | 900 ms | 左边被戳，往右一歪再弹回来（不循环） |
| `poke-right` | 8 | 900 ms | 右边被戳，往左一歪再弹回来（不循环） |
| `tickle` | 14 | 1140 ms | 被挠痒痒，挤眼乱笑、双手乱挥，鬼畜跳切后回到待机（不循环） |
| `dangle` | 8 | 940 ms | 被拎起来悬空，手脚乱蹬，冒汗、惊叫 |

共 26 段、256 帧；`sheets/` 合计约 38.4 KB。

## 状态映射

| 状态 | 动画 |
|---|---|
| idle / thinking / roam | `idle` / `thinking` / `walk` |
| working | 1 个会话 `eat-code`，2 个 `eat-code-fast`，3 个及以上 `feast` |
| juggling | 1 个子代理 `juggle`，2 个及以上 `juggle-many` |
| error / attention / notification | `shocked` / `laugh` / `alert` |
| sweeping / carrying | `devour` / `carry` |
| sleeping / waking | `sleep` / `wake` |

- 待机池：`idle-look`、`idle-giggle`、`snack` 权重 2，`dance` 权重 1。
- attention 有 0.5 的概率换成 `laugh-point`、`laugh-roll`、`laugh-belly` 之一。
- 反应：点左边 `poke-left`，点右边 `poke-right`，连点 `tickle`，拖动 `dangle`。
- `holds`、`faces`（`front`）、`sounds`（`naiwa`）和 `snack.every` 按设计文档第 4 节写入 `pet.json`。

## 自检

`draw.py` 每次运行都会检查下面这些，`--check` 还会核对磁盘上的文件是否最新：

- 26 段名字齐全；每段 4–16 帧、每帧 60–400 ms、总帧数不超过 400、每段不超过 256 色；alpha 只有 0 和 255，透明像素全是 `(0, 0, 0, 0)`；PNG 读回来和画出来的逐像素相同。
- 待机各帧脚底线都是 y = 60，只有一个连通块，没有离体道具。
- 离体道具离身体（含手持道具）至少 1 个透明像素；每帧最大的 8 连通块正好是身体。
- `wake`、`poke-left`、`poke-right`、`tickle` 不循环，最后一帧和待机第 0 帧的重合度（IoU）不低于 0.9。
- 进食动画张嘴帧的嘴中心在 `snack.mouth` ±1 像素以内。
- `pet.json` 引用的动画都存在，每段动画都被用到。
- 能导入 `app/tool/make_pet_pack.py` 时，按它的规则预算点击框并打印出来。
