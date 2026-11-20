# -*- coding: utf-8 -*-
"""流云材质包打包器 — 图形界面服务器
双击 exe 即可使用，无需安装 Python / 命令行。
基于 PackSquash，作者：流云
"""
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import stat
import threading
import traceback
import unicodedata
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from windows_picker import pick_path

# ---------------- 路径定位（兼容 PyInstaller 冻结） ----------------
if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent
    _APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "流云打包器"
    _APPDATA.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE = _APPDATA / "ui_config.json"
else:
    HERE = Path(__file__).resolve().parent
    CONFIG_FILE = HERE / "ui_config.json"

EXE = HERE / "packsquash.exe"
# PackSquash 默认上限；1.20.1 的动画长图高度可达 5120。
MAX_PNG_SIDE = 8192
DEFAULT_ITERATIONS = 2

# ---------------- 使用条款（先写入临时副本，再由 force_include 打包） ----------------
NOTICE_FILE = HERE / "资源包使用条款-README.txt"

DEFAULT_NOTICE = """============================================================
                    流云 PVP 材质包 · 使用条款
============================================================

作者：流云好犹豫
B站 ：https://space.bilibili.com/287723143

谢谢支持这份作品。麻烦花一分钟看看
下面几行 —— 其实就一句话：自己怎么玩都行，别往外传就好。

------------------------------------------------------------
【 你可以做的事 】
------------------------------------------------------------
1. 在你自己或你完全控制的设备上使用。
2. 按自己的喜好改一改，自己玩。
3. 用它录视频、开直播 —— 很欢迎。方便的话在简介里标注一下
   作品名称，或者有人问起时说一句出处。
4. 把「获取本作品的网址」分享给别人，让更多人从正规渠道拿到。

------------------------------------------------------------
【 希望你不要做的事 】
------------------------------------------------------------
1. 把本材质包的文件、下载链接转发给别人（网盘、群文件、社交
   平台、线下拷贝等都算）。
2. 把包里的内容拆出来，整合进你自己的作品再发布。
3. 拿它做商业用途 —— 售卖、二次分发等。
4. 破解、反编译本包，或提取其中的素材另作他用。

------------------------------------------------------------
【 关于本包的技术保护 】
------------------------------------------------------------
本包做了结构保护处理。用常规解压软件打开时，可能会提示「文件
已损坏」；也可能虽然能提取出文件，但内容无法使用 —— 这都属于
正常的保护效果，不是文件出了问题。

直接放进 .minecraft/resourcepacks 文件夹即可正常使用。不需要
解压，也不用尝试修复。

------------------------------------------------------------
【 需要其他用途？ 】
------------------------------------------------------------
上面「希望你不要做的事」里的情况，或者有其他用途，欢迎先来
问一声（B站私信就行）。很多事聊一聊就能解决，没必要绕开作者。

更新与定制范围以购买时的商品说明为准。遇到未经授权的传播，
作者保留维护作品权益的权利。

                                    流云好犹豫  © 2026
============================================================"""


def load_notice():
    """优先读同目录的条款文件（改文案不用重新打包），读不到就用内置的"""
    try:
        text = NOTICE_FILE.read_text("utf-8").strip()
        if text:
            return text
    except Exception:
        pass
    return DEFAULT_NOTICE.strip()


def prepare_notice(pack_dir, custom="", protected=False, add_notice=True):
    """只处理临时副本。已有说明保留，署名只写公开昵称。"""
    notice = pack_dir / "README.txt"
    if add_notice and not notice.exists():
        notice.write_text(load_notice() if protected else STANDARD_NOTICE, "utf-8")
    if custom:
        (pack_dir / "专属定制.txt").write_text(
            f"流云 · 专属定制\n\n定制者：{custom}\n"
            "本资源包仅供定制者本人使用，请勿转发、再分发或转售。\n"
            "署名可辅助核对交付来源，不能单独证明传播责任。\n", "utf-8")


STANDARD_NOTICE = (
    "流云 · 资源包使用说明\n\n请将 ZIP 放入 Minecraft 的 resourcepacks 文件夹。\n"
    "欢迎截图、录屏、直播和分享官方获取入口。请勿转发完整包、转售或拆出素材再发布。\n"
    "更新与定制范围以购买时的商品说明为准。\n"
)

ZW_SET = frozenset(("\u200b", "\u200c", "\u200d", "\u2060"))


# ---- 宽度估算：资源包列表只给 2 行、单行约 157px；超宽会折行，折出去的第 3 行会被吞掉 ----
DESC_MAX_PX = 157
_NARROW_PX = frozenset("il.,:;'|!")             # 约 2px（含 1px 字距）
_MED_PX = frozenset("tf()[]{}*\"`<>=/\\-+")     # 约 5px


def text_width_px(s):
    """估算可见部分的显示宽度（像素）—— 零宽指纹按 0 计

    § 色码不占宽；零宽字符（藏指纹用）不占宽；ASCII 按其 advance 近似；
    中日韩全角按 9px（8 + 1 字距）。
    用途：判断署名拼上去之后，会不会把可见文字挤到第 3 行去。
    """
    total = 0
    skip = False
    for ch in s:
        if skip:                     # § 后面那个色码字母
            skip = False
            continue
        if ch == "§":
            skip = True
            continue
        if ch in ZW_SET:             # 零宽指纹：游戏里不占可见宽度
            continue
        if ch == " ":
            total += 4
        elif ord(ch) < 128:
            total += 2 if ch in _NARROW_PX else (5 if ch in _MED_PX else 6)
        else:
            total += 9
    return total


def build_custom_desc(custom, pro_version=""):
    suffix = "定制"
    shortened = text_width_px(custom + suffix) > DESC_MAX_PX
    if shortened:
        while text_width_px(custom + "…" + suffix) > DESC_MAX_PX:
            custom = custom[:-1]
        custom += "…"
    title = f"§b流云 Pro {pro_version}" if pro_version else "§b流云 · 专属定制"
    return title + "\n§e" + custom + suffix, shortened


