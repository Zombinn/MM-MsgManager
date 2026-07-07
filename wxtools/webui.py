# -*- coding: utf-8 -*-
"""wxtools 简易本地控制台。

单文件 FastAPI 应用 + 内嵌 HTML，无需前端构建步骤。重操作（合并/导出）在
后台线程运行，前端轮询日志，保证界面不卡。仅监听本机，供个人使用。
"""
from __future__ import annotations

import io
import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from . import context, pipeline, audio

# ------------------------- 后台任务管理 ------------------------- #

_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()

# 线程 -> job_id 的登记表。注意：不能用 contextlib.redirect_stdout 逐线程替换
# sys.stdout —— 它是进程级全局属性，后台线程持有它的窗口内会连主线程/其他
# 请求线程的 print 一并吞掉。这里改为「按当前线程路由」的单例代理，
# 全局只安装一次，写入时查登记表决定落到哪个任务日志，查不到则转发真实终端。
_THREAD_JOBS: dict[int, str] = {}
_REAL_STDOUT = sys.stdout


class _ThreadRoutingStdout(io.TextIOBase):
    """按当前线程路由的 stdout 单例代理。

    任务线程的输出追加进对应任务日志；其余线程（主线程、其他并发请求）
    的输出照常转发到真实终端，互不干扰。
    """

    def write(self, s: str) -> int:
        if not s:
            return 0
        job_id = _THREAD_JOBS.get(threading.get_ident())
        if job_id is None:
            _REAL_STDOUT.write(s)
        elif s != "\n":  # print() 末尾的单独 "\n" 不追加成空行
            with _LOCK:
                job = _JOBS.get(job_id)
                if job is not None:
                    job["log"].append(s.rstrip("\n"))
        return len(s)

    def flush(self) -> None:
        _REAL_STDOUT.flush()


def _install_stdout_router() -> None:
    if not isinstance(sys.stdout, _ThreadRoutingStdout):
        sys.stdout = _ThreadRoutingStdout()


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with _LOCK:
        _JOBS[job_id] = {"status": "running", "log": [], "returncode": None,
                         "started": datetime.now().strftime("%H:%M:%S")}
    return job_id


def _run_async(job_id: str, fn) -> None:
    _install_stdout_router()

    def worker():
        tid = threading.get_ident()
        _THREAD_JOBS[tid] = job_id
        try:
            fn()
            with _LOCK:
                _JOBS[job_id]["status"] = "done"
                _JOBS[job_id]["returncode"] = 0
        except SystemExit as e:
            with _LOCK:
                _JOBS[job_id]["log"].append(str(e.code) if e.code else "")
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["returncode"] = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001 - 任何异常都回显到界面
            with _LOCK:
                _JOBS[job_id]["log"].append(f"[-] 异常: {e}")
                _JOBS[job_id]["status"] = "error"
                _JOBS[job_id]["returncode"] = 1
        finally:
            _THREAD_JOBS.pop(tid, None)

    threading.Thread(target=worker, daemon=True).start()


# ------------------------- FastAPI 应用 ------------------------- #

