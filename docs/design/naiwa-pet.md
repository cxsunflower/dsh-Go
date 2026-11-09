# 像素奶蛙宠物（naiwa）

> 2026-11-09 最终范围更新。伙伴小屋那版 Live2D 奶蛙已整体移除：仓库与文档不再包含该模型、导入脚本和小屋角色条目，只保留像素奶蛙（宠物 id `naiwa`）。宠物系统本身的规则见 [pets.md](pets.md)；宠物设置保留原版 Deepy 小鲸鱼、鲸娘，仅新增像素奶蛙，不保留此前的平滑帧图方案及素材。下面第 2～5 节是像素版的格式与兼容契约。

## 0. 结论

- **只加像素奶蛙。** 聊天宠物保留 Deepy 小鲸鱼、鲸娘，仅新增经典黄款像素奶蛙，随 APK 提供；不接入外部模型，也不新增设置页入口。
- **状态协议不改。** `PetMood` 的 12 个 Clawd 状态不动。像素版沿用 27 段动画。
- **只吃思考，不吃输出。** 像素奶蛙精灵帧里画进代码字符飞进嘴里；聊天页再加字符粒子：模型正在流出思考内容时，把新写出来的字（打码后）一个个吃掉；在跑工具时吃运行条上的命令，都没有时吃内置段子。回复正文完整保留，既不吃也不擦。
- **拖到哪擦到哪（只限思考）。** 拖动扫过思考时像橡皮一样立即擦掉路径覆盖的字，拖动半径 12 dp、静止半径 20 dp；收起的思考也能吃，展开时立即恢复思考显示。回复正文不擦。只改当前页面显示，不改对话记录（§7.2）。像素版拖动时趴下，向左拖时整体镜像朝左，松手可留在聊天页，拖回输入框附近恢复站位。
- **六段技能音效。** 全部取自 Valve《Deadlock》的 addon 资源包 `nawa_pak50_dir.vpk`（`citadel_addons/naiwa`），按用户给的名字命名：`hahahahahahaha`（笑声，整段 25.286531 秒）、`gagadilaxia`、`dajiaosei`、`diu`、`andi`、`houla`。五段仍是 PCM16 单声道 22050 Hz；只有笑声因整段 22050 Hz PCM 有 1,115,214 字节、超过 SoundPool 单段 1,000,000 字节上限，由脚本线性插值降到 11025 Hz（557,646 字节），其余不改。不做 EQ、压限、变调或淡入淡出，`@bite`、`@drop` 静音。前台、音效开关、安静模式与通话限制见 §6。
- **动作跟录音同步。** 捧腹大笑持续整段录音 25.286531 秒（`ms` 取整为 25287），其余有录音的一次性反应（戳、叫醒、趴吃、通知）持续该段录音的长度，都不能在动画周期结束时提前回到待机。拖动、点击、切页面等用户操作可中断；静音设置继续生效（§6.2）。
- **来源如实登记。** 像素版与原声的公开再分发许可均未确认，本轮仅本地包。

## 1. 素材调研与授权

### 1.1 形象特征