# Match quoted strings before comments so URLs and escaped quotes are preserved.
JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\r\n]*|/\*[\s\S]*?\*/')


def read_pack_metadata(path):
    text = path.read_text("utf-8-sig")
    text = JSONC_TOKEN.sub(lambda m: " " if m[0].startswith("/") else m[0], text)
    try:
        meta = json.loads(text)
    except ValueError as exc:
        raise ValueError("无法解析 pack.mcmeta，请检查 JSON 格式（支持注释）") from exc
    if not isinstance(meta, dict) or not isinstance(meta.get("pack"), dict):
        raise ValueError("pack.mcmeta 缺少有效的 pack 对象")
    return meta


def prepare_metadata(pack_dir, opts):
    path = pack_dir / "pack.mcmeta"
    custom = opts.get("custom_name", "").strip()
    delivery = opts.get("delivery_identity", False)
    if not delivery and (pack_dir / "专属定制.txt").exists():
        raise ValueError("源包已有专属定制说明，请选择未署名的源文件夹，避免发出上一份定制信息")
    meta = read_pack_metadata(path)
    if not delivery and "liuyun_authorization" in meta:
        raise ValueError("源包已有专属授权标记，请选择未署名的源文件夹")
    pack = meta["pack"]
    if "pack_format" not in pack and {"min_format", "max_format"} <= pack.keys():
        raise ValueError("当前 PackSquash 不能混淆只含 min_format/max_format 的资源包；源包未改动，也没有生成普通 ZIP")
    if "description" not in pack:
        raise ValueError("pack.mcmeta 缺少资源包描述")
    if custom:
        pack["description"], shortened = build_custom_desc(custom, opts.get("pro_version", ""))
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), "utf-8")
        if shortened:
            with state_lock:
                state["log"].append("[定制] 列表署名已缩短，完整昵称保存在专属定制.txt")


