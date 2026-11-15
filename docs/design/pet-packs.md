# 可导入的宠物包

DSH Go 使用 schema 1 的 `pack.json` 和 PNG 序列帧图。格式、限制及发布参考见 [作者指南](../pets/README.md)，App 行为见 [宠物设计](pets.md)。

## 制作与导入

用 `tooling/pets/build_pet_pack.py` 将素材目录打成确定性 ZIP；`pack.json` 与引用的 PNG 位于顶层或同一层文件夹内。App 导入时只保留清单及引用的 PNG，并通过 Dart 解析、Android 几何约束和 PNG 完整性校验。

设置 → 宠物 → 导入后，包安装到 `<应用支持目录>/pets/user-<id>/`。同 id 再次导入会更新，内置宠物不会被覆盖。读取、替换及删除由 `PetLibrary` 管理。

## 像素奶蛙

奶蛙是可导入包，不注册为内置宠物。它使用 main 的无声状态与交互规则，25 段动画分配见 [奶蛙说明](naiwa-pet.md)。ZIP 包含 1 份清单和 25 张 PNG。

声音原文件、生成资源及来源记录仅保留参考；当前 App 不提供宠物音效播放，奶蛙包不包含音频或音效字段。
