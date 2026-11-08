# 可安装宠物包：现行实现与早期设计

> 2026-11-09。早期设计稿（自带安装器、digest 校验、`<support>/pets/<id>/pack` 布局、覆盖同名内置 id）没有进入 `main`；现在生效的是 `main` 上「导入自己的宠物包」的实现，权威说明见 [pets.md](pets.md) §3.6。本文件只留索引，避免和实现脱节。

## 1. 包格式

一个 schema 1 的宠物包 zip：`pack.json` 在 zip 顶层，或放在 zip 里唯一的那个文件夹中；序列帧 PNG 由 `pack.json` 引用，平铺在图集里。安装时只保留 `pack.json` 和它引用的序列帧图，其余文件丢掉；包内不允许可执行文件。生成用 `tooling/pets/build_pet_pack.py`（确定性 zip），校验细节见 [pets.md](pets.md) §3.6。

## 2. 校验与上限

`PetPack.parse`（与内置宠物同一套解析）→ 悬浮窗更严的解析（`PetPack.kt`）→ 路径、PNG 完整性、帧边界、尺寸与数量上限。没有 digest、签名或发布地址校验：只从本机文件选择器选中的 zip 安装。全部规则见 [pets.md](pets.md) §3.6。

## 3. 存储与生命周期

```
<应用支持目录>/pets/user-<id>/      # 生效中的包（Android 上即 files/pets/user-<id>/）
```

`pack.json` 的 `id` 改写成 `user-` 前缀的文件夹名；同名再导入是覆盖同一只。安装、删除都用改名交换，中断留下的 `.staging-*` / `.old-*` / `.trash-*` 在下次列出或读取前收拾。内置 id（Deepy、鲸娘、奶蛙）永不被覆盖。

## 4. 读取路径

- Dart：`app/lib/pets/pet_library.dart`（导入/删除/列出），`petPackProvider` 对 `user-` id 从安装目录读，其余从 APK 资产读。
- 原生悬浮窗：`PetSprites.kt` 的 `sourceFor` 先看安装目录 `files/pets/<id>`，没有再回退到 APK 资产；目录是固定的，不需要 Dart 下发。
- 音效：安装包的音效还没接上（`app/lib/pets/pet_sounds.dart` 只读 `assets/pet_sounds/<id>/`），宠物页的「音效」开关只对内置音效集生效。

## 5. 本期不做

安装包的音效、digest/签名与发布 URL、自动更新与回滚 UI、宠物市场、覆盖内置包。