def check_copy_entries(folder, names):
    for name in names:
        info = (Path(folder) / name).lstat()
        if ((getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
                or stat.S_ISLNK(info.st_mode)):
            raise ValueError(f"源包含符号链接或重解析点：{name}。请复制实际文件再打包")
    return []


def suggest_filename(source, opts):
    mc, pro = opts.get("minecraft_version", ""), opts.get("pro_version", "")
    if mc and pro:
        stem = f"[{mc}]流云PVP材质包-Pro-{pro}"
    else:
        stem = source.name[:100] + (f"-MC-{mc}" if mc else "") + (f"-Pro-{pro}" if pro else "")
    custom = opts.get("custom_name", "").strip()
    suffix = "-保护"
    if custom:
        label = re.sub(r'[<>:"/\\|?*]', "_", custom).strip(" .")[:36].rstrip(" .")
        suffix = "-" + (label or "专属") + "定制-保护"
    return stem + suffix + ".zip"


def validate_labels(opts):
    if opts.get("order_id"):
        raise ValueError("图形界面不接收订单号；需要私有台账时请使用本地交付工具")
    custom = opts.get("custom_name", "")
    if not isinstance(custom, str) or len(custom) > 128:
        raise ValueError("定制署名须为不超过 128 个字符的公开昵称")
    if any(unicodedata.category(ch)[0] == "C" or ch in "§\u2028\u2029" for ch in custom):
        raise ValueError("定制署名不能包含换行、色码或隐藏字符")
    for key, label in (("minecraft_version", "Minecraft 版本"), ("pro_version", "Pro 版本")):
        value = opts.get(key, "")
        if not isinstance(value, str) or (value and not re.fullmatch(r"[0-9]{1,3}(?:\.[0-9]{1,3}){1,2}", value)):
            raise ValueError(f"{label}请填写数字版本，例如 1.21.11 或 1.0")


# ---------------- 运行状态 ----------------
state = {"running": False, "closing": False, "log": [], "done": False, "exit_code": None, "output": "", "source": ""}
state_lock = threading.Lock()
picker_active = False


def load_cfg():
    try:
        return json.loads(CONFIG_FILE.read_text("utf-8"))
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        CONFIG_FILE.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    except Exception:
        pass


def toml_str(s):
    return json.dumps(s, ensure_ascii=False)


def build_toml(src, out, opts):
    strong = opts.get("preset", "strong") == "strong"
    png_obf = strong and opts.get("png_obfuscation", True)
    ogg_obf = strong and opts.get("ogg_obfuscation", False)
    zip_obf = strong and opts.get("zip_obfuscation", True)
    optifine = opts.get("optifine", True)
    iters = int(opts.get("iterations", DEFAULT_ITERATIONS))
    conformance = "disregard" if zip_obf else "pedantic"

    lines = [
        f"pack_directory = {toml_str(src)}",
        f"output_file_path = {toml_str(out)}",
        "recompress_compressed_files = false",
        f"zip_compression_iterations = {iters}",
        "automatic_minecraft_quirks_detection = true",
        "automatic_asset_types_mask_detection = false",
        f"allow_mods = [{toml_str('OptiFine') if optifine else ''}]",
        "skip_pack_icon = false",
        "validate_pack_metadata_file = true",
        "ignore_system_and_hidden_files = true",
        f"zip_spec_conformance_level = '{conformance}'",
        f"size_increasing_zip_obfuscation = {'true' if zip_obf else 'false'}",
        "percentage_of_zip_structures_tuned_for_obfuscation_discretion = 100" if zip_obf else "",
        "zip_comment = 'Private resource pack. Do not redistribute.'" if
        (opts.get("notice", True) or opts.get("custom_name") or opts.get("delivery_identity")) else "",
        "never_store_squash_times = true",
        f"threads = {os.cpu_count() or 4}",
        "spooling_buffers_size = 128",
        "",
        "['**/*?.ogg']",
        "transcode_ogg = false",
        "two_pass_vorbis_optimization_and_validation = true" if ogg_obf else "two_pass_vorbis_optimization_and_validation = false",
        f"ogg_obfuscation = {'true' if ogg_obf else 'false'}",
        "",
        "['**/*.jsonc']",
        "minify_json = false",
        "delete_bloat_keys = false",
        "",
        "['**/*.json']",
        "minify_json = true",
        "delete_bloat_keys = false",
        "",
        "['**/*.png']",
        "image_data_compression_iterations = 0",
        "color_quantization_target = 'none'",
        f"maximum_width_and_height = {MAX_PNG_SIDE}",
        "downsize_if_single_color = false",
        "skip_alpha_optimizations = true",
        f"png_obfuscation = {'true' if png_obf else 'false'}",
        "",
        "['**/*.{fsh,vsh}']",
        "shader_source_transformation_strategy = 'keep_as_is'",
        "",
        # Keep known companion files that the engine's vanilla asset list would omit.
        "['**/*.properties']",
        "force_include = true",
        "['**/*.rpo']",
        "force_include = true",
    ]
    if opts.get("notice", True) or opts.get("delivery_identity"):
        lines += ["['README.txt']", "force_include = true"]
    if opts.get("custom_name", "").strip() or opts.get("delivery_identity"):
        lines += ["['专属定制.txt']", "force_include = true"]
    return "\n".join(l for l in lines if l != "")


def clean_path(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1].strip()
    if "\x00" in value or '"' in value:
        raise ValueError("路径包含无效字符，请从资源管理器重新复制")
    return value


def output_path(source, out, opts):
    out = clean_path(out)
    filename = suggest_filename(source, opts)
    if not out:
        return source.parent / filename, False
    output = Path(out)
    if output.is_dir():
        return output / filename, False
    if out.endswith(("/", "\\")) or output.suffix.lower() != ".zip":
        raise ValueError("保存位置不是现有文件夹。请选择保存文件夹，或用「另存为」指定 ZIP 文件")
    if not output.parent.is_dir():
        raise ValueError("ZIP 的上级文件夹不存在，请重新选择保存位置")
    return output, True


def validate_source(value):
    value = clean_path(value)
    if not value:
        raise ValueError("请先选择材质包源文件夹")
    source = Path(value).resolve()
    if not source.is_dir() and source.is_file():
        raise ValueError("源包需要包含 pack.mcmeta 的文件夹。若手上只有 ZIP，请先解压再选择")
    if not (source / "pack.mcmeta").is_file():
        raise ValueError("所选文件夹没有 pack.mcmeta。请打开到能看见 pack.mcmeta 的那一层")
    return source


def choose_native_path(mode, src, out, opts):
    global picker_active

    def seed(value):
        try:
            return clean_path(value)
        except ValueError:
            return ""

    src, out = seed(src), seed(out)
    current = src if mode == "source" else out
    target = Path(current) if current else None
    folder = target if target and target.is_dir() else target.parent if target else None
    prefer_folder = folder is not None and folder.is_dir()
    if not prefer_folder:
        if mode != "source" and src and Path(src).is_dir():
            folder = Path(src).resolve().parent
        else:
            folder = None
    filename = ""
    if mode == "save":
        if target and not target.is_dir() and target.suffix.lower() == ".zip":
            filename = target.name
        else:
            source = Path(src) if src else Path("流云PVP材质包")
            filename = suggest_filename(source, opts)
    with state_lock:
        if state["running"] or state["closing"] or picker_active:
            raise RuntimeError("已有打包或选择窗口正在进行")
        picker_active = True
    try:
        chosen = pick_path(mode, folder.resolve() if folder else None, filename, prefer_folder=prefer_folder)
        if chosen is None:
            return {"cancelled": True}
        if mode == "source":
            return {"path": str(validate_source(chosen))}
        chosen_path = Path(chosen).resolve()
        if mode == "folder" and not chosen_path.is_dir():
            raise ValueError("请选择现有的保存文件夹")
        if mode == "save" and (chosen_path.suffix.lower() != ".zip" or chosen_path.is_dir() or not chosen_path.parent.is_dir()):
            raise ValueError("请选择有效的 ZIP 文件名和保存文件夹")
        if src and Path(src).is_dir() and chosen_path.is_relative_to(Path(src).resolve()):
            raise ValueError("保存位置不能在源文件夹内，请选择其他位置")
        return {"path": str(chosen_path)}
    finally:
        with state_lock:
            picker_active = False


def validate_job(src, out, opts):
    """在启动线程前校验，避免错误输入留下永远运行中的任务。"""
    if not isinstance(src, str) or not src.strip() or not isinstance(out, str) or not isinstance(opts, dict):
        raise ValueError("打包参数格式不正确")
    source = validate_source(src)
    validate_labels(opts)
    output, _ = output_path(source, out, opts)
    output = output.resolve()
    if output.is_relative_to(source):
        raise ValueError("输出 ZIP 必须放在源文件夹外，避免把输出再次打包")
    if output.is_dir():
        raise ValueError("输出路径是文件夹，请填写其他 ZIP 文件名")
    if not output.parent.is_dir():
        raise ValueError("输出目录不存在，请先选择已有文件夹")
    if opts.get("preset", "strong") not in ("strong", "plain"):
        raise ValueError("请选择有效的保护模式")
    iterations = opts.get("iterations", DEFAULT_ITERATIONS)
    if isinstance(iterations, bool) or not isinstance(iterations, int) or not 1 <= iterations <= 10:
        raise ValueError("压缩力度必须是 1 到 10 的整数")
    for key in ("png_obfuscation", "ogg_obfuscation", "zip_obfuscation", "optifine", "notice", "delivery_identity", "overwrite"):
        if key in opts and not isinstance(opts[key], bool):
            raise ValueError("保护选项必须是勾选状态")
    return source, output


def run_packquash(src, out, opts):
    # 源目录从不写入；失败或关闭时也不需要补救还原。
    with state_lock:
        state.update(running=True, done=False, log=[], exit_code=None, output=out, source=src)
    try:
        source, output = validate_job(src, out, opts)
        custom = opts.get("custom_name", "").strip()
        protected = (opts.get("preset", "strong") == "strong" and
                     (opts.get("png_obfuscation", True) or opts.get("zip_obfuscation", True)
                      or opts.get("ogg_obfuscation", False)))
        with tempfile.TemporaryDirectory(prefix=".liuyun-pack-", dir=output.parent,
                                         ignore_cleanup_errors=True) as temp:
            temp_root = Path(temp)
            staged_source = temp_root / "source"
            shutil.copytree(source, staged_source, ignore=check_copy_entries)
            prepare_metadata(staged_source, opts)
            if opts.get("notice", True) or custom:
                prepare_notice(staged_source, custom, protected, opts.get("notice", True))
            staged_output = temp_root / "output.zip"
            code = run_engine(temp_root, staged_source, staged_output, opts)
            if code != 0:
                with state_lock:
                    if any("Invalid PNG: The texture width or height exceeds the configured maximum size" in line
                           for line in state["log"]):
                        state["log"].append(f"[失败] 有 PNG 宽度或高度超过 {MAX_PNG_SIDE} 像素。请在日志里查看具体文件。")
                    state["exit_code"] = code
                return
            if not staged_output.is_file() or staged_output.stat().st_size == 0:
                raise OSError("打包引擎未生成有效输出")
            # Windows rename 可原子提交新文件，并拒绝覆盖任务期间出现的同名文件。
            if not opts.get("overwrite", True):
                if os.name == "nt":
                    os.rename(staged_output, output)
                elif output.exists():
                    raise FileExistsError("打包期间出现同名文件，已保留原文件")
                else:
                    os.replace(staged_output, output)
            else:
                os.replace(staged_output, output)
            with state_lock:
                state["output"] = str(output)
                state["exit_code"] = 0
                state["log"].append("[完成] 已保存成品；源包未修改")
    except Exception as e:
        with state_lock:
            state["log"].append(f"[失败] {e}")
            state["exit_code"] = -1
    finally:
        with state_lock:
            state["running"] = False
            state["done"] = True


def run_engine(temp_root, staged_source, staged_output, opts):
    options_path = temp_root / "options.toml"
    options_path.write_text(build_toml(str(staged_source), str(staged_output), opts), "utf-8")
    proc = subprocess.Popen(
        [str(EXE), str(options_path)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        cwd=str(HERE), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            with state_lock:
                state["log"].append(line)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait()
        if proc.stdout is not None:
            proc.stdout.close()
    return proc.returncode


def start_job(src, out, opts):
    source, output = validate_job(src, out, opts)
    if not EXE.is_file():
        raise ValueError("找不到 packsquash.exe，请将它放在本程序同目录")
    with state_lock:
        if state["closing"]:
            raise RuntimeError("程序正在退出，请重新打开后再打包")
        if picker_active:
            raise RuntimeError("请先关闭文件选择窗口")
        if state["running"]:
            raise RuntimeError("已有打包任务正在进行中")
        if output.exists() and not opts.get("overwrite"):
            raise FileExistsError(f"输出 ZIP 已存在：{output}")
        state.update(running=True, done=False, log=[], exit_code=None,
                     output=str(output), source=str(source))
    try:
        job_opts = {"overwrite": False, **opts}
        threading.Thread(target=run_packquash, args=(str(source), str(output), job_opts),
                         daemon=False).start()
    except Exception as e:
        with state_lock:
            state.update(running=False, done=True, exit_code=-1, log=[f"[启动失败] {e}"])
        raise
    save_cfg({"last_src": str(source), "last_out": str(output)})
    return str(output)


HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<title>流云材质包打包器</title>
<style>
:root {
  color-scheme: dark;
  --bg: #171c21; --panel: #1e252b; --field: #161b20; --line: #39464f;
  --text: #f0f5f7; --muted: #adbac4; --accent: #39f2f5; --cyan-dark: #093337;
  --yellow: #ffda86; --danger: #ffaba3; --radius: 6px;
  font: 15px/1.55 "Segoe UI", "Microsoft YaHei UI", system-ui, sans-serif;
  background: var(--bg); color: var(--text);
}
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; }
[hidden] { display: none !important; }
button, input { font: inherit; }
button { cursor: pointer; }
button:disabled, input:disabled { cursor: wait; opacity: .65; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 3px; }
.shell { width: min(1120px, calc(100% - 64px)); margin-inline: auto; }
.topbar { background: #14191d; border-bottom: 1px solid var(--line); }
.topbar .shell { min-height: 72px; display: flex; align-items: center; gap: 14px; }
.brand-mark { width: 30px; height: 30px; border: 1px solid #348187; display: grid; place-items: center; background: #1c3035; }
.diamond { width: 9px; height: 9px; background: var(--accent); transform: rotate(45deg); flex: none; }
h1, h2, p { margin: 0; }
h1 { font-size: 20px; font-weight: 740; line-height: 1.3; }
.local { margin-left: auto; color: var(--muted); font-size: 13px; white-space: nowrap; }
.local::before { content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 7px; vertical-align: 2px; background: var(--accent); }
.workspace { display: grid; grid-template-columns: minmax(0, 1.22fr) minmax(0, 1fr); align-items: start; gap: 40px; padding-block: 42px 34px; }
.editor { padding: 25px 0 0; }
h2 { font-size: 23px; font-weight: 710; letter-spacing: .015em; line-height: 1.35; }
.field { display: grid; gap: 7px; min-width: 0; }
.field label { font-weight: 650; }
.field small, .hint { color: var(--muted); font-size: 13px; }
.field small { font-weight: 400; margin-left: 6px; }
.field + .field { margin-top: 16px; }
.form-section { margin-top: 23px; }
.form-section + .form-section { padding-top: 19px; border-top: 1px solid var(--line); }
.row { display: flex; gap: 8px; align-items: center; min-width: 0; }
input { color: var(--text); background: var(--field); border: 1px solid #465560; border-radius: var(--radius); width: 100%; min-width: 0; min-height: 42px; padding: 8px 11px; }
input::placeholder { color: #9daab5; opacity: 1; }
input:focus-visible { outline-offset: 1px; }
.btn { display: inline-flex; justify-content: center; align-items: center; min-height: 40px; padding: 7px 13px; border: 1px solid #4a5a65; border-radius: var(--radius); background: #28333c; color: var(--text); white-space: nowrap; transition: background .15s, border-color .15s; }
.btn:hover { background: #374752; border-color: #81929d; }
.quit { background: transparent; min-height: 36px; }
.version-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 17px; }
.version-row .field { margin: 0; }
.version-note { margin-top: 8px; }
.run { width: 100%; min-height: 49px; margin-top: 23px; display: flex; gap: 11px; align-items: center; justify-content: center; font-size: 16px; font-weight: 760; background: var(--accent); color: #092427; border: 1px solid var(--accent); border-radius: var(--radius); transition: background .15s; }
.run:hover:enabled { background: #9affff; }
.run .diamond { width: 7px; height: 7px; background: currentColor; }
.notice { margin-top: 14px; padding: 10px 12px; border-left: 3px solid var(--accent); background: #172d31; overflow-wrap: anywhere; }
.notice.error { color: var(--danger); border-color: var(--danger); background: #35282a; }
.status-actions { margin-top: 12px; }
.status-actions .btn { border-color: #3b8d94; background: var(--cyan-dark); }
.status-actions .btn:hover { background: #16494d; }
details { margin-top: 13px; color: var(--muted); }
summary { cursor: pointer; width: fit-content; }
#log { font: 13px/1.5 Consolas, "Microsoft YaHei UI", monospace; white-space: pre-wrap; overflow-wrap: anywhere; margin: 10px 0 0; padding: 10px; max-height: 200px; overflow: auto; background: var(--field); }
.progress { height: 3px; margin-top: 9px; overflow: hidden; background: #34424b; }
.progress i { width: 36%; height: 100%; display: block; background: var(--accent); animation: travel 1.4s ease-in-out infinite alternate; }
@keyframes travel { to { transform: translateX(178%); } }
.preview { position: relative; margin: 0; padding: 25px; background: #1b292f; border: 1px solid #4ecdd1; border-radius: var(--radius); }
.preview::before { position: absolute; content: ""; top: -1px; left: 24px; height: 3px; width: 68px; background: var(--accent); }
.preview-heading { display: flex; justify-content: space-between; gap: 12px; align-items: baseline; flex-wrap: wrap; }
.preview-heading h2 { color: var(--accent); }
.preview-label { color: var(--muted); font-size: 13px; margin-top: 22px; margin-bottom: 7px; }
.preview-label.file-label { margin-top: 21px; }
.pack-entry { display: flex; align-items: center; gap: 13px; padding: 13px; min-height: 103px; background: #111a1e; border-left: 2px solid #45c3c9; }
.pack-icon { width: 56px; height: 56px; flex: none; display: grid; place-items: center; border: 1px solid #44878b; background: #214047; }
.pack-icon i { width: 24px; height: 24px; display: block; border: 3px solid #84faff; background: #225058; transform: rotate(45deg); box-shadow: inset 0 0 0 3px #214047; }
.pack-copy { min-width: 0; overflow-wrap: anywhere; }
.pack-title { font-size: 16px; font-weight: 720; color: #96faff; }
.pack-signature { color: var(--yellow); }
.preview-file { display: block; min-height: 43px; padding: 9px 11px; color: var(--text); background: #152127; font: 14px/1.6 Consolas, "Microsoft YaHei UI", monospace; border-radius: 3px; overflow-wrap: anywhere; }
.preview-foot { padding-top: 15px; }
.preview-error { margin-top: 12px; color: var(--danger); }
.compact-source, .compact-file { display: none; }
.footer { border-top: 1px solid var(--line); display: flex; flex-wrap: wrap; gap: 4px 18px; justify-content: space-between; padding-block: 14px 20px; color: var(--muted); font-size: 13px; }
dialog { width: min(560px, calc(100% - 28px)); max-height: min(86dvh, 620px); background: var(--panel); color: var(--text); border: 1px solid #527a82; border-radius: var(--radius); padding: 0; }
dialog::backdrop { background: rgb(7 13 16 / 76%); }
.modal { display: flex; flex-direction: column; gap: 12px; padding: 20px; max-height: min(84dvh, 600px); }
.modal .actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: end; }
.modal .primary { background: var(--accent); color: #092427; border-color: var(--accent); font-weight: 700; }
.modal .primary:hover { background: #9affff; }
.modal .primary:disabled { cursor: default; }
.modal .dialog-text { overflow-wrap: anywhere; }
.location-actions { flex-wrap: wrap; }
.picker-error { color: var(--danger); }
.picker-status { overflow-wrap: anywhere; }
@media (max-width: 890px) { .workspace { gap: 18px; } .editor { padding-top: 19px; } .preview { padding: 19px; } }
@media (max-width: 720px) {
  .shell { width: calc(100% - 28px); }
  .topbar .shell { min-height: 62px; gap: 9px; }
  h1 { font-size: 17px; }
  .workspace { grid-template-columns: minmax(0, 1fr); padding-block: 18px; }
  .editor { padding-top: 4px; }
  .compact-source { display: block; overflow-wrap: anywhere; }
  .compact-file { display: block; margin-top: 15px; }
  .compact-file .preview-file { min-height: 0; margin-top: 4px; }
  .preview .file-label, .preview .preview-file { display: none; }
  .run { margin-top: 14px; }
  input { font-size: 16px; }
}
@media (max-width: 400px) { .local { display: none; } .quit { margin-left: auto; } .preview { padding: 16px; } }
@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
</style>
</head>
<body>
<header class="topbar">
  <div class="shell">
    <span class="brand-mark" aria-hidden="true"><i class="diamond"></i></span>
    <h1>流云材质包打包器</h1>
    <span class="local">本地运行</span>
    <button type="button" class="btn quit" id="quit">退出</button>
  </div>
</header>
<main class="shell workspace">
  <form class="editor" id="pack-form" aria-labelledby="editor-title">
    <h2 id="editor-title">打包设置</h2>
    <div class="form-section">
      <div class="field">
        <label for="src">源文件夹</label>
        <div class="row">
          <input id="src" placeholder="选择包含 pack.mcmeta 的文件夹" aria-required="true" aria-describedby="source-name" spellcheck="false" autocomplete="off">
          <button class="btn" type="button" id="browse-source" aria-label="选择源文件夹">选文件夹</button>
        </div>
        <p class="hint compact-source" id="source-name" hidden></p>
      </div>
      <p id="picker-source" class="picker-status hint" role="status" hidden></p>
      <div class="field">
        <label for="out">保存位置<small>选填</small></label>
        <div class="row">
          <input id="out" placeholder="留空时保存到源文件夹旁，可粘贴路径" spellcheck="false" autocomplete="off">
        </div>
        <div class="row location-actions">
          <button class="btn" type="button" id="browse-output" aria-label="选择保存文件夹">选文件夹</button>
          <button class="btn" type="button" id="save-as">另存为 ZIP</button>
        </div>
      </div>
      <p id="picker-out" class="picker-status hint" role="status" hidden></p>
    </div>
    <div class="form-section">
      <div class="field">
        <label for="custom">定制昵称<small>选填</small></label>
        <input id="custom" maxlength="128" placeholder="成品留空，定制填公开昵称" aria-describedby="custom-note" autocomplete="off">
        <p class="hint" id="custom-note">昵称会显示在建议文件名、游戏资源包列表和包内说明中。</p>
      </div>
      <div class="version-row">
        <div class="field">
          <label for="mc">Minecraft 版本</label>
          <input id="mc" maxlength="11" placeholder="如 1.21.11" aria-describedby="version-note" autocomplete="off">
        </div>
        <div class="field">
          <label for="pro">Pro 版本</label>
          <input id="pro" maxlength="11" placeholder="如 1.0" aria-describedby="version-note" autocomplete="off">
        </div>
      </div>
      <p class="hint version-note" id="version-note">版本号选填，用于命名。Pro 版本也会显示在列表署名首行。游戏兼容范围由源包决定。</p>
    </div>
    <div class="compact-file" id="compact-file" hidden>
      <p class="hint" id="compact-label"></p>
      <output class="preview-file" id="compact-name" for="src out mc pro custom"></output>
    </div>
    <button class="run" id="runBtn" type="submit"><i class="diamond" aria-hidden="true"></i><span id="run-label">混淆打包</span></button>
    <p class="notice" id="status-message" role="status" hidden></p>
    <div class="progress" id="progress" aria-hidden="true" hidden><i></i></div>
    <div class="status-actions" id="doneBtns" hidden><button class="btn" type="button" id="open-output">打开输出文件夹</button></div>
    <details id="details" hidden><summary>打包日志</summary><pre id="log"></pre></details>
  </form>
  <aside class="preview" aria-labelledby="preview-title">
    <div class="preview-heading">
      <h2 id="preview-title">输出预览</h2>
      <span class="hint" id="preview-kind">成品包</span>
    </div>
    <div id="preview" aria-live="polite">
      <p class="preview-label">资源包列表示意</p>
      <div class="pack-entry">
        <span class="pack-icon" aria-hidden="true"><i></i></span>
        <div class="pack-copy">
          <p class="pack-title" id="pack-title">沿用源包描述</p>
          <p class="pack-signature" id="pack-signature" hidden></p>
        </div>
      </div>
      <p class="preview-label file-label" id="file-label">建议文件名</p>
      <output class="preview-file" id="file-name" for="src out mc pro custom">选择源文件夹后生成</output>
      <p class="hint preview-foot" id="preview-note" hidden></p>
      <p class="preview-error" id="preview-error" hidden></p>
    </div>
  </aside>
</main>
<footer class="shell footer">
  <span>作者 流云 · PackSquash 引擎</span>
  <span>发货前请在目标版本检查加载和显示效果。</span>
</footer>
<dialog id="confirm-dialog" aria-labelledby="confirm-title" aria-describedby="confirm-text">
  <form class="modal" method="dialog">
    <h2 id="confirm-title"></h2>
    <p class="dialog-text" id="confirm-text"></p>
    <div class="actions">
      <button class="btn" value="cancel" autofocus>取消</button>
      <button class="btn primary" id="confirm-action" value="confirm"></button>
    </div>
  </form>
</dialog>
<script>
const $ = id => document.getElementById(id);
const fields = ['src', 'out', 'mc', 'pro', 'custom'];
const text = id => $(id).value.trim();
const labels = () => ({custom_name: text('custom'), minecraft_version: text('mc'), pro_version: text('pro')});
let previewTimer, previewRequest = 0, timer = null, lastOut = '', busy = false, showingResult = false;
let picking = false;

async function read(url, options) {
  const response = await fetch(url, options);
  return response.json();
}
function savePaths() {
  try { localStorage.setItem('lyun_cfg', JSON.stringify({src: text('src'), out: text('out')})); }
  catch (_) { /* Path preferences are optional. */ }
}
async function restorePaths() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem('lyun_cfg') || '{}'); }
  catch (_) { return; }
  if (typeof saved?.src !== 'string' || !saved.src) return;
  const src = saved.src;
  try {
    const source = await read('/api/check?p=' + encodeURIComponent(src));
    if (!text('src') && source.has_mcmeta) $('src').value = src;
    if (typeof saved.out === 'string' && saved.out && text('src') === src && !text('out')) {
      const output = await read('/api/check?p=' + encodeURIComponent(saved.out));
      if (output.isdir && text('src') === src && !text('out')) $('out').value = saved.out;
    }
  } catch (_) { /* A missing path can be selected again. */ }
  queuePreview();
}
function queuePreview() {
  const source = text('src');
  const sourceName = source.replace(/^"(.*)"$/, '$1').split(/[\\/]/).filter(Boolean).pop();
  $('source-name').hidden = !sourceName || sourceName === source;
  $('source-name').textContent = sourceName ? '文件夹 · ' + sourceName : '';
  const id = ++previewRequest;
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => updatePreview(id), 120);
}
async function updatePreview(id) {
  try {
    const src = text('src');
    const query = new URLSearchParams({src, out: text('out'), ...labels()});
    const data = await read('/api/preview?' + query);
    if (id !== previewRequest) return;
    const lines = (data.description || '').split('\n');
    $('preview-kind').textContent = lines[1] ? '定制包' : '成品包';
    $('pack-title').textContent = lines[0] || '沿用源包描述';
    $('pack-signature').textContent = lines[1] || '';
    $('pack-signature').hidden = !lines[1];
    const fileLabel = data.explicit ? '输出文件名' : '建议文件名';
    const filename = data.error ? '请检查打包设置' :
      (src || data.explicit ? data.name : '选择源文件夹后生成');
    $('file-label').textContent = $('compact-label').textContent = fileLabel;
    $('file-name').textContent = $('compact-name').textContent = filename;
    $('compact-file').hidden = !(src || data.explicit) || Boolean(data.error);
    $('preview-note').textContent = data.shortened ? '列表署名已缩短，包内说明保留完整昵称。' : '列表排版以游戏实际显示为准。';
    $('preview-note').hidden = !lines[1];
    $('preview-error').textContent = data.error || '';
    $('preview-error').hidden = !data.error;
  } catch (_) {
    if (id === previewRequest) {
      $('preview-error').textContent = '暂时无法刷新预览。';
      $('preview-error').hidden = false;
    }
  }
}
function showStatus(message, error = false) {
  showingResult = false;
  const notice = $('status-message');
  notice.textContent = message;
  notice.classList.toggle('error', error);
  notice.hidden = !message;
}
function ask(title, description, action) {
  const dialog = $('confirm-dialog');
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = description;
  $('confirm-action').textContent = action;
  dialog.returnValue = 'cancel';
  return new Promise(resolve => {
    dialog.addEventListener('close', () => resolve(dialog.returnValue === 'confirm'), {once: true});
    dialog.showModal();
  });
}
function setBusy(value) {
  busy = value;
  refreshControls();
  $('run-label').textContent = value ? '打包中…' : '混淆打包';
}
function refreshControls() {
  for (const id of [...fields, 'browse-source', 'browse-output', 'save-as', 'runBtn', 'quit']) {
    $(id).disabled = busy || picking;
  }
}
async function poll(restored = false) {
  try {
    const data = await read('/api/status');
    if ((restored && busy) || (!data.done && !data.running)) return;
    const log = $('log');
    const contents = data.log.join('\n');
    if (contents !== log.textContent) {
      const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 12;
      log.textContent = contents;
      if (atBottom) log.scrollTop = log.scrollHeight;
    }
    $('details').hidden = !contents;
    if (!data.done) { showStatus('正在复制源包并生成混淆 ZIP。'); return; }
    clearInterval(timer);
    timer = null;
    setBusy(false);
    $('progress').hidden = true;
    if (data.exit_code === 0) {
      lastOut = data.output;
      const filename = lastOut.split(/[\\/]/).pop();
      showStatus((restored ? '上次打包 · ' : '打包完成 · ') + filename);
      showingResult = true;
      $('doneBtns').hidden = false;
    } else {
      const reason = [...data.log].reverse().find(line => line.startsWith('[失败] '));
      showStatus(reason ? reason.slice(5) : `打包失败（退出码 ${data.exit_code}）。请查看打包日志。`, true);
      $('details').open = true;
    }
  } catch (_) { showStatus('暂时无法读取打包进度，正在重试。', true); }
}
function startPolling() {
  setBusy(true);
  showStatus('正在复制源包并生成混淆 ZIP。');
  $('progress').hidden = false;
  if (timer === null) timer = setInterval(poll, 700);
}
async function submitPack(event) {
  event.preventDefault();
  if (busy || picking) return;
  const src = text('src'), out = text('out');
  if (!src) {
    showStatus('请先选择包含 pack.mcmeta 的源文件夹。', true);
    $('src').focus();
    return;
  }
  savePaths();
  setBusy(true);
  showStatus('');
  $('doneBtns').hidden = true;
  $('details').hidden = true;
  $('details').open = false;
  $('log').textContent = '';
  const body = {src, out, ...labels()};
  const submit = () => read('/api/run', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  try {
    let reply = await submit();
    if (reply.output_exists) {
      if (!await ask('替换已有的 ZIP？', reply.error, '替换并打包')) return;
      body.overwrite = true;
      reply = await submit();
    }
    if (reply.error) { showStatus(reply.error, true); return; }
    startPolling();
  } catch (_) { showStatus('无法连接打包器，请重新打开程序。', true); }
  finally { if (timer === null) setBusy(false); }
}
function pickerFeedback(target, message, error = false) {
  const notice = $(target === 'src' ? 'picker-source' : 'picker-out');
  notice.textContent = message;
  notice.hidden = !message;
  notice.classList.toggle('picker-error', error);
}
async function choosePath(mode, trigger) {
  if (busy || picking) return;
  const target = mode === 'source' ? 'src' : 'out';
  picking = true;
  refreshControls();
  pickerFeedback(target, '请在 Windows 选择窗口中操作。');
  try {
    const body = {mode, src: text('src'), out: text('out'), ...labels()};
    const data = await read('/api/pick-path', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    if (data.error) { pickerFeedback(target, data.error, true); return; }
    if (data.path) {
      $(target).value = data.path;
      savePaths();
      formEdited();
    }
    pickerFeedback(target, '');
  } catch (_) { pickerFeedback(target, '无法打开 Windows 选择窗口。也可以直接粘贴路径。', true); }
  finally { picking = false; refreshControls(); if (!busy) $(trigger).focus(); }
}
$('browse-source').addEventListener('click', () => choosePath('source', 'browse-source'));
$('browse-output').addEventListener('click', () => choosePath('folder', 'browse-output'));
$('save-as').addEventListener('click', () => choosePath('save', 'save-as'));
$('open-output').addEventListener('click', async () => {
  try {
    const reply = await read('/api/openfolder', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (reply.error) showStatus(reply.error, true);
  }
  catch (_) { showStatus('无法打开输出文件夹：' + lastOut, true); }
});
$('quit').addEventListener('click', async () => {
  if (!await ask('退出打包器？', '再次使用时，双击打包器程序即可打开。', '退出程序')) return;
  try {
    const reply = await read('/api/quit', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    if (reply.error) { showStatus(reply.error, true); return; }
    setBusy(true);
    $('run-label').textContent = '程序已退出';
    $('doneBtns').hidden = true;
    showStatus('程序已退出，可以关闭这个页面。');
  } catch (_) { showStatus('无法连接打包器。', true); }
});
function formEdited() {
  if (showingResult) {
    showStatus('');
    $('doneBtns').hidden = true;
    $('details').hidden = true;
  }
  queuePreview();
}
for (const id of fields) $(id).addEventListener('input', () => {
  if (id === 'src' || id === 'out') pickerFeedback(id, '');
  formEdited();
});
for (const id of ['src', 'out']) $(id).addEventListener('blur', savePaths);
$('pack-form').addEventListener('submit', submitPack);
restorePaths();
queuePreview();
read('/api/status').then(data => {
  if (busy) return;
  if (data.running) startPolling();
  else if (data.done) poll(true);
}).catch(() => {});
</script>
</body>
</html>
"""


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_local_request(self):
        port = self.server.server_address[1]
        host = self.headers.get("Host")
        origin = self.headers.get("Origin")
        return (host in {f"127.0.0.1:{port}", f"localhost:{port}"}
                and (origin is None or origin == f"http://{host}")
                and self.headers.get("Sec-Fetch-Site") != "cross-site")

    def do_GET(self):
        if not self._is_local_request():
            self._json({"error": "只能从打包器本地页面访问"}, 403)
            return
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/preview":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query, keep_blank_values=True)
            opts = {key: q.get(key, [""])[0] for key in ("custom_name", "minecraft_version", "pro_version")}
            try:
                validate_labels(opts)
                src_text = clean_path(q.get("src", [""])[0])
                src = Path(src_text or "流云PVP材质包")
                if src_text:
                    src = validate_source(src_text)
                output, explicit = output_path(src, q.get("out", [""])[0].strip(), opts)
                custom = opts["custom_name"].strip()
                if src_text and output.resolve().is_relative_to(src):
                    raise ValueError("保存位置不能在源文件夹内，请选择其他位置")
                desc, shortened = build_custom_desc(custom, opts["pro_version"]) if custom else ("", False)
                self._json({"name": output.name, "explicit": explicit,
                            "description": re.sub(r"§.", "", desc), "shortened": shortened})
            except (ValueError, OSError) as exc:
                self._json({"error": str(exc)}, 400)
        elif path == "/api/status":
            with state_lock:
                self._json({"running": state["running"], "done": state["done"],
                            "exit_code": state["exit_code"], "output": state["output"], "log": state["log"]})
        elif path == "/api/check":
            from urllib.parse import parse_qs
            q = parse_qs(urlparse(self.path).query)
            try:
                p = clean_path(q.get("p", [""])[0])
                isdir = bool(p) and os.path.isdir(p)
                self._json({"isdir": isdir, "has_mcmeta": isdir and (Path(p) / "pack.mcmeta").is_file()})
            except (ValueError, OSError) as e:
                self._json({"error": str(e)}, 400)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route not in {"/api/run", "/api/pick-path", "/api/openfolder", "/api/quit"}:
            self._json({"error": "not found"}, 404)
            return
        if not self._is_local_request() or self.headers.get_content_type() != "application/json":
            self._json({"error": "只能从打包器本地页面操作"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 65536:
                raise ValueError("请求大小不正确")
            req = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(req, dict):
                raise ValueError("请求必须是 JSON 对象")
            if route in {"/api/openfolder", "/api/quit"}:
                if req:
                    raise ValueError("此操作无需参数")
                if route == "/api/quit":
                    with state_lock:
                        busy = state["running"] or picker_active
                        if not busy:
                            state["closing"] = True
                    if busy:
                        self._json({"error": "请先完成打包或关闭文件选择窗口"}, 409)
                        return
                    self._json({"ok": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                    return
                with state_lock:
                    target = state["output"] if state["done"] and state["exit_code"] == 0 else ""
                if not target or not Path(target).is_file():
                    raise ValueError("没有可打开的打包输出")
                os.startfile(str(Path(target).parent))  # noqa
                self._json({"ok": True})
                return
            src, out = req.get("src", ""), req.get("out", "")
            if not isinstance(src, str) or not isinstance(out, str):
                raise ValueError("源文件夹和输出路径必须是文字")
            if route == "/api/pick-path":
                mode = req.get("mode")
                if mode not in ("source", "folder", "save") or set(req) - {"mode", "src", "out", "custom_name", "pro_version", "minecraft_version"}:
                    raise ValueError("文件选择方式无效")
                opts = {k: req[k] for k in ("custom_name", "pro_version", "minecraft_version") if k in req}
                if mode == "save":
                    validate_labels(opts)
                self._json(choose_native_path(mode, src, out, opts))
                return
            if set(req) - {"src", "out", "custom_name", "pro_version", "minecraft_version", "overwrite"}:
                raise ValueError("图形界面只支持混淆打包和公开署名，请刷新页面后重试；请勿提交订单号")
            opts = {k: v for k, v in req.items() if k not in {"src", "out"}}
            output = start_job(src.strip(), out.strip(), opts)
        except FileExistsError as e:
            self._json({"error": str(e), "output_exists": True}, 409)
            return
        except (ValueError, TypeError, OSError) as e:
            self._json({"error": str(e)}, 400)
            return
        except RuntimeError as e:
            self._json({"error": str(e)}, 409)
            return
        self._json({"ok": True, "output": output})


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def pick_port(base=8765):
    for port in range(base, base + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return base


def main():
    try:
        port = pick_port()
        url = f"http://127.0.0.1:{port}/"
        with Server(("127.0.0.1", port), Handler) as server:
            if "--no-browser" not in sys.argv[1:]:
                threading.Timer(1.0, lambda: webbrowser.open(url)).start()
            if sys.stdout is not None:
                print(f"流云材质包打包器运行中：{url}")
            server.serve_forever()
    except Exception:
        (HERE / "crash.log").write_text(traceback.format_exc(), "utf-8")
        raise


if __name__ == "__main__":
    main()
