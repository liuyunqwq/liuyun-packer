# -*- coding: utf-8 -*-
"""流云材质包打包器 — 图形界面服务器
双击 exe 即可使用，无需安装 Python / 命令行。
基于 PackSquash，作者：流云
"""
import http.server
import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

# ---------------- 路径定位（兼容 PyInstaller 冻结） ----------------
if getattr(sys, "frozen", False):
    HERE = Path(sys.executable).resolve().parent
    _APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "流云打包器"
    _APPDATA.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE = _APPDATA / "ui_config.json"
    TOML_OUT = _APPDATA / "generated_options.toml"
else:
    HERE = Path(__file__).resolve().parent
    CONFIG_FILE = HERE / "ui_config.json"
    TOML_OUT = HERE / "generated_options.toml"

EXE = HERE / "packsquash.exe"

# ---------------- 运行状态 ----------------
state = {"running": False, "log": [], "done": False, "exit_code": None, "output": "", "source": ""}
state_lock = threading.Lock()


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
    png_obf = opts.get("png_obfuscation", True)
    ogg_obf = opts.get("ogg_obfuscation", True)
    zip_obf = opts.get("zip_obfuscation", True)
    optifine = opts.get("optifine", True)
    iters = int(opts.get("iterations", 5))
    img_iters = max(10, iters * 2)
    strong = opts.get("preset", "strong") == "strong"
    conformance = "disregard" if (strong or zip_obf) else "balanced"

    lines = [
        f"pack_directory = {toml_str(src)}",
        f"output_file_path = {toml_str(out)}",
        "recompress_compressed_files = true",
        f"zip_compression_iterations = {iters}",
        "automatic_minecraft_quirks_detection = true",
        "work_around_minecraft_quirks = ['grayscale_images_gamma_miscorrection', 'java8_zip_parsing']",
        f"allow_mods = [{toml_str('OptiFine') if optifine else ''}]",
        "skip_pack_icon = false",
        "validate_pack_metadata_file = true",
        "ignore_system_and_hidden_files = false",
        f"zip_spec_conformance_level = '{conformance}'",
        f"size_increasing_zip_obfuscation = {'true' if strong else 'false'}",
        "percentage_of_zip_structures_tuned_for_obfuscation_discretion = 100" if strong else "",
        "never_store_squash_times = true",
        f"threads = {os.cpu_count() or 4}",
        "spooling_buffers_size = 128",
        "",
        "['**/*?.ogg']",
        "transcode_ogg = false",
        "two_pass_vorbis_optimization_and_validation = true" if ogg_obf else "two_pass_vorbis_optimization_and_validation = false",
        f"ogg_obfuscation = {'true' if ogg_obf else 'false'}",
        "",
        "['**/*?.{flac,wav}']",
        "channels = 2",
        "sampling_frequency = 44100",
        "target_pitch = 1.5",
        "target_bitrate_control_metric = 96000",
        "",
        "['**/*.jsonc']",
        "minify_json = false",
        "delete_bloat_keys = false",
        "",
        "['**/*.json']",
        "minify_json = true",
        "delete_bloat_keys = true",
        "",
        "['**/*.png']",
        f"image_data_compression_iterations = {img_iters}",
        "color_quantization_target = 'none'",
        "maximum_width_and_height = 3072",
        "skip_alpha_optimizations = true",
        f"png_obfuscation = {'true' if png_obf else 'false'}",
        "",
        "['**/*.{fsh,vsh}']",
        "shader_source_transformation_strategy = 'keep_as_is'",
        "",
        "['**/*.properties']",
        "minify_properties = false",
    ]
    return "\n".join(l for l in lines if l != "")