def create_app():
    from fastapi import FastAPI, Body
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="wxtools UI", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return _HTML

    @app.get("/api/status")
    def status():
        context.setup_env()
        try:
            acct = context.load_account()
        except SystemExit as e:
            return JSONResponse({"ok": False, "error": str(e.code)})
        peer = context.load_defaults().get("peer_wxid") or os.environ.get("WXTOOLS_PEER", "")
        return {
            "ok": True,
            "my_wxid": acct.my_wxid,
            "peer_wxid": peer,
            "merge_path": acct.merge_path,
            "merge_exists": bool(acct.merge_path and os.path.isfile(acct.merge_path)),
            "wx_path": acct.wx_path,
        }

    def _start_job(prep):
        """执行同步准备逻辑（可能抛 SystemExit/ValueError），成功后起后台任务。

        准备阶段的异常在这里被捕获并转成普通错误响应（无 job_id），
        前端按「无 job_id 即视为错误」处理，避免 FastAPI 500。
        """
        try:
            task = prep()
        except (SystemExit, ValueError) as e:
            msg = e.code if isinstance(e, SystemExit) else str(e)
            return {"error": str(msg)}
        job_id = _new_job()
        _run_async(job_id, task)
        return {"job_id": job_id}

    @app.post("/api/refresh")
    def api_refresh(peer_wxid: str = Body("", embed=True),
                    merge_only: bool = Body(False, embed=True),
                    export_only: bool = Body(False, embed=True)):
        def prep():
            context.setup_env()
            acct = context.load_account()
            # merge-only 不涉及具体联系人，避免强制要求配置默认 peer_wxid
            peer = None if merge_only else context.resolve_peer(peer_wxid or None)

            def task():
                if not os.path.isfile(acct.merge_path):
                    raise SystemExit(f"[-] merge_all.db 不存在: {acct.merge_path}")
                if not export_only:
                    from . import wechat
                    print("[*] 尝试实时合并（微信开着也可以，读取运行中进程数据）...")
                    ok, msg = pipeline.merge_realtime(acct)
                    print(f"[+] 实时合并成功: {msg}" if ok else
                          f"[!] 实时合并跳过/失败（不影响后续常规合并）: {msg}")
                    if wechat.warn_wal_files(acct.wx_path):
                        print("[*] 仍将尝试合并；若缺新消息，请退出微信后重试。")
                    print("[*] 合并 MSG 分库 ...")
                    n = pipeline.merge_msg_shards(acct)
                    print(f"[+] 共处理 {n} 个分库")
                if not merge_only:
                    print(f"[*] 导出 CSV: {peer}")
                    pipeline.export_contact_csv(acct, peer)
                print("[+] 完成")

            return task

        return _start_job(prep)

    @app.post("/api/realtime")
    def api_realtime():
        def task():
            context.setup_env()
            acct = context.load_account()
            print("[*] 实时合并中（微信可以继续开着）...")
            ok, msg = pipeline.merge_realtime(acct)
            if not ok:
                raise SystemExit(f"[-] 实时合并失败: {msg}")
            print(f"[+] 实时合并成功: {msg}")

        job_id = _new_job()
        _run_async(job_id, task)
        return {"job_id": job_id}

    @app.post("/api/voices")
    def api_voices(peer_wxid: str = Body("", embed=True),
                   since: str = Body("", embed=True),
                   all_time: bool = Body(False, embed=True),
                   speaker: str = Body("all", embed=True)):
        def prep():
            context.setup_env()
            acct = context.load_account()
            peer = context.resolve_peer(peer_wxid or None)
            since_dt = None
            if not all_time:
                since_dt = datetime.strptime(since.strip()[:10], "%Y-%m-%d") if since \
                    else datetime(datetime.now().year, 4, 1)

            def task():
                csv_dir = acct.csv_dir(peer)
                if not csv_dir.is_dir():
                    raise SystemExit(f"[-] CSV 目录不存在: {csv_dir}（请先 refresh）")
                safe = "".join(c if c.isalnum() or c in "_-" else "_" for c in peer)
                suffix = "all" if since_dt is None else f"since_{since_dt.strftime('%Y%m%d')}"
                out_dir = acct.export_dir / f"voices_{safe}_{speaker}_{suffix}"
                msgs = pipeline.iter_csv_messages(csv_dir, peer)
                voices = pipeline.filter_voice_messages(msgs, peer, since_dt, speaker)
                print(f"[*] 待导出语音: {len(voices)} 条 -> {out_dir}")
                ok, fail = pipeline.export_voices(acct, peer, voices, out_dir)
                print(f"[+] 成功 {ok}, 失败 {fail}")

            return task

        return _start_job(prep)

    @app.post("/api/concat")
    def api_concat(input_dir: str = Body(..., embed=True),
                   output: str = Body(..., embed=True),
                   gap_ms: int = Body(0, embed=True)):
        def task():
            n, dur = audio.concat_wavs(Path(input_dir), Path(output), gap_ms)
            print(f"[+] 共 {n} 条，时长约 {dur:.1f} 秒 -> {output}")

        job_id = _new_job()
        _run_async(job_id, task)
        return {"job_id": job_id}

    @app.get("/api/job/{job_id}")
    def job(job_id: str):
        with _LOCK:
            j = _JOBS.get(job_id)
            if not j:
                return JSONResponse({"error": "job not found"}, status_code=404)
            return {"status": j["status"], "returncode": j["returncode"], "log": list(j["log"])}

    return app


