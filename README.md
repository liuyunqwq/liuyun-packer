# 流云材质包打包器

Windows 本地 Minecraft Java 版资源包打包工具，使用 PackSquash 生成带混淆的 ZIP。可给空白源包添加公开定制昵称，并在页面预览 Minecraft 资源包列表里的署名。

[下载 Windows 版](https://github.com/liuyunqwq/liuyun-packer/releases/latest)

1. 下载 `liuyun-packer-v1.2-windows-x64.zip` 并解压整个文件夹，双击 `流云材质包打包器.exe`。
2. 选择能直接看到 `pack.mcmeta` 的源文件夹。保存位置留空会输出到源目录旁，也可以选保存文件夹，或用「另存为 ZIP」自定文件名。
3. 点击「混淆打包」。Minecraft 版本和 Pro 版本用于文件名，Pro 版本也用于定制描述。打包完成后，可把 ZIP 放入对应版本的 `resourcepacks` 文件夹进行检查。

v1.2 支持宽高不超过 8192 像素的 PNG，已验证 1.20.1 Pro 中高 5120 像素的动画贴图。混淆增加提取素材的难度。

## 从源码运行

将 PackSquash v0.4.1 的 `packsquash.exe` 放在 `ui_server.py` 同目录，运行 `python ui_server.py`。本版 EXE 使用 Python 3.13 和 PyInstaller 6.22.3 构建。

```powershell
python -m PyInstaller --onefile --windowed --icon app_icon.ico --name 流云材质包打包器 ui_server.py
```

PackSquash 按 GNU AGPL v3 分发。发布页附有对应源码归档，文件为 `packsquash-v0.4.1-source.tar.gz`。[PackSquash v0.4.1 上游发布页](https://github.com/ComunidadAylas/PackSquash/releases/tag/v0.4.1)