def run_packquash(src, out, opts):
    TOML_OUT.write_text(build_toml(src, out, opts), "utf-8")
    with state_lock:
        state.update(running=True, done=False, log=[], exit_code=None, output=out, source=src)
    try:
        proc = subprocess.Popen(
            [str(EXE), str(TOML_OUT)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(HERE),
        )
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip()
            with state_lock:
                state["log"].append(line)
        proc.wait()
        with state_lock:
            state["exit_code"] = proc.returncode
    except Exception as e:
        with state_lock:
            state["log"].append(f"[启动失败] {e}")
            state["exit_code"] = -1
    finally:
        with state_lock:
            state["running"] = False
            state["done"] = True




HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>流云材质包打包器</title>
<style>
:root{
  --bg1:#0d1017; --bg2:#151a26; --panel:#181d2a; --panel2:#1e2435;
  --line:#2a3142; --line2:#36405a;
  --txt:#eef1f7; --sub:#8893a8; --sub2:#5d6680;
  --acc:#7c6cff; --acc2:#5b8cff; --ok:#3ddc97; --warn:#ffb454; --err:#ff6b81;
  --grad:linear-gradient(135deg,#7c6cff 0%,#5b8cff 100%);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{
  background:radial-gradient(1200px 600px at 50% -200px,#1d2440 0%,transparent 60%),var(--bg1);
  color:var(--txt);
  font-family:"Microsoft YaHei UI","Microsoft YaHei",system-ui,-apple-system,sans-serif;
  min-height:100vh;display:flex;justify-content:center;padding:32px 16px 48px;
  -webkit-font-smoothing:antialiased;
}
.wrap{width:100%;max-width:780px;position:relative}
/* 顶栏 */
.topbar{display:flex;align-items:center;gap:14px;margin-bottom:26px}
.logo{
  width:52px;height:52px;border-radius:14px;background:var(--grad);
  display:flex;align-items:center;justify-content:center;font-size:26px;
  box-shadow:0 8px 24px rgba(124,108,255,.35);flex-shrink:0;
}
.titles{flex:1;min-width:0}
.titles h1{font-size:22px;font-weight:700;letter-spacing:.5px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.badge{font-size:11px;font-weight:600;color:var(--acc);background:rgba(124,108,255,.14);
  border:1px solid rgba(124,108,255,.3);border-radius:6px;padding:3px 9px;white-space:nowrap}
.author{font-size:12px;color:var(--sub2);margin-top:3px}
.author b{color:var(--sub);font-weight:600}
.quit{width:38px;height:38px;border-radius:10px;border:1px solid var(--line);background:var(--panel);
  color:var(--sub);font-size:18px;cursor:pointer;flex-shrink:0;transition:.15s}
.quit:hover{border-color:var(--err);color:var(--err);background:rgba(255,107,129,.08)}
/* 卡片 */
.card{background:linear-gradient(180deg,var(--panel) 0%,var(--bg2) 100%);
  border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px;
  box-shadow:0 4px 20px rgba(0,0,0,.2)}
.card-title{font-size:13px;font-weight:600;color:var(--sub);margin-bottom:12px;
  display:flex;align-items:center;gap:7px;text-transform:uppercase;letter-spacing:.6px}
.card-title .dot{width:6px;height:6px;border-radius:50%;background:var(--acc)}
label.fld{display:block;font-size:12px;color:var(--sub2);margin-bottom:6px;font-weight:500}
input[type=text]{width:100%;background:#10141d;border:1px solid var(--line);color:var(--txt);
  border-radius:10px;padding:11px 14px;font-size:14px;outline:none;transition:.15s;font-family:inherit}
input[type=text]:focus{border-color:var(--acc);box-shadow:0 0 0 3px rgba(124,108,255,.15);background:#131826}
input[type=text]::placeholder{color:var(--sub2)}
.row{display:flex;gap:10px;align-items:center}
.row input{flex:1;min-width:0}
.btn{background:var(--panel2);border:1px solid var(--line2);color:var(--txt);border-radius:10px;
  padding:10px 16px;font-size:13px;cursor:pointer;white-space:nowrap;transition:.15s;font-family:inherit}
.btn:hover{border-color:var(--acc);color:#fff;background:#262d42}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn.primary{border-color:rgba(124,108,255,.5);color:#c9c2ff}
.spacer{height:16px}
/* 预设 */
.presets{display:flex;gap:12px;margin-top:2px}
.preset{flex:1;border:1.5px solid var(--line);border-radius:14px;padding:16px;cursor:pointer;
  background:#11151f;transition:.18s;position:relative;overflow:hidden}
.preset:hover{border-color:var(--line2);transform:translateY(-1px)}
.preset.sel{border-color:var(--acc);background:linear-gradient(180deg,rgba(124,108,255,.1),rgba(91,140,255,.04))}
.preset.sel::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:var(--grad)}
.preset .pic{font-size:22px;margin-bottom:8px;display:block}
.preset b{font-size:14px;display:block;margin-bottom:5px}
.preset span{font-size:12px;color:var(--sub);line-height:1.55;display:block}
/* 高级 */
details{margin-top:16px;border-top:1px solid var(--line);padding-top:14px}
summary{font-size:13px;color:var(--sub);cursor:pointer;user-select:none;font-weight:500}
summary:hover{color:var(--txt)}
.chk{display:flex;align-items:center;gap:9px;padding:9px 0;font-size:14px;cursor:pointer}
.chk input{width:17px;height:17px;accent-color:var(--acc)}
.chk small{color:var(--sub2)}
.range-row{display:flex;align-items:center;gap:12px;margin-top:10px}
.range-row label{font-size:13px;color:var(--sub);white-space:nowrap}
input[type=range]{flex:1;accent-color:var(--acc);height:5px}
.range-val{font-size:14px;font-weight:700;color:var(--acc);min-width:24px;text-align:center}
/* 运行 */
.run{width:100%;padding:15px;font-size:16px;font-weight:700;border:none;border-radius:14px;
  background:var(--grad);color:#fff;cursor:pointer;margin-top:4px;transition:.15s;
  box-shadow:0 6px 20px rgba(124,108,255,.3);letter-spacing:1px}
.run:hover{transform:translateY(-1px);box-shadow:0 8px 26px rgba(124,108,255,.4)}
.run:disabled{opacity:.55;cursor:not-allowed;transform:none}
.bar{height:6px;background:#10141d;border-radius:3px;margin:14px 0 0;overflow:hidden;display:none}
.bar i{display:block;height:100%;width:0;background:var(--grad);transition:width .4s;border-radius:3px}
#log{background:#0a0d14;border:1px solid var(--line);border-radius:12px;padding:14px;
  font:12px/1.75 "Cascadia Code","Consolas",monospace;height:280px;overflow-y:auto;
  white-space:pre-wrap;word-break:break-all;color:#9fb0c8;display:none;margin-top:12px}
#log::-webkit-scrollbar{width:8px}#log::-webkit-scrollbar-track{background:transparent}
#log::-webkit-scrollbar-thumb{background:#2a3142;border-radius:4px}
.final{color:var(--ok);font-weight:700}
.errline{color:var(--err)}
.done-btns{display:none;gap:10px;margin-top:12px}
.hint{font-size:12px;color:var(--sub2);margin-top:16px;line-height:1.7;text-align:center}
.footer{text-align:center;font-size:11px;color:var(--sub2);margin-top:24px;line-height:1.7}
.footer b{color:var(--sub);font-weight:600}
/* 浏览弹窗 */
#modal{display:none;position:fixed;inset:0;background:rgba(5,8,14,.7);backdrop-filter:blur(4px);z-index:9}
.mbox{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:680px;max-width:94vw;
  max-height:80vh;display:flex;flex-direction:column;background:var(--panel);border:1px solid var(--line2);
  border-radius:16px;padding:20px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.mbox label{font-size:13px;color:var(--sub);font-weight:600;margin-bottom:10px;display:block}
.bitem{display:flex;align-items:center;gap:10px;width:100%;text-align:left;background:none;border:none;
  color:var(--txt);padding:10px 12px;font-size:14px;border-radius:8px;cursor:pointer;transition:.12s;font-family:inherit}
.bitem:hover{background:rgba(124,108,255,.1)}
.bmc{font-size:12px;color:var(--ok);margin-right:auto;font-weight:600}
#blist{overflow-y:auto;flex:1;margin:10px 0;min-height:220px;max-height:46vh}
#blist::-webkit-scrollbar{width:8px}#blist::-webkit-scrollbar-thumb{background:#2a3142;border-radius:4px}
</style>
</head>
<body>
<div class="wrap">
 <div class="topbar">
  <div class="logo">☁</div>
  <div class="titles">
   <h1>流云材质包打包器 <span class="badge">加密保护版</span></h1>
   <div class="author">材质包加密压缩 · 防解压混淆 · 作者 <b>流云</b></div>
  </div>
  <button class="quit" title="退出程序" onclick="quitApp()">✕</button>
 </div>

 <div class="card">
  <div class="card-title"><span class="dot"></span> 材质包源</div>
  <label class="fld">源文件夹（包含 pack.mcmeta 的文件夹）</label>
  <div class="row">
   <input type="text" id="src" placeholder="点击右侧浏览选择，或手动输入路径">
   <button class="btn" onclick="openBrowse('src')">浏览…</button>
  </div>
  <div class="spacer"></div>
  <label class="fld">输出 ZIP 文件</label>
  <div class="row">
   <input type="text" id="out" placeholder="留空则自动保存到源文件夹旁边">
   <button class="btn" onclick="openBrowse('out')">浏览…</button>
  </div>
 </div>

 <div class="card">
  <div class="card-title"><span class="dot"></span> 保护强度</div>
  <div class="presets">
   <div class="preset sel" id="p-strong" onclick="setPreset('strong')">
    <span class="pic">🔒</span><b>最强保护（推荐）</b>
    <span>ZIP 结构混淆 + PNG 图片混淆 + OGG 音效混淆。解压软件打不开，强行提取出的图片和音效全部损坏。</span>
   </div>
   <div class="preset" id="p-plain" onclick="setPreset('plain')">
    <span class="pic">⚡</span><b>仅压缩优化</b>
    <span>不混淆，仅无损压缩减小体积，任何解压软件都能打开。用于内部调试。</span>
   </div>
  </div>
  <details>
   <summary>高级选项</summary>
   <label class="chk"><input type="checkbox" id="o-png" checked> PNG 图片混淆 <small>（提取后无法查看）</small></label>
   <label class="chk"><input type="checkbox" id="o-ogg" checked> OGG 音效混淆 <small>（提取后无法播放）</small></label>
   <label class="chk"><input type="checkbox" id="o-zip" checked> ZIP 结构混淆 <small>（解压软件报错）</small></label>
   <label class="chk"><input type="checkbox" id="o-of" checked> 兼容 OptiFine</label>
   <div class="range-row">
    <label>压缩力度</label>
    <input type="range" id="o-iters" min="1" max="10" value="5" oninput="$('itersVal').textContent=this.value">
    <span class="range-val" id="itersVal">5</span>
   </div>
  </details>
 </div>

 <button class="run" id="runBtn" onclick="run()">▶ 开始打包</button>
 <div class="bar" id="bar"><i id="barFill"></i></div>
 <div id="log"></div>
 <div class="done-btns" id="doneBtns">
  <button class="btn primary" onclick="openFolder()">📂 打开输出文件夹</button>
 </div>

 <div class="hint">打包完成后记得先进游戏确认贴图和音效显示正常，再对外发布。</div>
 <div class="footer">由 <b>流云</b> 制作 · 基于 PackSquash 开源项目<br>本工具在本地运行，不会上传任何文件</div>
</div>

<div id="modal" onclick="if(event.target===this)closeBrowse()">
 <div class="mbox">
  <label id="btitle">选择文件夹</label>
  <div class="row">
   <input type="text" id="bpath" placeholder="路径">
   <button class="btn" onclick="browseGo()">前往</button>
  </div>
  <div id="blist"></div>
  <div class="row">
   <span class="bmc" id="bmcmeta"></span>
   <button class="btn" onclick="closeBrowse()">取消</button>
   <button class="btn primary" onclick="pickBrowse()">✔ 选择此文件夹</button>
  </div>
 </div>
</div>

<script>
let preset='strong',timer=null,lastLines=0,lastOut='';
const $=id=>document.getElementById(id);
function setPreset(p){
 preset=p;
 $('p-strong').classList.toggle('sel',p==='strong');
 $('p-plain').classList.toggle('sel',p==='plain');
 const on=p==='strong';
 $('o-png').checked=on;$('o-ogg').checked=on;$('o-zip').checked=on;
 for(const id of ['o-png','o-ogg','o-zip'])$(id).disabled=(p!=='strong');
}
function save(){localStorage.setItem('lyun_cfg',JSON.stringify({src:$('src').value,out:$('out').value,iters:$('o-iters').value}));}
function restore(){
 try{const c=JSON.parse(localStorage.getItem('lyun_cfg')||'{}');
  if(c.src)$('src').value=c.src;if(c.out)$('out').value=c.out;if(c.iters)$('o-iters').value=c.iters,$('itersVal').textContent=c.iters;
 }catch(e){}
}
$('src').onblur=()=>{if(!$('out').value&&$('src').value)$('out').value=$('src').value+'.zip';save()};
$('out').onblur=save;
/* 浏览 */
let browseTarget='src',browseCur='';
function openBrowse(t){
 browseTarget=t;
 $('btitle').textContent=t==='src'?'选择材质包源文件夹（含 pack.mcmeta）':'选择输出 ZIP 所在文件夹';
 $('modal').style.display='block';
 const init=t==='src'?$('src').value.trim():$('out').value.trim();
 browseGo(init);
}
function closeBrowse(){$('modal').style.display='none'}
function browseGo(path){
 path=(path!==undefined?path:$('bpath').value).trim();
 fetch('/api/browse?path='+encodeURIComponent(path)).then(r=>r.json()).then(d=>{
  if(d.error){alert(d.error);return}
  browseCur=d.path;$('bpath').value=d.path;
  const list=$('blist');list.innerHTML='';
  $('bmcmeta').textContent=d.has_mcmeta?'✔ 此文件夹包含 pack.mcmeta':'';
  if(d.parent!==undefined&&d.parent!=='')addBItem(list,'⬆','返回上级',d.parent);
  if(!d.path){$('bpath').value='';
   const hd=document.createElement('div');hd.style.cssText='font-size:12px;color:var(--sub2);padding:4px 12px 8px';
   hd.textContent='💻 此电脑 — 请选择盘符';list.appendChild(hd);
   (d.dirs||[]).forEach(dr=>addBItem(list,'💾',dr,dr));
   if(!(d.dirs||[]).length)list.innerHTML='<span style="color:var(--sub2);font-size:13px">没找到可用盘符</span>';
  }else{
   if((d.dirs||[]).length)d.dirs.forEach(n=>addBItem(list,'📁',n,d.path+'\\'+n));
   else list.innerHTML='<span style="color:var(--sub2);font-size:13px">此文件夹下没有子文件夹</span>';
  }
 }).catch(e=>alert('连接失败：'+e));
}
function addBItem(list,icon,text,path){
 const b=document.createElement('button');b.className='bitem';
 b.innerHTML='<span>'+icon+'</span><span>'+text+'</span>';b.title=path;b.onclick=()=>browseGo(path);list.appendChild(b);
}
function pickBrowse(){
 if(!browseCur){alert('请先选择一个文件夹');return}
 if(browseTarget==='src'){$('src').value=browseCur;if(!$('out').value.trim())$('out').value=browseCur+'.zip';}
 else{const oldName=($('out').value.trim().split('\\').pop())||'';
  $('out').value=browseCur+'\\'+(oldName.toLowerCase().endsWith('.zip')?oldName:'材质包.zip');}
 save();closeBrowse();
}
/* 轮询 */
function poll(){
 fetch('/api/status').then(r=>r.json()).then(d=>{
  const log=$('log');
  if(d.log.length>lastLines){log.textContent+=(log.textContent?'\n':'')+d.log.slice(lastLines).join('\n');lastLines=d.log.length;log.scrollTop=log.scrollHeight;}
  const m=[...d.log].reverse().find(l=>l.includes('pack files'));
  if(m){const mm=m.match(/(\d+)\s*pack files?/);if(mm)$('barFill').style.width=Math.min(100,parseInt(mm[1])/15)+'%'}
  if(d.done){clearInterval(timer);$('runBtn').disabled=false;$('barFill').style.width='100%';
   if(d.exit_code===0){log.innerHTML+='\n<span class="final">✔ 打包完成！</span>';$('doneBtns').style.display='flex';}
   else{log.innerHTML+='\n<span class="errline">✘ 打包失败（退出码 '+d.exit_code+'），请检查上方日志</span>';}
  }
 });
}
function openFolder(){fetch('/api/openfolder?path='+encodeURIComponent(lastOut));}
function quitApp(){if(confirm('确定退出流云材质包打包器？'))fetch('/api/quit');}
async function run(){
 const src=$('src').value.trim(),out=$('out').value.trim()||src+'.zip';
 if(!src){alert('请先选择材质包源文件夹');return}
 if(src===out){alert('输出 ZIP 不能和源文件夹相同');return}
 lastOut=out;save();
 $('runBtn').disabled=true;$('log').style.display='block';$('bar').style.display='block';
 $('doneBtns').style.display='none';$('log').textContent='正在启动 PackSquash...';lastLines=0;$('barFill').style.width='0%';
 const body={src,out,preset,png_obfuscation:$('o-png').checked,ogg_obfuscation:$('o-ogg').checked,
  zip_obfuscation:$('o-zip').checked,optifine:$('o-of').checked,iterations:parseInt($('o-iters').value)};
 try{const r=await fetch('/api/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(d.error){alert(d.error);$('runBtn').disabled=false;$('bar').style.display='none';return}
  timer=setInterval(poll,700);
 }catch(e){alert('连接失败：'+e);$('runBtn').disabled=false}
}
restore();
</script>
</body>
</html>"""


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

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/status":
            with state_lock:
                self._json({"running": state["running"], "done": state["done"],
                            "exit_code": state["exit_code"], "log": state["log"][-2000:]})
        elif path == "/api/browse":
            from urllib.parse import unquote
            q = urlparse(self.path).query
            m = re.search(r"path=([^&]*)", q)
            target = unquote(m.group(1)) if m else ""
            if not target:
                import string
                drives = [f"{l}:\\" for l in string.ascii_uppercase if os.path.isdir(f"{l}:\\")]
                self._json({"path": "", "dirs": drives})
                return
            target = os.path.abspath(target)
            if not os.path.isdir(target):
                self._json({"error": f"无法访问：{target}"}, 400)
                return
            try:
                names = sorted(e.name for e in os.scandir(target) if e.is_dir() and not e.name.startswith("."))
            except OSError as e:
                self._json({"error": f"无法读取：{e}"}, 400)
                return
            parent = os.path.dirname(target.rstrip("\\")) if not target.endswith(":\\") else ""
            self._json({"path": target, "parent": parent, "dirs": names,
                        "has_mcmeta": os.path.isfile(os.path.join(target, "pack.mcmeta"))})
        elif path == "/api/openfolder":
            q = urlparse(self.path).query
            p = re.search(r"path=([^&]+)", q)
            if p:
                from urllib.parse import unquote
                target = unquote(p.group(1))
                if os.path.isdir(target):
                    os.startfile(target)  # noqa
                elif os.path.isfile(target):
                    os.startfile(str(Path(target).parent))  # noqa
            self._json({"ok": True})
        elif path == "/api/quit":
            self._json({"ok": True})
            threading.Timer(0.3, os._exit, args=[0]).start()
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if urlparse(self.path).path != "/api/run":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            req = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            self._json({"error": "请求数据解析失败，请刷新页面重试"}, 400)
            return
        src, out = req.get("src", "").strip(), req.get("out", "").strip()
        if not src or not os.path.isdir(src):
            self._json({"error": f"源文件夹不存在：{src}"}, 400)
            return
        if not (Path(src) / "pack.mcmeta").exists():
            self._json({"error": f"该文件夹里没有 pack.mcmeta，不是材质包源：{src}"}, 400)
            return
        if not out.lower().endswith(".zip"):
            out += ".zip"
        if not EXE.exists():
            self._json({"error": f"找不到 packsquash.exe（应与本程序放在同一文件夹）"}, 400)
            return
        with state_lock:
            if state["running"]:
                self._json({"error": "已有打包任务正在进行中"}, 400)
                return
        save_cfg({"last_src": src, "last_out": out, "opts": req})
        threading.Thread(target=run_packquash, args=(src, out, req), daemon=True).start()
        self._json({"ok": True})


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
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        print(f"流云材质包打包器运行中：{url}")
        Server(("127.0.0.1", port), Handler).serve_forever()
    except Exception:
        (HERE / "crash.log").write_text(traceback.format_exc(), "utf-8")
        raise


if __name__ == "__main__":
    main()
