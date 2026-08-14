# ☁ 流云材质包打包器

> Minecraft 材质包一键加密打包工具 · 由 **流云** 制作

一个带图形界面的材质包打包器：选中材质包文件夹 → 点一下按钮 → 得到体积更小、且**防止被解包盗用素材**的加密材质包。

基于开源项目 [PackSquash](https://github.com/ComunidadAylas/PackSquash) 构建。

---

## ✨ 它能做什么

| 功能 | 说明 |
|------|------|
| 🖱️ 图形界面 | 双击 exe 自动打开网页界面，不用命令行、不用改配置文件 |
| 🔒 三层防解包 | ZIP 结构混淆 + PNG 贴图混淆 + OGG 音效混淆 |
| 📉 无损压缩 | 材质包体积明显减小，游戏内画质无损 |
| 🎵 音频优化 | FLAC/WAV 自动转高音量 OGG |
| 🧹 JSON 精简 | 压缩成单行并删除多余字段 |

## 🛡️ 防解包原理

普通材质包用解压软件就能把贴图、音效全部提取。这个打包器输出的是**加密包**：

1. **ZIP 结构混淆** — 解压软件直接报错打不开
2. **PNG 混淆** — 即使强行修复 ZIP，提取出的贴图全是损坏的
3. **OGG 混淆** — 音效文件在游戏外无法播放

游戏（Minecraft Java 版）能正常加载使用，但盗素材的人拿不到任何可用资源。

## 📦 仓库内容

```
流云打包器源码备份.zip   ← 源码备份（含 UI 源码 / 加密配置 / 图标 / 使用说明）
```

解压后：

| 文件 | 说明 |
|------|------|
| `ui_server.py` | 完整源码（Python，内置 Web UI） |
| `file.toml` | PackSquash 加密配置 |
| `app_icon.ico` | 程序图标 |
| `使用说明.txt` | 使用教程 |

## 🔧 从源码构建

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon app_icon.ico ui_server.py
```

把生成的 exe 与 [packsquash.exe](https://github.com/ComunidadAylas/PackSquash/releases) 放在同一文件夹即可。

## 👤 作者

**流云** — Minecraft 材质包作者

</br>

<p align="center">如果这个工具帮到了你，欢迎点一个 ⭐ Star</p>
