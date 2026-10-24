#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
图片批量压缩工具（桌面版）
============================
双击本程序（或配套的"启动图片压缩工具.bat"）直接打开 HTML 页面窗口。
页面里选择文件夹、设置参数、点开始压缩：
- 底层用 Python 批量处理（支持大量图片、多线程）
- 页面实时显示进度条 + 命令行日志
- 原生文件夹对话框选择真实路径（支持网盘同步目录）

依赖：pip install pywebview pillow
"""
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

from PIL import Image, ImageOps

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
FMT_EXT = {"webp": ".webp", "jpg": ".jpg", "png": ".png"}

# ================= 任务状态 =================
STATE = {
    "running": False,
    "stop": False,
    "done": 0,
    "total": 0,
    "logs": [],
    "since": 0,
    "stats": {"ok": 0, "skip": 0, "fail": 0, "orig": 0, "new": 0},
}
LOCK = threading.Lock()


def log(msg):
    ts = time.strftime("%H:%M:%S")
    with LOCK:
        STATE["logs"].append(f"[{ts}] {msg}")


def fmt_size(n):
    if n < 1024:
        return f"{n} B"
    if n < 1048576:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1048576:.2f} MB"


def collect_files(src: Path, min_size: int):
    src = Path(src)
    files = []
    for p in src.rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                if min_size and p.stat().st_size < min_size:
                    continue
                files.append(p)
        except OSError:
            continue
    return sorted(files)


def convert_one(src: Path, dst: Path, p):
    try:
        if dst.exists() and not p["force"]:
            return "skip", 0, 0, None
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            if getattr(im, "is_animated", False):
                im.seek(0)
            if p["format"] == "jpg":
                if im.mode in ("RGBA", "LA", "P"):
                    im = im.convert("RGBA")
                    bg = Image.new("RGB", im.size, (255, 255, 255))
                    bg.paste(im, mask=im.split()[-1])
                    im = bg
                else:
                    im = im.convert("RGB")
            elif im.mode not in ("RGB", "RGBA", "L"):
                im = im.convert("RGB")
            if p["max_edge"] > 0:
                im.thumbnail((p["max_edge"], p["max_edge"]), Image.LANCZOS)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if p["format"] == "webp":
                im.save(dst, "WEBP", quality=p["quality"], method=6)
            elif p["format"] == "jpg":
                im.save(dst, "JPEG", quality=p["quality"], optimize=True, progressive=True)
            else:
                im.save(dst, "PNG", optimize=True)
        return "ok", src.stat().st_size, dst.stat().st_size, None
    except Exception as e:
        return "fail", 0, 0, f"{e}"[:200]


def run_task(p):
    with LOCK:
        STATE["running"] = True
        STATE["stop"] = False
        STATE["done"] = 0
        STATE["total"] = 0
        STATE["since"] = len(STATE["logs"])
        STATE["stats"] = {"ok": 0, "skip": 0, "fail": 0, "orig": 0, "new": 0}
    try:
        src = Path(p["src"])
        out = Path(p["out"])
        if out == src:
            log("[错误] 输出文件夹不能等于源文件夹")
            return
        files = collect_files(src, p["min_size"])
        total = len(files)
        with LOCK:
            STATE["total"] = total
        if not total:
            log("没有找到可处理的图片")
            return
        orig_sum = sum(f.stat().st_size for f in files)
        log(f"发现 {total} 张图片，总大小 {fmt_size(orig_sum)}")
        log(f"输出: {p['format']} | 质量 {p['quality']}"
            + (f" | 最长边 {p['max_edge']}px" if p["max_edge"] else "")
            + f" | 线程 {p['threads']} -> {out}")
        done = 0
        start_time = time.time()

        def work(f):
            rel = f.relative_to(src)
            dst = out / rel.with_suffix(FMT_EXT[p["format"]])
            return f, rel, convert_one(f, dst, p)

        with ThreadPoolExecutor(max_workers=max(1, p["threads"])) as pool:
            futures = []
            for f in files:
                if STATE["stop"]:
                    log("检测到停止请求，跳过剩余任务…")
                    break
                futures.append(pool.submit(work, f))
            for fut in as_completed(futures):
                if STATE["stop"]:
                    break
                f, rel, (status, old, new, err) = fut.result()
                done += 1
                with LOCK:
                    STATE["done"] = done
                    st = STATE["stats"]
                if status == "ok":
                    st["ok"] += 1
                    st["orig"] += old
                    st["new"] += new
                    diff = old - new
                    log(f"OK   {rel}  {fmt_size(old)} -> {fmt_size(new)}"
                        f" ({'节省' if diff >= 0 else '增大'} {fmt_size(abs(diff))})")
                    if p["delete_original"]:
                        try:
                            f.unlink()
                            log(f"已删除原图 {rel}")
                        except OSError:
                            pass
                elif status == "skip":
                    st["skip"] += 1
                    log(f"跳过 {rel}（输出已存在）")
                else:
                    st["fail"] += 1
                    log(f"失败 {rel}  {err}")
        if STATE["stop"]:
            log("已停止")
        st = STATE["stats"]
        log("========== 汇总 ==========")
        log(f"成功 {st['ok']} | 跳过 {st['skip']} | 失败 {st['fail']}")
        if st["ok"]:
            saved = st["orig"] - st["new"]
            pct = st["orig"] and round(saved / st["orig"] * 100) or 0
            verb = "节省" if saved >= 0 else "增大"
            log(f"原大小 {fmt_size(st['orig'])} | 新大小 {fmt_size(st['new'])}"
                f" | {verb} {fmt_size(abs(saved))} ({pct}%)")
        log(f"耗时 {time.time() - start_time:.1f} 秒")
    finally:
        with LOCK:
            STATE["running"] = False
        log("任务结束")


# ================= HTML 界面 =================
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>图片批量压缩工具</title>
<style>
:root{--bg:#0D1117;--bg2:#161B22;--bg3:#1C2333;--line:#26303E;--line2:#35404F;
--text:#E6EDF3;--sub:#9AA7B2;--dim:#6B7A86;--accent:#2EA043;--accent2:#3FB950;
--term-bg:#0A0D10;--term-fg:#7EE787;--warn:#E9B44C;--danger:#E76F51}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"PingFang SC","Microsoft YaHei","Noto Sans SC",system-ui,sans-serif;
background:var(--bg);color:var(--text);line-height:1.6;height:100vh;display:flex;flex-direction:column}
.wrap{max-width:1020px;width:100%;margin:0 auto;padding:20px 22px 24px;flex:1;overflow-y:auto}
header{display:flex;align-items:center;gap:13px;margin-bottom:18px}
.logo{width:42px;height:42px;border-radius:10px;background:rgba(46,160,67,.13);display:flex;align-items:center;justify-content:center;flex:none}
h1{font-size:21px;font-weight:700}
.sub{color:var(--sub);font-size:12.5px;margin-top:2px}
.card{background:var(--bg2);border:1px solid var(--line);border-radius:12px;padding:18px;margin-bottom:14px}
.card h2{font-size:14px;font-weight:600;margin-bottom:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:760px){.grid2{grid-template-columns:1fr}}
label.blk{display:block;font-size:12.5px;color:var(--sub);margin-bottom:7px;font-weight:500}
.pathrow{display:flex;gap:9px;align-items:center}
input[type=text],input[type=number]{background:var(--bg);border:1px solid var(--line2);color:var(--text);border-radius:9px;padding:8px 11px;font-size:13px;font-family:inherit;outline:none;flex:1;min-width:0}
input[type=text]:focus,input[type=number]:focus{border-color:var(--accent2)}
.btn{display:inline-flex;align-items:center;gap:6px;border:none;cursor:pointer;border-radius:9px;font-size:13px;font-weight:600;padding:9px 16px;font-family:inherit;transition:background .15s;flex:none}
.btn:active{transform:scale(.97)}
.btn-p{background:var(--accent);color:#fff}.btn-p:hover{background:var(--accent2)}
.btn-g{background:var(--bg3);color:var(--text);border:1px solid var(--line2)}
.btn-g:hover{border-color:var(--accent2);color:var(--accent2)}
.btn-r{background:var(--bg3);color:var(--text);border:1px solid var(--line2)}
.btn-r:hover{border-color:var(--danger);color:var(--danger)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.seg{display:flex;background:var(--bg);border:1px solid var(--line2);border-radius:9px;overflow:hidden}
.seg button{flex:1;background:transparent;border:none;color:var(--sub);font-size:13px;padding:8px 0;cursor:pointer;font-family:inherit;font-weight:500}
.seg button.on{background:var(--accent);color:#fff;font-weight:600}
.quality-row{display:flex;align-items:center;gap:12px}
input[type=range]{flex:1;accent-color:var(--accent);height:4px}
.qnum{width:50px;text-align:right;color:var(--accent2);font-weight:700;font-size:14px}
.checks{display:flex;gap:16px;flex-wrap:wrap;margin-top:4px}
.checks label{display:flex;align-items:center;gap:7px;font-size:12.5px;color:var(--text);cursor:pointer}
.checks input{accent-color:var(--accent);width:15px;height:15px}
.actionbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.hint{font-size:12px;color:var(--dim)}
.progress{display:none;margin-top:15px}
.progress.show{display:block}
.pbar{height:8px;background:var(--bg);border:1px solid var(--line);border-radius:99px;overflow:hidden}
.pfill{height:100%;width:0;background:linear-gradient(90deg,var(--accent),var(--accent2));border-radius:99px;transition:width .25s}
.pinfo{display:flex;justify-content:space-between;font-size:12.5px;color:var(--sub);margin-top:8px}
.terminal{border:1px solid var(--line2);border-radius:11px;overflow:hidden;background:var(--term-bg)}
.term-bar{display:flex;align-items:center;gap:7px;background:var(--bg3);border-bottom:1px solid var(--line);padding:8px 13px}
.term-bar .dot{width:11px;height:11px;border-radius:50%}
.t1{background:#FF5F57}.t2{background:#FEBC2E}.t3{background:#28C840}
.term-bar .title{color:var(--dim);font-size:12px;font-family:Consolas,"Cascadia Mono",monospace;margin-left:8px}
.term-body{height:250px;overflow-y:auto;padding:11px 13px;font-family:Consolas,"Cascadia Mono","Courier New",monospace;font-size:12.5px;line-height:1.7;color:var(--term-fg);white-space:pre-wrap;word-break:break-all}
.term-body .warn{color:var(--warn)}.term-body .err{color:var(--danger)}.term-body .dim{color:#5C6B78}
.stats{display:none;grid-template-columns:repeat(4,1fr);gap:11px;margin-top:14px}
.stats.show{display:grid}
@media(max-width:760px){.stats{grid-template-columns:repeat(2,1fr)}}
.stat{background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 15px}
.stat .v{font-size:18px;font-weight:700;font-variant-numeric:tabular-nums}
.stat .k{font-size:11.5px;color:var(--dim);margin-top:2px}
.stat .v.acc{color:var(--accent2)}.stat .v.green{color:#56D364}.stat .v.bad{color:var(--danger)}
.note{font-size:12px;color:var(--dim);line-height:1.8}
.note b{color:var(--sub)}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="logo"><svg viewBox="0 0 24 24" width="23" height="23" fill="none" stroke="#3FB950" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg></div>
    <div><h1>图片批量压缩工具</h1><div class="sub">Python 引擎批量处理 · 实时进度条 + 命令行日志 · 图片不上传</div></div>
  </header>

  <div class="card">
    <h2>1. 文件夹</h2>
    <div class="grid2">
      <div><label class="blk">源文件夹（含子目录）</label>
        <div class="pathrow"><input type="text" id="src" placeholder="点击右侧按钮选择"><button class="btn btn-g" id="btnSrc">选择…</button></div>
      </div>
      <div><label class="blk">输出文件夹（留空自动生成）</label>
        <div class="pathrow"><input type="text" id="out" placeholder="留空 = 源文件夹_compressed"><button class="btn btn-g" id="btnOut">选择…</button></div>
      </div>
    </div>
  </div>

  <div class="card">
    <h2>2. 压缩设置</h2>
    <div class="grid2">
      <div><label class="blk">输出格式</label>
        <div class="seg" id="segFmt"><button data-v="webp" class="on">WebP</button><button data-v="jpg">JPG</button><button data-v="png">PNG</button></div>
      </div>
      <div><label class="blk">质量（WebP/JPG 有效）</label>
        <div class="quality-row"><input type="range" id="quality" min="10" max="100" value="80"><span class="qnum" id="qval">80</span></div>
      </div>
      <div><label class="blk">最长边限制（px，0=不缩放）</label><input type="number" id="maxEdge" value="0" min="0" step="100"></div>
      <div><label class="blk">并发线程数（电脑不错可调大）</label><input type="number" id="threads" value="4" min="1" max="32"></div>
    </div>
    <div class="checks" style="margin-top:13px">
      <label><input type="checkbox" id="force"> 覆盖已存在的输出（默认跳过，断点续跑）</label>
      <label><input type="checkbox" id="delOrig"> 转换成功后删除原图（危险，慎用）</label>
      <label><input type="checkbox" id="minSize"> 只压大于 100KB 的图</label>
    </div>
  </div>

  <div class="card">
    <h2>3. 处理</h2>
    <div class="actionbar">
      <button class="btn btn-g" id="btnPrev">预览统计</button>
      <button class="btn btn-p" id="btnRun">开始压缩</button>
      <button class="btn btn-r" id="btnStop" disabled>停止</button>
      <span class="hint" id="hint"></span>
    </div>
    <div class="progress" id="progress">
      <div class="pbar"><div class="pfill" id="pfill"></div></div>
      <div class="pinfo"><span id="ptext">等待开始…</span><span id="ppercent">0%</span></div>
    </div>
    <div class="stats" id="stats">
      <div class="stat"><div class="v" id="sOrig">0</div><div class="k">压缩前</div></div>
      <div class="stat"><div class="v acc" id="sNew">0</div><div class="k">压缩后</div></div>
      <div class="stat"><div class="v green" id="sSave">0</div><div class="k">共节省</div></div>
      <div class="stat"><div class="v acc" id="sPct">0%</div><div class="k">节省比例</div></div>
    </div>
  </div>

  <div class="card">
    <h2>4. 命令行日志</h2>
    <div class="terminal">
      <div class="term-bar"><span class="dot t1"></span><span class="dot t2"></span><span class="dot t3"></span><span class="title">batch_compress.py — 实时输出</span></div>
      <div class="term-body" id="term"></div>
    </div>
  </div>

  <div class="card">
    <h2>说明</h2>
    <div class="note">
      <p><b>本工具为桌面窗口版</b>：双击启动文件即打开本页面，底层用 Python 批量处理，支持几千上万张图片，处理中断后重跑会自动跳过已完成文件（断点续跑）。</p>
      <p><b>输出位置</b>：建议单独选一个输出文件夹；输出会保留源文件夹的子目录结构。WebP 在 Chrome/Edge/Firefox/新版 PS 可打开，极老软件打不开请改选 JPG。</p>
    </div>
  </div>
</div>

<script>
"use strict";
const $ = id => document.getElementById(id);
const term = $('term'), toast = $('toast');
let fmt = 'webp', polling = false, started = false;

function esc(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function fmtBytes(n){
  if(n == null) return '—';
  if(n < 1024) return n + ' B';
  if(n < 1048576) return (n/1024).toFixed(1) + ' KB';
  return (n/1048576).toFixed(2) + ' MB';
}
function params(){
  return {
    src: $('src').value.trim(),
    out: $('out').value.trim(),
    format: fmt,
    quality: +$('quality').value,
    max_edge: Math.max(0, +$('maxEdge').value || 0),
    threads: Math.min(32, Math.max(1, +$('threads').value || 4)),
    force: $('force').checked,
    delete_original: $('delOrig').checked,
    min_size: $('minSize').checked ? 102400 : 0,
  };
}
function showToast(m){
  toast.textContent = m; toast.classList.add('show');
  clearTimeout(window._tt); window._tt = setTimeout(() => toast.classList.remove('show'), 2800);
}
function appendLogs(lines){
  if(!lines || !lines.length) return;
  const auto = term.scrollTop + term.clientHeight >= term.scrollHeight - 30;
  for(const l of lines){
    const div = document.createElement('div');
    if(/\[错误\]|失败/.test(l)) div.className = 'err';
    else if(/跳过|已删除|停止/.test(l)) div.className = 'warn';
    else if(/汇总|成功|原大小|耗时/.test(l)) div.className = 'dim';
    div.textContent = l;
    term.appendChild(div);
  }
  while(term.children.length > 3000) term.removeChild(term.firstChild);
  if(auto) term.scrollTop = term.scrollHeight;
}
function setProgress(done, total){
  const pct = total ? Math.round(done/total*100) : 0;
  $('pfill').style.width = pct + '%';
  $('ppercent').textContent = pct + '%';
  $('ptext').textContent = total ? '正在处理 ' + done + ' / ' + total + ' 张…' : '准备中…';
}

$('segFmt').addEventListener('click', e => {
  const b = e.target.closest('button'); if(!b) return;
  fmt = b.dataset.v;
  [...$('segFmt').children].forEach(x => x.classList.toggle('on', x === b));
});
$('quality').addEventListener('input', e => $('qval').textContent = e.target.value);

$('btnSrc').addEventListener('click', async () => {
  const r = await pywebview.api.pick('folder');
  if(r) $('src').value = r;
});
$('btnOut').addEventListener('click', async () => {
  const r = await pywebview.api.pick('folder');
  if(r) $('out').value = r;
});

$('btnPrev').addEventListener('click', async () => {
  const p = params();
  if(!p.src){ showToast('请先选择源文件夹'); return; }
  try{
    const r = await pywebview.api.preview(p);
    if(r.error) showToast(r.error);
    else showToast('发现 ' + r.count + ' 张图片，总大小 ' + fmtBytes(r.total_size));
  }catch(e){ showToast('预览失败'); }
});

$('btnRun').addEventListener('click', async () => {
  const p = params();
  if(!p.src){ showToast('请先选择源文件夹'); return; }
  if(started && !confirm('当前任务尚未完成，确定重新开始吗？')) return;
  try{
    const r = await pywebview.api.start(p);
    if(r.error){ showToast(r.error); return; }
    started = true;
    term.innerHTML = '';
    $('stats').classList.remove('show');
    $('progress').classList.add('show'); setProgress(0, 0);
    $('btnRun').disabled = true; $('btnPrev').disabled = true; $('btnStop').disabled = false;
    if(!polling) poll();
  }catch(e){ showToast('启动失败'); }
});

$('btnStop').addEventListener('click', async () => {
  try{ await pywebview.api.stop(); showToast('已发送停止请求'); }
  catch(e){ showToast('取消失败'); }
});

async function poll(){
  if(polling) return; polling = true;
  try{
    const r = await pywebview.api.get_status();
    appendLogs(r.logs);
    setProgress(r.done, r.total);
    if(r.running){ setTimeout(poll, 700); }
    else{
      $('progress').classList.remove('show');
      $('btnRun').disabled = false; $('btnPrev').disabled = false; $('btnStop').disabled = true;
      if(r.stats.ok){
        const st = r.stats, saved = st.orig - st.new;
        const pct = st.orig ? Math.round(saved/st.orig*100) : 0;
        $('sOrig').textContent = fmtBytes(st.orig);
        $('sNew').textContent = fmtBytes(st.new);
        $('sSave').textContent = (saved>=0?'节省 ':'增大 ') + fmtBytes(Math.abs(saved));
        $('sPct').textContent = pct + '%';
        $('sSave').className = 'v ' + (saved>=0?'green':'bad');
        $('sPct').className = 'v acc' + (saved>=0?'':' bad');
        $('stats').classList.add('show');
      }
    }
  }catch(e){ setTimeout(poll, 1500); }
  polling = false;
}
setTimeout(poll, 500);
</script>
<div id="toast" style="position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:var(--bg3);border:1px solid var(--line2);color:var(--text);padding:10px 20px;border-radius:10px;font-size:13px;opacity:0;pointer-events:none;transition:all .25s;z-index:99;display:none"></div>
</body>
</html>
"""