def start(port: int = 5001, open_browser: bool = True) -> None:
    import uvicorn

    context.setup_env()
    url = f"http://127.0.0.1:{port}/"
    print(f"[+] wxtools 控制台: {url}")
    if open_browser:
        import webbrowser
        with contextlib.suppress(Exception):
            webbrowser.open(url)
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning")


_HTML = """<!doctype html>
<html lang=\"zh-CN\"><head><meta charset=\"utf-8\">
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">
<title>wxtools 控制台</title>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--line:#2a2f3a;--fg:#e6e8ee;--mut:#8b90a0;--acc:#4c8bf5;--ok:#39c07a;--err:#e5534b}
 *{box-sizing:border-box}
 body{margin:0;font:14px/1.6 system-ui,\"Segoe UI\",\"Microsoft YaHei\",sans-serif;background:var(--bg);color:var(--fg)}
 header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;align-items:center;gap:12px}
 header h1{font-size:17px;margin:0;font-weight:600}
 .badge{font-size:12px;color:var(--mut);background:var(--card);border:1px solid var(--line);padding:2px 8px;border-radius:20px}
 main{max-width:920px;margin:0 auto;padding:24px;display:grid;gap:16px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px}
 .card h2{margin:0 0 12px;font-size:14px;font-weight:600}
 .row{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
 label{color:var(--mut);font-size:13px}
 input,select{background:var(--bg);border:1px solid var(--line);color:var(--fg);border-radius:7px;padding:7px 10px;font:inherit}
 input{min-width:200px}
 button{background:var(--acc);color:#fff;border:0;border-radius:7px;padding:8px 16px;font:inherit;cursor:pointer}
 button.sec{background:transparent;border:1px solid var(--line);color:var(--fg)}
 button:disabled{opacity:.5;cursor:not-allowed}
 .grid2{display:grid;grid-template-columns:auto 1fr;gap:8px 14px;align-items:center;font-size:13px}
 .grid2 .k{color:var(--mut)}
 pre{background:#0a0c10;border:1px solid var(--line);border-radius:8px;padding:12px;margin:12px 0 0;max-height:300px;overflow:auto;font:12px/1.5 \"Cascadia Code\",Consolas,monospace;white-space:pre-wrap}
 .dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:6px;background:var(--mut)}
 .dot.run{background:var(--acc);animation:pulse 1s infinite}
 .dot.done{background:var(--ok)} .dot.err{background:var(--err)}
 @keyframes pulse{50%{opacity:.3}}
</style></head><body>
<header><h1>wxtools 控制台</h1><span class=\"badge\" id=\"acct\">加载中…</span></header>
<main>
 <div class=\"card\">
  <h2>账号状态</h2>
  <div class=\"grid2\" id=\"status\"><span class=\"k\">读取中</span><span>…</span></div>
 </div>
 <div class=\"card\">
  <h2>① 刷新聊天记录（合并最新 MSG → 导出 CSV）</h2>
  <div class=\"row\">
   <label>联系人 wxid</label><input id=\"r_peer\" placeholder=\"留空用默认\">
   <button onclick=\"run('refresh',{peer_wxid:v('r_peer')})\">合并并导出</button>
   <button class=\"sec\" onclick=\"run('refresh',{peer_wxid:v('r_peer'),merge_only:true})\">仅合并</button>
   <button class=\"sec\" onclick=\"run('refresh',{peer_wxid:v('r_peer'),export_only:true})\">仅导出</button>
   <button class=\"sec\" onclick=\"run('realtime',{})\">实时合并（微信开着也可）</button>
  </div>
  <p style=\"color:var(--mut);font-size:12px;margin:10px 0 0\">
   手机上刚发的消息导不出来？两种情况：① 微信开着、消息还没落盘 —— 点「实时合并」
   或退出微信后重试；② 消息还没同步到这台电脑 —— 先在微信里打开该对话等它同步，
   再重新刷新。刷新完成后日志里会显示该会话本地最新消息时间，可据此比对。
  </p>
 </div>
 <div class=\"card\">
  <h2>② 导出语音（从 CSV 筛语音 → WAV）</h2>
  <div class=\"row\">
   <label>联系人</label><input id=\"v_peer\" placeholder=\"留空用默认\">
   <label>起始日期</label><input id=\"v_since\" placeholder=\"2026-04-01\" style=\"min-width:120px\">
   <label>发言人</label>
   <select id=\"v_speaker\"><option value=\"all\">全部</option><option value=\"peer\">仅对方</option><option value=\"self\">仅自己</option></select>
   <button onclick=\"runVoices()\">导出语音</button>
  </div>
 </div>
 <div class=\"card\">
  <h2>③ 拼接语音（目录内 WAV 按时间合成一条）</h2>
  <div class=\"row\">
   <label>输入目录</label><input id=\"c_in\" placeholder=\"wxdump_work/export/.../voices_...\">
   <label>输出</label><input id=\"c_out\" placeholder=\"merged.wav\">
   <button onclick=\"run('concat',{input_dir:v('c_in'),output:v('c_out'),gap_ms:0})\">拼接</button>
  </div>
 </div>
 <div class=\"card\">
  <h2><span class=\"dot\" id=\"dot\"></span>运行日志</h2>
  <pre id=\"log\">就绪。</pre>
 </div>
</main>
<script>
const $=id=>document.getElementById(id);
const v=id=>$(id).value.trim();
let timer=null;
async function loadStatus(){
 try{
  const r=await fetch('/api/status');const d=await r.json();
  if(!d.ok){$('acct').textContent='未初始化';$('status').innerHTML='<span class=\"k\">提示</span><span>请先运行 wxdump ui 初始化账号</span>';return;}
  $('acct').textContent=d.my_wxid;
  $('status').innerHTML=
   `<span class=\"k\">当前账号</span><span>${d.my_wxid}</span>`+
   `<span class=\"k\">默认联系人</span><span>${d.peer_wxid||'（未设置）'}</span>`+
   `<span class=\"k\">合并库</span><span>${d.merge_exists?'✅ ':'❌ '}${d.merge_path||''}</span>`;
  if(d.peer_wxid){$('r_peer').placeholder=d.peer_wxid;$('v_peer').placeholder=d.peer_wxid;}
 }catch(e){$('acct').textContent='服务异常';}
}
function setDot(s){const d=$('dot');d.className='dot '+(s==='running'?'run':s==='done'?'done':s==='error'?'err':'');}
async function poll(id){
 const r=await fetch('/api/job/'+id);const d=await r.json();
 $('log').textContent=d.log.join('\\n')||'(无输出)';
 $('log').scrollTop=$('log').scrollHeight;setDot(d.status);
 if(d.status==='running'){timer=setTimeout(()=>poll(id),700);}else{buttons(false);loadStatus();}
}
function buttons(dis){document.querySelectorAll('button').forEach(b=>b.disabled=dis);}
async function run(cmd,body){
 buttons(true);setDot('running');$('log').textContent='启动中…';
 try{
  const r=await fetch('/api/'+cmd,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(d.job_id){poll(d.job_id);}else{$('log').textContent=JSON.stringify(d,null,2);buttons(false);setDot('error');}
 }catch(e){$('log').textContent='请求失败: '+e;buttons(false);setDot('error');}
}
function runVoices(){run('voices',{peer_wxid:v('v_peer'),since:v('v_since'),all_time:false,speaker:v('v_speaker')});}
loadStatus();
</script>
</body></html>"""
