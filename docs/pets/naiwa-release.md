像素奶蛙 1.1.1 是供 DSH Go 导入的无声像素宠物包，共 24 段动画、861 帧。本次更新替换此前的 251 帧版本，同 ID 再次导入即可更新。

## 更新内容

- 完成状态改为 `celebrate`：轻跃、“啦”口型与 ✅，播放一遍后返回当前状态。三连点播放 `laugh-roll`，先捧腹大笑 1440 ms，再打滚、起身，共 2940 ms。
- 工作三档改为单爪敲键、双爪交替和快速打字，资源名为 `typing`、`typing-both`、`typing-fast`；击键与键盘亮键、上浮字符同步。
- 子代理使用 `terminal` / `terminals` 终端小图标；上下文压缩使用 `eat-paper`，持续吞入下端带卷边的长纸；拖动趴行使用 `crawl`。
- 优化全部动作的衔接、呼吸、手臂、脚掌与描边，减少轮廓逐点跳变、手掌漏黄点和双线；保留趴行接缝。图集每帧保留透明边距，隔开相邻帧。
- 保留导入时的抱箱搬运 `carrying`、六连点的鼓腮跺脚 `annoyed` 和四种待机小动作，覆盖 main 的现有状态与交互入口。
- 中英文 README 按状态展示全部动作，更新完成后回到待机的演示和完整 861 帧大图。
- 声音资源完整保留参考，宠物继续按无声方式设计；发布 ZIP 只包含清单与 24 张 PNG。

## 下载与导入

下载下方附件 **pixel-naiwa.zip**，在 **设置 → 宠物 → 导入** 中选择它，再选中「像素奶蛙」。同 ID 再次导入会更新已有宠物。

`SHA256SUMS` 用于校验下载文件；GitHub 自动生成的 Source code 压缩包是仓库源码快照。

## English

Pixel Naiwa 1.1.1 is a silent pet pack for DSH Go with 24 animations and 861 frames. This update replaces the earlier 251-frame build; importing the same pet ID updates the installed pack.

- Completion now plays `celebrate`: a small hop, a “La” mouth shape and a check mark, followed by a return to the current state. Three taps play `laugh-roll`: 1440 ms of belly laughter followed by rolling and standing up, for 2940 ms in total.
- Three work tiers use `typing`, `typing-both` and `typing-fast`, with one paw, alternating paws and rapid typing. Key flashes and rising characters follow the keystrokes.
- Subagents use the `terminal` / `terminals` icons. Context compaction uses `eat-paper`, continuously feeding a long sheet with a curled lower edge. Dragging uses the `crawl` animation.
- Refines transitions, breathing, arms, feet and outlines to reduce stray pixels, yellow leaks around palms and doubled lines. Keeps the crawl's body seam and adds transparent margins between atlas cells.
- Keeps parcel carrying during imports, the six-tap puff-and-stamp reaction, and all four idle variations, covering main's existing states and interactions.
- Updates all state previews in both READMEs, the completion-to-idle sequence and the full 861-frame sheet.
- Retains sound resources for reference. The downloadable pack remains silent and contains only the manifest and 24 PNG sheets.

Download **pixel-naiwa.zip**, import it under **Settings → Pets → Import**, then select Pixel Naiwa. Importing the same ID updates the existing pet. Use `SHA256SUMS` to verify the download.