# ================= pywebview 桥接 =================
import webview


class Api:
    def pick(self, kind):
        try:
            win = webview.windows[0]
            result = win.create_file_dialog(webview.FOLDER_DIALOG)
            if result and len(result) > 0:
                return result[0]
        except Exception:
            pass
        return None

    def preview(self, p):
        src = (p.get("src") or "").strip()
        if not src or not os.path.isdir(src):
            return {"error": "源文件夹不存在或路径无效"}
        try:
            files = collect_files(Path(src), int(p.get("min_size") or 0))
            total = sum(f.stat().st_size for f in files)
            return {"count": len(files), "total_size": total}
        except Exception as e:
            return {"error": str(e)[:120]}

    def start(self, p):
        with LOCK:
            if STATE["running"]:
                return {"error": "已有任务在运行中"}
        src = (p.get("src") or "").strip()
        if not src or not os.path.isdir(src):
            return {"error": "源文件夹不存在或路径无效"}
        out = (p.get("out") or "").strip()
        if not out:
            out = src.rstrip("\\/") + "_compressed"
        if os.path.abspath(out) == os.path.abspath(src):
            return {"error": "输出文件夹不能等于源文件夹"}
        params = {
            "src": src, "out": out,
            "format": p.get("format", "webp") if p.get("format", "webp") in FMT_EXT else "webp",
            "quality": max(1, min(100, int(p.get("quality") or 80))),
            "max_edge": max(0, int(p.get("max_edge") or 0)),
            "threads": max(1, min(32, int(p.get("threads") or 4))),
            "force": bool(p.get("force")),
            "delete_original": bool(p.get("delete_original")),
            "min_size": max(0, int(p.get("min_size") or 0)),
        }
        threading.Thread(target=run_task, args=(params,), daemon=True).start()
        return {"ok": True}

    def stop(self):
        with LOCK:
            STATE["stop"] = True
        return {"ok": True}

    def get_status(self):
        with LOCK:
            total = STATE["total"]
            done = STATE["done"]
            new_logs = STATE["logs"][STATE["since"]:]
            STATE["since"] = len(STATE["logs"])
            return {
                "running": STATE["running"],
                "done": done,
                "total": total,
                "logs": new_logs,
                "stats": dict(STATE["stats"]),
            }


def main():
    api = Api()
    window = webview.create_window(
        "图片批量压缩工具",
        html=HTML,
        js_api=api,
        width=1020,
        height=800,
        min_size=(820, 620),
        background_color="#0D1117",
    )
    webview.start(debug=False)


if __name__ == "__main__":
    main()