现有像素版的参考来源是 [Orliss/nailong](https://github.com/Orliss/nailong)，造型要点如下；这份图片、视频参考不能证明获得了角色授权。

| 特征 | 像素化要点 |
|---|---|
| 身形 | 梨形，头和身体连成一体没有脖子，上窄下宽，大肚子 |
| 配色 | 身体奶黄，肚皮浅米色椭圆，手脚灰褐色爪子 |
| 眼睛 | 圆眼，浅绿色眼圈、黑瞳孔；大笑时闭成两道弧线 |
| 嘴 | 平时一条横线；大笑时张到半张脸，深色口腔、上排白牙，有时露舌头 |
| 招牌动作 | 捶头大笑（双手抱头后仰）、抱头震惊（绿眼瞪圆、O 嘴）、叉腰指点（指你大笑）、托腮沉思、张臂平衡、四肢着地笑趴、捧腹大笑、狂笑到抽搐 |
| 隐藏款 | 银河奶龙（深蓝紫身体带星点）、彩虹渐变、粉肤、白肤、橙肤、圣诞帽 |

### 1.2 授权边界

- 参考仓库是 MIT，但它的 `emotes/README.md` 写明「奶龙角色形象版权归其版权方所有，本项目为粉丝向资源合集」。MIT 管不到角色形象本身。
- 现有像素版只参考造型特征，用脚本绘制像素画（`app/tool/pet_src/naiwa/draw.py`），不收录该参考仓库的图片、视频和帧图。六段技能音效的来源记录见 `app/tool/pet_src/naiwa/audio/README.md`。
- `pack.json` 的 `author`、`license`、`source` 如实写明「来自 github.com/cxsunflower，参考网络二创形象重画，非官方」，宠物页页底显示。登记见 `ASSETS.md`。权利人提出要求时替换或移除。

## 2. 现有像素版经典黄款

`naiwa` 使用 64×64 画布、奶黄身体、米色肚皮、绿眼圈和灰爪；身体大小跟随 App 的小/标准/大三档。正面捧腹大笑，拖动时趴着吃字。

技术路线上也比较过：

| 路线 | 结论 |
|---|---|
| 内置宠物包（`app/assets/pets/<id>/`） | 现有像素版采用。App 内和悬浮窗按精灵格式绘制 |
| 插件协议宠物（`PetAdapter`，`plugin-seams.md` §4.2） | 第二期。原生层还没有接宠物协议，`PetAdapter.protocols` 是空集 |
| 网页插件（dsh-pet 式） | 不作为原生聊天页宠物的入口 |
| Flutter 音频插件 | 不用。新增依赖和原生代码；`SoundPool` 几十行就够，和现有原生插件一致 |
| 吃掉正文 | 当前页的绘制遮罩可以擦字；不改消息数据、持久化记录或复制/导出内容（§7.2） |

## 3. 动画与状态（契约）

现有像素版使用下表 27 段，名字一字不差。`loop` 为否的是一次性动画。

触发完整笑声时，正面捧腹大笑动作与该次录音同步保持 25.286531 秒（`ms` 取整为 25287），按需重复动作帧，不重复启动音频；普通状态刷新不能提前替换该动作。拖动、点击或切页面等操作可中断，不要求用户等待笑声结束。

| 动画 | 接到哪里 | loop | 画什么 |
|---|---|---|---|
| `idle` | `states.idle` | 是 | 站着呼吸，肚子起伏，偶尔眨眼 |
| `idle-look` | `idlePool` | 是 | 左右张望 |
| `idle-giggle` | `idlePool` | 是 | 捂嘴偷笑，肩膀抖 |
| `guichu` | `idlePool` | 是 | 鬼畜：同一个动作跳帧复读、抖动、色偏，头顶蹦「哈」 |
| `snack` | `idlePool` | 是 | 从身边抓一个 `;` 塞进嘴里，嚼完打个嗝 |
| `dance` | `idlePool` | 是 | 张臂单脚平衡，左右摇摆 |
| `thinking` | `states.thinking` | 是 | 托腮沉思，眼睛往上看，头顶「?」或「…」 |
| `eat-code` | `states.working`、`tiers.working` ≥1 | 是 | 代码字符从右侧飞进张大的嘴，一口一口嚼 |
| `eat-code-fast` | `tiers.working` ≥2 | 是 | 双手往嘴里塞代码 |
| `feast` | `tiers.working` ≥3 | 是 | 鬼畜速吃：身体抖、碎屑四溅、冒汗 |
| `juggle` | `states.juggling`、`tiers.juggling` ≥1 | 是 | 抛接两个代码块 `{}` `[]` |
| `juggle-many` | `tiers.juggling` ≥2 | 是 | 抛接三四个，边抛边扭 |
| `shocked` | `states.error` | 是 | 抱头震惊：绿眼瞪圆、O 嘴、抖、冒汗、「!?」 |
| `laugh` | `states.attention` | 是 | 正面捧腹大笑，双手抱肚、身体颤动；触发原版笑声时动作持续到录音结束或用户中断 |
| `laugh-point` | `bonus.attention` | 是 | 叉腰指点，指你大笑 |
| `laugh-roll` | `bonus.attention` | 是 | 笑趴：四肢着地或倒地打滚 |
| `laugh-belly` | `bonus.attention` | 是 | 捧腹大笑，肚子一颤一颤 |
| `alert` | `states.notification` | 是 | 叉腰挥手，头顶「!」闪 |
| `devour` | `states.sweeping` | 是 | 一长条代码卷进来，被一口口吃掉（压缩上下文） |
| `carry` | `states.carrying` | 是 | 头顶举着文件箱 |
| `sleep` | `states.sleeping` | 是 | 坐着打瞌睡、鼻涕泡、「Z」 |
| `wake` | `states.waking` | 否 | 伸懒腰、打哈欠 |
| `walk` | `states.roam`、`roam.anim` | 是 | 正面摇摆走路，不镜像 |
| `poke-left` | `reactions.tapLeft` | 否 | 被戳左半边：往右歪、弹回来 |
| `poke-right` | `reactions.tapRight` | 否 | 被戳右半边：往左歪、弹回来 |
| `tickle` | `reactions.tickle` | 否 | 狂笑到抽搐，鬼畜式快速复读（点击链不再触发，数据保留） |
| `prone-eat` | `reactions.drag` | 是 | 被拖动时趴下：肚皮贴地、身体横过来、头朝一侧，张大嘴一口口吃飞来的代码字符（嘴的位置写进 `snack.mouths`） |

绘制约束（打包工具会量，量不过就构建失败）：

- 1 倍像素画，每个像素要么全透明（写成 `0,0,0,0`）要么不透明，不用半透明。
- 待机 `idle` 的每一帧不带脱离身体的道具，`contentBox` 只量到身体。脚底落在同一条脚线上（取众数），身体水平中心稳定。
- 道具（「哈」「Z」「!」、代码字符、碎屑）和身体之间至少隔 1 个透明像素，不并进身体连通块。长时间停留的状态（三档 working、两档 juggling、thinking、alert、sleep）的道具贴近身体，悬浮窗播这些动画时窗口会长到整段的帧格，帧格越大挡住下面 App 的范围越大（pets.md §6.1）。
- 每段 4～16 帧，每帧 60～400 ms，每套总帧数不超过 400；每段颜色不超过 256 种。
- 一次性动画（`wake`、`poke-left`、`poke-right`、`tickle`）末帧回到接近 `idle` 首帧的姿势。

## 4. 源文件格式（契约）

```
app/tool/pet_src/<id>/draw.py        # 生成脚本：只依赖 numpy + Pillow，输出可重复（两次运行字节相同）
app/tool/pet_src/<id>/pet.json       # 由 draw.py 写出
app/tool/pet_src/<id>/sheets/<anim>.png   # 由 draw.py 写出：1 倍单行横条，每帧 w×h
app/tool/pet_src/<id>/README.md      # 方案说明、调色板、重新生成的命令
```

`make_pet_pack.py` 新增源格式 `kind: 'sprite'`，读 `pet.json` 和横条，按现有流程裁切、去重、量命中框，写出 `app/assets/pets/<id>/`。`pet.json`：

```json
{
  "id": "naiwa",
  "w": 64, "h": 64,
  "anims": [
    {"key": "idle", "durs": [160, 120, 120, 160, 120, 120], "loop": true},
    {"key": "wake", "durs": [200, 120, 120, 300], "loop": false}
  ],
  "states": {
    "idle": ["idle"], "thinking": ["thinking"], "working": ["eat-code"], "juggling": ["juggle"],
    "error": ["shocked"], "attention": ["laugh"], "notification": ["alert"], "sweeping": ["devour"],
    "carrying": ["carry"], "sleeping": ["sleep"], "waking": ["wake"], "roam": ["walk"]
  },
  "tiers": {
    "working": [{"min": 3, "anim": "feast"}, {"min": 2, "anim": "eat-code-fast"}, {"min": 1, "anim": "eat-code"}],
    "juggling": [{"min": 2, "anim": "juggle-many"}, {"min": 1, "anim": "juggle"}]
  },
  "idlePool": [
    {"anim": "idle-look", "loops": 2, "weight": 2}, {"anim": "idle-giggle", "loops": 2, "weight": 2},
    {"anim": "guichu", "loops": 2, "weight": 1}, {"anim": "snack", "loops": 1, "weight": 2},
    {"anim": "dance", "loops": 2, "weight": 1}
  ],
  "bonus": {"attention": {"anims": ["laugh-point", "laugh-roll", "laugh-belly"], "chance": 0.5}},
  "reactions": {"tapLeft": "poke-left", "tapRight": "poke-right", "tickle": "tickle", "drag": "prone-eat"},
  "holds": {"attention": 3, "error": 2, "notification": 2, "carrying": 2, "waking": 1, "sweeping": 1},
  "faces": "front",
  "sounds": "naiwa",
  "snack": {
    "mouth": {"x": 33, "y": 31},
    "mouths": {"prone-eat": {"x": 50, "y": 52}},
    "every": {"eat-code": 700, "eat-code-fast": 380, "feast": 200, "devour": 260, "snack": 1500, "prone-eat": 260}
  }
}
```

- `anims[].durs` 的个数等于横条的帧数；横条宽 `w × 帧数`，高 `h`。
- `states`、`tiers`、`bonus`、`reactions` 原样进 `pack.json`，名字必须是 §3 的动画。
- `holds`：一次性或需要停留的状态显示几遍主动画。工具换算成 `timings`：`minDisplay[s] = holds[s] × 主动画一遍时长`；attention、error、carrying 的 `autoReturn` 同值；sweeping 的 `autoReturn` 固定 300000，notification 没有 `autoReturn`；working、thinking 的 `minDisplay` 固定 1000（去抖）；`wakeMs = holds.waking × wake 一遍`。
- `idlePool[].loops`：插播几遍，工具换算成 `ms`。
- `faces` 固定 `front`；`sleep.afterMs` 由工具写 60000。
- `sounds`、`snack` 见 §5，工具校验后原样写进 `pack.json`。

## 5. pack.json 新增字段（契约）

下表字段都可选。Dart 和 Kotlin 的解析器原本就忽略不认识的键，旧版 App 读新包不受影响。

| 字段 | 类型 | 含义 |
|---|---|---|
| `sounds` | 字符串，`^[a-z0-9-]+$` | 音效集 id，对应 `app/assets/pet_sounds/<id>/sounds.json`（§6） |
| `snack.mouth` | `{x, y}`，美术像素，落在画布内 | 嘴的位置：聊天页的代码粒子在这里消失 |
| `snack.every` | `{动画名: 毫秒}`，毫秒 > 0 | 这段动画播放时，每隔多少毫秒飞来一个字符；聊天页实际取 `max(值, 1200)`，避免快节奏动画把字连成一串 |
| `snack.mouths` | `{动画名: {x, y}}`，可选 | 这段动画里嘴的位置，覆盖 `snack.mouth`（趴着吃时嘴更低、偏向一侧）；动画必须在 `snack.every` 里 |
| `roam.free` | 布尔，默认 false | 能被拖到整个页面并待在那里（§7「拖动」）。奶蛙为 true，由 `make_pet_pack.py` 的 PACKS 登记写入 |

Dart（`app/lib/pets/pet_pack.dart`）：

```dart
/// Code snacks flying into the pet's mouth on the chat page (docs/design/naiwa-pet.md §7).
@immutable
class PetSnack {
  const PetSnack({required this.mouth, required this.every});

  /// Where the glyphs vanish, art pixels on the canvas.
  final Offset mouth;

  /// Animation name → ms between glyphs while it plays.
  final Map<String, int> every;

  /// Animation name → where the mouth is in it, over [mouth].
  final Map<String, Offset> mouths;   // 构造参数可选，默认 const {}

  int? everyOf(String anim) => every[anim];
  Offset mouthOf(String anim) => mouths[anim] ?? mouth;
}

// PetPack 另加 `final bool roamFree;`（`roam.free == true`，默认 false）。

// PetPack 增加两个可选字段（构造参数同名，默认 null）：
final String? sounds;
final PetSnack? snack;
```

字段写错（`sounds` 不合规、`mouth` 越界、`every` 里没有一项有效）时当作没有该字段，不让整个包加载失败；`every` 里指向不存在动画的项丢掉。

## 6. 音效（契约）

### 6.1 音效集

```
app/assets/pet_sounds/naiwa/sounds.json
app/assets/pet_sounds/naiwa/*.wav     # PCM16 单声道；笑声 11025 Hz（25.286531 秒），其余 22050 Hz、各不超过 2.5 秒；整套上限 1,500,000 字节
```

六段全部来自 Valve《Deadlock》的一个 addon 资源包 `nawa_pak50_dir_bf496.7z` → `nawa_pak50_dir.vpk`（1,427,634 字节，SHA-256 `093ace9eef9b133e923fd08a3d7c70472f84855df8731e704b3855349483af13`，Valve VPK v2；包内命名空间 `citadel_addons/naiwa`）。包里的 50 条 VO 是空壳，只有 6 个技能音有真实音频。`vsnd_c` 的 KV3 头之后是 MP3 数据段，取出后解码为 PCM16 单声道 22050 Hz WAV 存进 `app/tool/pet_src/naiwa/audio/`：这一步由 `app/tool/pet_src/naiwa/audio/extract_from_pak.py` 做（VPK v2 → 六段 `vsnd_c` → ffmpeg 解码），逐条核对 `sources.json` 里 `vsnd_c` 与 WAV 的 SHA-256，可逐字节复现本目录的输入；只有这一步需要 ffmpeg，构建与测试仍只用 Python 标准库。六段均不做 EQ、压限、响度归一化、变速、变调、淡入淡出或混响；五段逐字节复制，**只有笑声**由脚本用标准库线性插值降到 11025 Hz 以绕开 SoundPool 单段上限，时长保持整段 25.286531 秒。

`app/tool/make_pet_sounds.py` 校验输入 SHA-256 后打包：五段逐字节复制；笑声按固定 WAV 块结构把 `fmt` 与 `data` 写成 11025 Hz 单声道 PCM16（278,784 帧 = 557,568 字节 PCM），保留其余头与 LIST 元数据。重采样算法：输出第 i 帧映射到源区间 `i × (F−1) / (N−1)`，在相邻源样本间做线性插值 `a + (b−a) × 小数部分`，两端分别落在源首帧与末帧，故时长不变。每段解码 PCM 上限 1,000,000 字节，整套上限 1,500,000 字节。来源、pak 条目与全部哈希以 `app/tool/pet_src/naiwa/audio/sources.json` 为准。

`sounds.json`：

```json
{
  "schema": 1,
  "id": "naiwa",
  "name": "奶蛙技能音效",
  "author": "github.com/cxsunflower",
  "license": "Valve《Deadlock》addon 资源，再分发许可未确认，仅本地包；见 ASSETS.md",
  "source": "Deadlock addon nawa_pak50_dir.vpk（citadel_addons/naiwa）; 逐条来源与校验见 app/tool/pet_src/naiwa/audio/sources.json",
  "clips": {
    "hahahahahahaha": {"file": "hahahahahahaha.wav", "gain": 1.0, "vary": 0.0, "ms": 25287},
    "dajiaosei": {"file": "dajiaosei.wav", "gain": 1.0, "vary": 0.0, "ms": 1071},
    "diu": {"file": "diu.wav", "gain": 1.0, "vary": 0.0, "ms": 1071},
    "andi": {"file": "andi.wav", "gain": 1.0, "vary": 0.0, "ms": 1306},
    "gagadilaxia": {"file": "gagadilaxia.wav", "gain": 1.0, "vary": 0.0, "ms": 1384},
    "houla": {"file": "houla.wav", "gain": 1.0, "vary": 0.0, "ms": 2090}
  },
  "cues": {
    "laugh": ["hahahahahahaha"],
    "laugh-point": ["hahahahahahaha"],
    "laugh-roll": ["hahahahahahaha"],
    "laugh-belly": ["hahahahahahaha"],
    "poke-left": ["dajiaosei"],
    "poke-right": ["diu"],
    "wake": ["andi"],
    "prone-eat": ["gagadilaxia"],
    "alert": ["houla"]
  }
}
```

- `clips[].file`：同目录下的 `.wav` 文件名，不含斜杠。通用格式允许 `gain` 0～1、`vary` 0～0.3；本套六段一律显式设置 `gain=1`、`vary=0`，按原速播放。`ms` 是录音自身长度，有录音的一次性反应保持到它结束；缺省视为未知。
- `cues` 的键是 §3 的动画名，外加两个特殊键：`@bite`（一个代码粒子被吃掉）、`@drop`（拖动后松手落地）。值是 clip id 列表，每次随机挑一个，有多个时不连续重复同一个。
- 本套映射上面九个 cue；`@bite`、`@drop` 和其余动作均无声音映射，不生成咀嚼、弹簧、提示音或鬼畜重采样。
- **动作与录音原子化**：一次性反应（`tapLeft`/`tapRight` 与 attention 的捧腹）先问 `PetSoundPlayer.wouldAllow`（纯查询，不占用额度）；这一声会被限流丢掉时，保持当前动画，绝不出现「无声但动作照播」。静音或关音效时同样不切这类反应。其它无音效映射的 cue 与状态动画照旧。

点击反应：单击按左右播 `poke-left`（`dajiaosei`）/`poke-right`（`diu`）；1.1 秒内第 2 下进入 attention 的捧腹大笑，沿用 `_laughing` 机制与 `pack.animFor(PetStateName.attention)`，声音走 `laugh`（`hahahahahahaha`），姿势保持到整段录音结束。链只有这两步：第 2 下开始大笑时计数清空，所以大笑中或之后再点一下不会又凑成一次大笑；笑中的那一下结束录音，之后的单击重新从戳开始（没有第 3 下的挠痒）。第 2 下允许紧随上一声（不受 280 ms 的任意两声间隔限制），但同一 cue 的 1.5 秒限制和每分钟 24 声仍生效；若该声会被限流丢掉，保持当前动画，不切到无声姿势。单击/双击可被拖动、再次点击、长按菜单、切页面、关闭音效或安静模式中断。

六段音效各对应一个交互：戳左 `dajiaosei`、戳右 `diu`、双击大笑 `hahahahahahaha`、把睡着的它点醒 `andi`（`wake` 状态动画）、拖动趴吃 `gagadilaxia`（`prone-eat`）、有待确认的提醒 `houla`（`alert` 状态动画）。`reactions.tickle` 仍留在包里，但不进点击链，也不再有录音。

### 6.2 什么时候响

- **只有聊天页像素奶蛙出声**。`petSoundSetProvider('naiwa')` 供聊天页的像素奶蛙使用；悬浮窗不出声（第二期再议）。
- 条件同时满足才响：宠物包有 `sounds`；「音效」开着；不是安静模式；宠物可见；App 在前台。原生端另外判断：通话或语音通话中不响。不看铃声模式：音效走媒体音量，振动、静音模式下照样响；不想听就关「音效」或调低媒体音量。
- 正在显示的动画换成另一段时，播已映射的原声一次；持续的动画不重复播。通用协议保留 `@bite`、`@drop`，本套未映射，所以吃字和落地均静音。
- **笑声与捧腹动作**：捧腹大笑同步保持整段 25.286531 秒（`ms` 取整 25287）录音长度。动作循环只维持画面，不重新播放音频；普通待机切换不能提前结束。其余有录音的一次性反应按各自 `ms` 保持，规则相同。拖动、点击、切页面等用户操作可中断，关闭音效或开启安静模式仍立即停止声音。
- **动态设置约束**：原声服从 `pet.sound` 与 `pet.quiet`。用户关闭音效或打开安静模式后停止当前原声；异步加载完成后、实际播放前须重读设置，旧请求不能晚到发声。离开页面也停止原声。
- 通用限流（`PetSoundPlayer`）：任意两声至少隔 280 ms；同一个提示音至少隔 1.5 秒，`@bite` 至少隔 1.2 秒；每分钟最多 24 声，`@bite` 不计入这个数。超出的直接丢掉，不排队；本套 `@bite` 未映射，不产生播放请求。

### 6.3 Dart（`app/lib/pets/pet_sounds.dart`）

```dart
@immutable
class PetClip {
  const PetClip({required this.id, required this.file, this.gain = 1, this.vary = 0.1});
  final String id;
  final String file;
  final double gain;
  final double vary;
}

/// Special cues besides animation names.
abstract final class PetCues {
  static const bite = '@bite';
  static const drop = '@drop';
}

@immutable
class PetSoundSet {
  // id、name、author、license、source、clips（id → PetClip）、cues（键 → clip id 列表）
  static const schema = 1;
  static String folder(String id) => 'assets/pet_sounds/$id';
  String assetOf(PetClip clip);           // '${folder(id)}/${clip.file}'
  List<PetClip> cue(String key);          // 未知键返回空表
  factory PetSoundSet.parse(Map<String, Object?> json);   // 格式错误抛 FormatException
  static Future<PetSoundSet> load(String id, [AssetBundle? bundle]);
}

/// Plays cues through the native SoundPool (`dsh/pet_sound`), within §6.2's limits.
class PetSoundPlayer {
  PetSoundPlayer({MethodChannel? channel, DateTime Function()? clock, math.Random? random, bool Function()? appVisible});
  static const channelName = 'dsh/pet_sound';
  static const minGap = Duration(milliseconds: 280);
  static const sameCueGap = Duration(milliseconds: 1500);
  static const biteGap = Duration(milliseconds: 1200);
  static const perMinute = 24;   // @bite 不计入
  Future<void> prepare(PetSoundSet set);          // 同一套只加载一次
  Future<bool> cue(PetSoundSet set, String key, {double gain = 1});  // 返回是否发出了播放请求
  Future<void> release();
}

final petSoundSetProvider = FutureProvider.family<PetSoundSet, String>((ref, id) => PetSoundSet.load(id));
final petSoundPlayerProvider = Provider<PetSoundPlayer>(...);   // ref.onDispose 时 release
```

`PetPrefs` 增加 `sound`（默认 true，键 `pet.sound`）和 `PetPrefsController.setSound(bool)`。音效开关、安静模式、宠物包有无 `sounds` 由聊天页判断；`PetSoundPlayer` 只管前台判断、限流、挑选和变调。

### 6.4 原生通道 `dsh/pet_sound`（Kotlin `pet/PetSoundPlugin.kt`）

| 方法 | 参数 | 返回 | 说明 |
|---|---|---|---|
| `load` | `{assets: List<String>}` | null | 逐个载入 `SoundPool`；已载入的跳过 |
| `play` | `{asset: String, volume: double, rate: double}` | bool | 真正开始播放才返回 true；没载入完、通话中、音量为 0 时返回 false |
| `release` | 无 | null | 释放 `SoundPool` |

- 资源路径必须以 `assets/pet_sounds/` 开头、以 `.wav` 结尾，不含 `..` 和反斜杠；不合规返回错误码 `bad_asset`，参数类型不对返回 `bad_args`。
- `volume` 夹在 0～1，`rate` 夹在 0.5～2（`SoundPool` 的范围）。
- `AudioAttributes`：`USAGE_GAME`、`CONTENT_TYPE_SONIFICATION`，跟媒体音量走；最多 4 路同时播放。
- 判断逻辑放在纯 Kotlin 的 `PetSoundRules` 里，JVM 单测覆盖。

## 7. 吃模型的输出（跑过去吃）

`app/lib/ui/pets/pet_snack.dart` 画字，`pet_stage.dart` 让宠物跑到正在输出的思考那边、慢慢地一口一口吃；都在聊天页宠物层里，不吃触摸。

- **何时吃**：当前动画在 `snack.every` 里（三档 working、devour、snack），且宠物可见、没被拖着、系统没关动画。思考（thinking）状态下，如果正在流出的是回复的思考内容，带 `snack` 的宠物改播 working 第一档的动画（奶蛙是 `eat-code`），照样吃；还没出字时照旧播 thinking。起飞间隔取 `snack.every` 与 1200 ms 的较大值（本套为 1200 ms 一口），同时在飞的字符最多 3 个；字形飞行本身仍为 700～1000 ms 的抛物线，能看清一个再吃下一个。
- **吃什么**，按顺序取第一个有的：
  1. **模型的思考内容**：正在看的对话里 `AssistantChatItem.streaming` 为真的那条回复的 `reasoning`，按 `<id>/reasoning` 另算一份。**回复正文不算食物**，无论是否已经开始输出：正文既不吃也不擦，完整保留。这条回复之后若已有用户消息或正在跑、等批准的工具调用，就不算（改吃命令）。只吃开始吃之后**新写出来的字**，不循环；积压超过 48 个字时直接跳到最新的 48 个，不追旧字。整段思考先过 `maskSecrets`（线性扫描，私钥块、长令牌可能从很前面开始），再取末尾 256 个字；最后一个还没写完的词（后面还没出现空白或非 ASCII）先不吃，免得密钥写到一半、还没被认出来就把前缀吃掉。
  2. **运行条上的命令**：`runActivityOf` 的 `detail` 且 `detailIsCode` 为真（例如 `flutter test test/auth`），先过 `maskSecrets`，循环吃。
  3. **内置 ASCII 段子**（`git push -f`、`rm -rf node_modules`、`while (true) {}`、`NaN`、`undefined`、`404` 等），循环吃。
  空白、组合符号、零宽字符和表情符号（代理对）跳过，中文照吃。只画在屏幕上，不存、不发、不打日志。
- **跑过去**：思考区（`ThinkingPill` 的整块：摘要行加正文槽）在思考流式输出时向宠物层上报自己在屏幕上的矩形，像 `PetAvoid` 一样。回复正文不再上报食物矩形。状态不是 idle、这个状态自己的动画在 `snack.every` 里（待机插播的 `snack` 不跑）、吃的是这段思考、并且它有一部分在屏幕上（站位上方、页面之内）时，宠物沿当前站位**跑**到思考块下方：
  - 用 `walk` 动画，速度 72 逻辑像素/秒（游走的 2.5 倍），按方向翻转的规则同游走；
  - 目标点在回复可见部分的水平范围内随机取，离当前位置至少 24 逻辑像素，夹在站位范围内并避开禁区（`_clear`）；
  - 跑到后吃；之后每 6～9 秒换一个目标点再跑，像在追着字吃。列表滚动、正在拖动或输入框弹出层打开时不换目标点，已在跑的跑完；
  - 回复停止输出、不再可见，或者动画不再是吃的动画时，停止追字、停在原地；中间来的大笑、出错、等你确认都就地播。等状态回到 idle 后 1.2 秒，按游走速度走回原来的位置；系统关了动画或宠物看不见时直接回到原位。
  - 被拖动就停止追字；放下的位置成为新的原位，不再走回去。放下时还在吃，就先在放下的地方吃 6～9 秒再跑。
- **从哪飞到哪**：
  - 吃思考时：字从思考块底部一带起飞（可见部分的底边往上 36 逻辑像素内），横向在嘴的 ±48 逻辑像素内，落进嘴里；
  - 吃命令或段子时：起点在宠物脚下胶囊上沿一带、避开宠物身体。
  终点是 `snack.mouth` 换算到屏幕上的位置。抛物线飞行 700～1000 ms。
- **像素一致**：ASCII 用内置的 5×7 像素字体；中文等其他字符用 App 字体画进 9×9 的小图，按覆盖度取阈值成整点（`ColorFilter.matrix`），最多缓存 256 个。字的每个点和宠物的美术像素一样大（同一个缩放倍数 `k`），位置按美术像素取整，以每秒 12 步跳着走，配色取代码高亮的几种颜色，外加 1 像素深色描边，深浅主题都看得清。
- **吃到嘴里**：字符消失，掉 2～3 粒碎屑，300 ms 内落下淡出；本套 `@bite` 无声音映射。
- **省电**：只在有字符在飞时以每秒 12 步重绘，其余时间不重绘；整层在 `RepaintBoundary` 里。

### 7.1 拖动：整个聊天页都能去

下述自由拖动规则仅用于聊天页像素奶蛙；Deepy 小鲸鱼和鲸娘保持原有拖动规则。`prone-eat` 趴吃姿势描述像素帧动画；不擦聊天文字。

- **拖动时**：像素奶蛙播 `reactions.drag`（`prone-eat`，趴着吃），可中断正在持续的捧腹大笑。脚点跟着手指走，整个聊天页舞台都能去，身体整个留在舞台内。
- **朝向**：奶蛙的趴吃美术嘴在右侧，`pack.json` 的 `drag.mirror` 为 true。向左拖时整体按 `anchorX` 镜像（美术与 `snack.mouthOf('prone-eat')` 一起镜像，`2 * anchorX - mouth.x`），向右拖保持原朝向。方向以拖动起点为准，越过 2 逻辑像素才换，手指小幅抖动不会反复翻转。其它宠物没有该字段，行为不变。
- **边拖边吃**：字符按 `snack.every['prone-eat']` 与 1200 ms 的较大值起飞（本套 1200 ms 一口），起点在嘴前方一带（嘴朝的那一侧，36 逻辑像素以内），终点是 `snack.mouthOf('prone-eat')`；吃什么同上（思考 > 命令 > 段子），正文不可吃。被拖动时不追字、不游走。拖动扫过仍按 §7.2 的 12 dp 立即擦除，不等待这个出字节拍。
- **松手**：脚点离当前站位的上沿不到 32 逻辑像素、并且横向在站位范围内，就回到站位，按原规则吸附并存位置；否则待在松手的地方（自由位置，只在本次运行有效，不存）。
- **在自由位置上**：照常播各状态的动画、冒气泡、睡觉、点按反应；不游走、不追字（回复的字照样从回复底部飞过来吃）。页面尺寸变化、键盘弹出时，位置夹回舞台内。再拖回站位附近就回到站位；换宠物、藏起来再出现时回到站位。
- 命中框和气泡都跟着宠物当前的位置。系统关了动画时照样能拖能放，只是不飞字。
- 这是对 pets.md「不全屏游走、不挡正文」的有意例外：宠物自己不会去别处，只会待在你放下它的地方。

### 7.2 快速擦字与收起的思考

- **擦除先发生，粒子只作反馈。** 拖动时按嘴部前后位置之间的路径擦除覆盖的可见字形，快速扫过也不能只处理最后一个点。拖动半径为 12 dp，静止进食半径为 20 dp。一次可擦多个字，粒子数量有限，不等待飞行结束或 260 ms 的进食间隔，不逐字播放音效。
- **展开的思考**按可见字形擦除；拖过多个内容块时分别处理。**回复正文不可擦。** 滚动裁切外的文字不算命中，消息操作按钮和翻译工具不属于食物。已完成的思考也能吃。
- **收起的思考**不要求先展开，擦到摘要行也能产生吃字反馈。展开思考时立即清除该思考的擦除遮罩，恢复完整显示；已展开时擦掉的思考在收起后再次展开也恢复。不写回 `AssistantChatItem.reasoning`，不删除隐藏正文。
- **保留记录与布局。** 擦除不改源文本、消息记录、复制/导出内容或布局。展开即恢复思考。正文没有被遮罩，从未改动。
- 聚焦回归入口：`app/test/pets/pet_edible_test.dart`、`app/test/pets/pet_collapsed_reasoning_test.dart`。静态对照不等于真机手感验收。

## 8. 设置与文案

- 宠物设置的选择卡片缩小：每行最多 4 个，容器最大宽度 400；窄屏和大字体减少列数，名字允许两行。预览尺寸独立于聊天页的实际大小，避免大宠物把设置卡片撑大。保留原版「Deepy 小鲸鱼」「鲸娘」，仅新增像素「奶蛙」，另有「不显示」；不新增设置页小屋入口。小屋继续从聊天顶部主机栏 → 切换主机面板 → 伙伴小屋进入。
- 宠物页在当前宠物包有 `sounds` 时多一行「音效」开关（设置搜索可搜到），副标题一行。
- 选中奶蛙系列时，宠物页页底写明形象来源和「非官方」，不再写「来自 DSH-TUI」。
- 文案守 pets.md §8 的规矩：不写解释段落，不加感叹号，不用表情符号。

## 9. 本次实现的文件分工

| 负责 | 文件 |
|---|---|
| 像素奶蛙美术 | `app/tool/pet_src/naiwa/` |
| 打包工具 | `app/tool/make_pet_pack.py`、`app/tool/test_make_pet_pack.py`、`app/pubspec.yaml`（资源声明）、`docs/design/pets.md`（§3 字段） |
| 音效 | `app/tool/pet_src/naiwa/audio/`（提取脚本、输入 WAV、`sources.json`）、`app/tool/make_pet_sounds.py`、`app/tool/test_make_pet_sounds.py`、`app/assets/pet_sounds/naiwa/` |
| Dart 数据层 | `app/lib/pets/pet_pack.dart`、`app/lib/pets/pet_sounds.dart`、`app/lib/pets/pet_prefs.dart`、`app/test/pets/support.dart`、`app/test/pets/pet_pack_test.dart`、`app/test/pets/pet_sounds_test.dart` |
| Dart 界面 | `app/lib/ui/pets/pet_stage.dart`、`app/lib/ui/pets/pet_snack.dart`、`app/lib/ui/pets/pixel_font.dart`、`app/lib/ui/pets/pet_perch.dart`（`PetFood`）、`app/lib/ui/chat/widgets/thinking_pill.dart`（思考区是唯一的食物来源）、`app/lib/ui/pets/pet_picker.dart`、`app/lib/ui/pets/pet_settings_page.dart`、`app/lib/ui/settings/index/spots.dart`、`app/lib/l10n/parts/bots_*.arb` 及生成物、`app/test/pets/pet_snack_test.dart`、`app/test/pets/pet_reaction_sound_test.dart` |
| Kotlin | `pet/PetSoundPlugin.kt`、`MainActivity.kt`（注册一行）、`PetSoundRulesTest.kt`、`PetPackTest.kt` |
| 汇总 | `ASSETS.md`、`docs/guide/*/06-pets.md`、构建 `app/assets/pets/naiwa*/` |

## 10. 验证

- Python：`python app/tool/test_make_pet_pack.py`、`python app/tool/test_make_pet_sounds.py`；`python app/tool/make_pet_pack.py --only <id>` 构建并生成预览图。
- 音效输入（需要 ffmpeg，仅重新提取时跑）：`python app/tool/pet_src/naiwa/audio/extract_from_pak.py <nawa_pak50_dir.vpk> --check` 核验六段能从 pak 逐字节复现；去掉 `--check` 就地重写输入 WAV。
- Flutter：`(cd app && flutter analyze && flutter test test/pets)`。
- Kotlin：`./gradlew :app:testX64DebugUnitTest --tests '*pet.*'`；`PetFramesTest` 会自动遍历新包的每段动画。
- 文案和指南：`python app/tool/l10n_merge.py --check`、`python app/tool/guide_sync.py --check`。
- 真机：听一遍六段音效的音量和时机，尤其确认整段 25.2865 秒笑声在当前设备上不被 SoundPool 截断；确认振动模式下照样响、跟随媒体音量、通话中不响；确认单击/双击/笑中点击/点醒睡着的它与限流期内连点不出现「无声动作」，以及有录音的反应保持到录音结束；确认慢速吃字（1200 ms 一口、最多 3 个在飞）仍会跑到思考块旁并落在视野内；左拖时镜像、松手恢复；吃字粒子在 dpr 2.75 下像素清楚。这些均需真机验证，桌面结果不算。

## 11. 第二期与不做

- **第二期**：悬浮窗音效；插件协议宠物（`PetAdapter`）；更多隐藏款配色（彩虹、粉肤）。
- **不做**：修改对话记录来实现吃字；宠物主动调用模型；后台出声；将未确认再分发许可的原声用于公开发布。
