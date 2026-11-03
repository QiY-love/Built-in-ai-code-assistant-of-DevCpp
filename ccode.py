#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccode — 给 Dev-C++ 5.11 用的 AI 代码助手（DeepSeek 后端）。

模式:
  gen        描述需求 -> 生成 C 代码 -> 预览 -> 插入编辑器
  complete   用编辑器里选中的代码作为上下文，续写/补全
  config     填写 API key、模型等设置

Dev-C++ 外部工具参数示例:
  gen --file "<SOURCEPATH><SOURCENAME>" --wordxy <WORDXY>
  complete --file "<SOURCEPATH><SOURCENAME>" --wordxy <WORDXY>

调试:
  --mock     不联网，用固定代码验证界面与插入流程
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
from tkinter import font as tkfont
from tkinter import ttk

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "ccode.json")

DEFAULTS = {
    "api_key": "",
    "base_url": "https://api.deepseek.com/v1",
    "model": "deepseek-chat",
    "temperature": 0.2,
    "max_tokens": 2048,
    "timeout": 120,
    # 留空即按进程名 devcpp.exe 自动查找窗口，无需填安装路径
    "devcpp_exe": "",
    "context_chars": 4000,
}

PROMPT_GEN = (
    "你是 C 语言代码助手，服务对象是正在做课程作业的中国大学生。\n"
    "规则：\n"
    "1. 只输出最终代码本身，不要解释、不要 Markdown 代码围栏、不要空话。\n"
    "2. 用标准 C（C99/C11），gcc 可直接编译，必要时写全 #include。\n"
    "3. 代码要能独立运行：有 main 就完整，写函数就完整可调用。\n"
    "4. 关键处加简短中文注释。\n"
)

PROMPT_COMPLETE = (
    "你在帮我写 C 代码。下面是编辑器里已有的内容，光标在它的末尾。\n"
    "只输出「紧接着要插入」的那部分代码，不要重复已有内容，不要解释，"
    "不要 Markdown 代码围栏。若已有代码停在半句，就把它补完。\n"
)

# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------


def load_config():
    cfg = dict(DEFAULTS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg.update(json.load(f) or {})
        except Exception as e:  # 配置坏了不该拦住用户
            print("配置文件读取失败:", e, file=sys.stderr)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------
# Win32：剪贴板 / 找窗口 / 发按键
# --------------------------------------------------------------------------

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL, VK_C, VK_V, VK_RETURN, VK_ESCAPE = 0x11, 0x43, 0x56, 0x0D, 0x1B

u32.OpenClipboard.argtypes = [wt.HWND]
u32.OpenClipboard.restype = wt.BOOL
u32.GetClipboardData.argtypes = [wt.UINT]
u32.GetClipboardData.restype = ctypes.c_void_p
u32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
u32.SetClipboardData.restype = ctypes.c_void_p
k32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
k32.GlobalAlloc.restype = ctypes.c_void_p
k32.GlobalLock.argtypes = [ctypes.c_void_p]
k32.GlobalLock.restype = ctypes.c_void_p
k32.GlobalUnlock.argtypes = [ctypes.c_void_p]
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = ctypes.c_void_p
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]


def get_clipboard():
    for _ in range(12):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return ""
    try:
        h = u32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        p = k32.GlobalLock(h)
        if not p:
            return ""
        try:
            return ctypes.wstring_at(p)
        finally:
            k32.GlobalUnlock(h)
    finally:
        u32.CloseClipboard()


def set_clipboard(text):
    """写入系统剪贴板（进程退出后内容仍在，tkinter 自己做不到这点）。"""
    data = (text or "").encode("utf-16-le") + b"\x00\x00"
    for _ in range(12):
        if u32.OpenClipboard(None):
            break
        time.sleep(0.02)
    else:
        return False
    try:
        u32.EmptyClipboard()
        h = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = k32.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        return True
    finally:
        u32.CloseClipboard()


def _window_exe(hwnd):
    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = k32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        k32.CloseHandle(h)


def find_devcpp_window(cfg):
    """找到 Dev-C++ 主窗口句柄。"""
    want = os.path.basename(cfg.get("devcpp_exe") or "devcpp.exe").lower()
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _):
        if u32.IsWindowVisible(hwnd) and u32.GetWindowTextLengthW(hwnd) > 0:
            if _window_exe(hwnd) == want:
                found.append(hwnd)
                return False
        return True

    u32.EnumWindows(cb, 0)
    return found[0] if found else None


def activate(hwnd):
    if not hwnd:
        return False
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    u32.SetForegroundWindow(hwnd)
    time.sleep(0.12)
    return u32.GetForegroundWindow() == hwnd


def send_ctrl(vk):
    u32.keybd_event(VK_CONTROL, 0, 0, 0)
    u32.keybd_event(vk, 0, 0, 0)
    u32.keybd_event(vk, 0, 0x0002, 0)
    u32.keybd_event(VK_CONTROL, 0, 0x0002, 0)


# --------------------------------------------------------------------------
# DeepSeek 调用
# --------------------------------------------------------------------------


def clean_code(text):
    """去掉模型偶尔自带的 Markdown 围栏和客套话。"""
    t = (text or "").strip()
    m = re.search(r"```[a-zA-Z0-9+#]*\n?(.*?)```", t, re.S)
    if m:
        t = m.group(1)
    lines = t.splitlines()
    while lines and lines[0].strip().startswith("```"):
        lines.pop(0)
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip("\n")


def api_chat(cfg, messages):
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    body = json.dumps({
        "model": cfg["model"],
        "messages": messages,
        "temperature": cfg.get("temperature", 0.2),
        "max_tokens": cfg.get("max_tokens", 2048),
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + cfg["api_key"].strip(),
    })
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 120)) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", "ignore")[:400]
        except Exception:
            pass
        if e.code == 401:
            raise RuntimeError("API key 无效或已过期（HTTP 401）。请重新运行 `ccode config` 填写。")
        if e.code == 402:
            raise RuntimeError("DeepSeek 账户余额不足（HTTP 402），请先充值。")
        if e.code == 429:
            raise RuntimeError("请求太频繁被限流（HTTP 429），等几秒再试。")
        raise RuntimeError("接口返回 HTTP %d: %s" % (e.code, detail))
    except urllib.error.URLError as e:
        raise RuntimeError("连不上 %s（%s）。检查网络或 base_url。" % (url, e.reason))
    try:
        return data["choices"][0]["message"]["content"]
    except Exception:
        raise RuntimeError("返回格式异常: %s" % json.dumps(data, ensure_ascii=False)[:300])


# --------------------------------------------------------------------------
# 上下文获取
# --------------------------------------------------------------------------


def context_from_file(path, line=None, chars=4000):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    if line and line > 0:
        lines = text.splitlines()
        text = "\n".join(lines[:line])
    return text[-chars:]


def grab_selection_via_copy(cfg, wait=0.25):
    """模拟 Ctrl+C 取编辑器选中内容。返回空串表示没选中。"""
    set_clipboard("\x00ccode-empty")  # 哨兵：区分“没选中”和“剪贴板旧内容”
    hwnd = u32.GetForegroundWindow()
    exe = _window_exe(hwnd)
    want = os.path.basename(cfg.get("devcpp_exe") or "devcpp.exe").lower()
    if exe != want:
        hwnd = find_devcpp_window(cfg)
        if not hwnd:
            return ""
        activate(hwnd)
    send_ctrl(VK_C)
    time.sleep(wait)
    got = get_clipboard()
    return "" if got.strip() == "\x00ccode-empty" else got


# --------------------------------------------------------------------------
# 界面
# --------------------------------------------------------------------------


class App:
    def __init__(self, root, mode, cfg, args):
        self.root = root
        self.mode = mode
        self.cfg = cfg
        self.args = args
        self.q = queue.Queue()
        self.result = None
        self.busy = False

        root.title("AI 代码助手 — " + ("生成代码" if mode == "gen" else "补全代码"))
        root.configure(bg="#f5f5f5")
        root.attributes("-topmost", True)
        root.resizable(True, True)

        self.mono = tkfont.Font(family="Consolas", size=11)
        self.ui = tkfont.Font(family="Microsoft YaHei UI", size=10)

        self._build_input()
        self._poll()

    # ---------- 输入阶段 ----------
    def _build_input(self):
        wrap = tk.Frame(self.root, bg="#f5f5f5", padx=14, pady=12)
        wrap.pack(fill="both", expand=True)

        hint = ("描述你想要的 C 代码，回车生成。\n"
                "也可以粘贴一段代码让 AI 改写；留空则补全编辑器里选中的内容。"
                if self.mode == "gen" else
                "编辑器里选中的代码会作为上下文自动带入。\n"
                "也可以在这里补充要求（比如“用递归重写”），回车生成。")
        tk.Label(wrap, text=hint, bg="#f5f5f5", fg="#555",
                 font=self.ui, justify="left").pack(anchor="w", pady=(0, 8))

        self.text = tk.Text(wrap, height=7, width=78, font=self.mono,
                            undo=True, wrap="word", relief="solid", bd=1,
                            highlightthickness=0, padx=8, pady=6)
        self.text.pack(fill="both", expand=True)
        self.text.focus_set()

        bar = tk.Frame(wrap, bg="#f5f5f5")
        bar.pack(fill="x", pady=(10, 0))
        self.status = tk.Label(bar, text="Ctrl+Enter 生成   Esc 取消",
                               bg="#f5f5f5", fg="#888", font=self.ui)
        self.status.pack(side="left")

        self.btn_go = ttk.Button(bar, text="生成", command=self.start)
        self.btn_go.pack(side="right")
        ttk.Button(bar, text="取消", command=self.root.destroy).pack(side="right", padx=6)

        for seq in ("<Control-Return>", "<Control-KP_Enter>"):
            self.root.bind(seq, lambda e: self.start())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)

        # 补全模式：先把编辑器选中内容抓过来当上下文
        if self.mode == "complete":
            self.ctx = self._load_context()
            if self.ctx:
                self.text.insert("1.0", "（已读取选中代码 %d 字符）" % len(self.ctx))
                self.text.tag_add("hint", "1.0", "end")
                self.text.tag_config("hint", foreground="#999")
                self.text.mark_set("insert", "end-1c")

    def _load_context(self):
        a = self.args
        if getattr(a, "file", None):
            path = os.path.expandvars(a.file.strip().strip('"'))
            if os.path.isfile(path):
                line = None
                if getattr(a, "wordxy", None):
                    nums = re.findall(r"\d+", a.wordxy)
                    if nums:
                        line = int(nums[0])
                ctx = context_from_file(path, line, self.cfg.get("context_chars", 4000))
                if ctx.strip():
                    self._ctx_source = "文件 %s" % os.path.basename(path)
                    return ctx
        sel = grab_selection_via_copy(self.cfg)
        self._ctx_source = "编辑器选中内容"
        return sel.strip()

    def _user_text(self):
        t = self.text.get("1.0", "end-1c").strip()
        if t.startswith("（已读取选中代码"):
            t = ""
        return t

    # ---------- 生成阶段 ----------
    def start(self):
        if self.busy:
            return
        user = self._user_text()
        ctx = getattr(self, "ctx", "") if self.mode == "complete" else ""
        if not user and not ctx:
            self.status.config(text="写点需求，或者先在编辑器里选中要补全的代码", fg="#c0392b")
            return
        if not self.cfg.get("api_key") and not self.args.mock:
            self.status.config(text="还没配置 API key，先运行 ccode config", fg="#c0392b")
            return

        parts = []
        if ctx:
            parts.append("已有代码（光标在末尾）：\n```c\n" + ctx + "\n```")
        if user:
            parts.append("我的要求：" + user)
        prompt = "\n\n".join(parts)

        if self.mode == "complete":
            messages = [{"role": "system", "content": PROMPT_COMPLETE},
                        {"role": "user", "content": prompt}]
        else:
            messages = [{"role": "system", "content": PROMPT_GEN},
                        {"role": "user", "content": prompt}]

        self.busy = True
        self.btn_go.config(state="disabled")
        self.status.config(text="生成中…", fg="#2980b9")

        def work():
            try:
                if self.args.mock:
                    time.sleep(0.6)
                    code = MOCK_CODE
                else:
                    code = clean_code(api_chat(self.cfg, messages))
                self.q.put(("ok", code))
            except Exception as e:
                self.q.put(("err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "ok":
                    self._show_preview(payload)
                else:
                    self.busy = False
                    self.btn_go.config(state="normal")
                    self.status.config(text=payload, fg="#c0392b")
        except queue.Empty:
            pass
        self.root.after(80, self._poll)

    # ---------- 预览阶段 ----------
    def _show_preview(self, code):
        for w in self.root.winfo_children():
            w.destroy()
        self.result = code
        wrap = tk.Frame(self.root, bg="#f5f5f5", padx=14, pady=12)
        wrap.pack(fill="both", expand=True)

        tk.Label(wrap, text="生成结果 — 看一眼再决定要不要", bg="#f5f5f5",
                 fg="#333", font=self.ui).pack(anchor="w", pady=(0, 6))

        holder = tk.Frame(wrap, relief="solid", bd=1, bg="white")
        holder.pack(fill="both", expand=True)
        view = tk.Text(holder, font=self.mono, wrap="none", padx=8, pady=6,
                       height=20, width=84, bg="white", relief="flat")
        view.insert("1.0", code)
        view.config(state="disabled")
        ys = ttk.Scrollbar(holder, orient="vertical", command=view.yview)
        view.config(yscrollcommand=ys.set)
        ys.pack(side="right", fill="y")
        view.pack(side="left", fill="both", expand=True)

        bar = tk.Frame(wrap, bg="#f5f5f5")
        bar.pack(fill="x", pady=(10, 0))
        tk.Label(bar, text="Ctrl+Enter 插入到编辑器   Esc 丢弃", bg="#f5f5f5",
                 fg="#888", font=self.ui).pack(side="left")
        ttk.Button(bar, text="丢弃", command=self.root.destroy).pack(side="right")
        ttk.Button(bar, text="只复制", command=self._copy).pack(side="right", padx=6)
        ttk.Button(bar, text="插入", command=self._insert).pack(side="right")

        self.root.title("AI 代码助手 — 确认")
        self.root.bind("<Control-Return>", lambda e: self._insert())
        self.root.bind("<Control-KP_Enter>", lambda e: self._insert())
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        self.root.update_idletasks()
        self._center()

    def _copy(self):
        set_clipboard(self.result)
        for w in self.root.winfo_children():
            w.destroy()
        tk.Label(self.root, text="已复制到剪贴板，去编辑器里 Ctrl+V 吧",
                 bg="#f5f5f5", font=self.ui, pady=20).pack()
        self.root.after(1200, self.root.destroy)

    def _insert(self):
        ok_clip = set_clipboard(self.result)
        hwnd = find_devcpp_window(self.cfg)
        if not hwnd:
            self._copy()
            return
        self.root.withdraw()
        self.root.update()
        activate(hwnd)
        time.sleep(0.05)
        send_ctrl(VK_V)
        time.sleep(0.05)
        self.root.destroy()

    def _center(self):
        r = self.root
        r.update_idletasks()
        w, h = max(r.winfo_width(), 640), max(r.winfo_height(), 400)
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        r.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))


MOCK_CODE = """#include <stdio.h>

int main(void) {
    /* 这是 --mock 模式的假代码，用来验证界面与插入流程 */
    printf("Hello from ccode mock\\n");
    return 0;
}
"""


# --------------------------------------------------------------------------
# 配置窗口
# --------------------------------------------------------------------------


def run_config(cfg):
    root = tk.Tk()
    root.title("AI 代码助手 — 设置")
    root.configure(bg="#f5f5f5")
    root.attributes("-topmost", True)
    ui = tkfont.Font(family="Microsoft YaHei UI", size=10)

    frm = tk.Frame(root, bg="#f5f5f5", padx=16, pady=14)
    frm.pack(fill="both", expand=True)
    tk.Label(frm, text="DeepSeek API Key（sk- 开头，只存在本机 ccode.json 里）",
             bg="#f5f5f5", font=ui).grid(row=0, column=0, columnspan=2, sticky="w")
    ent_key = tk.Entry(frm, width=54, font=("Consolas", 10), show="*")
    ent_key.insert(0, cfg.get("api_key", ""))
    ent_key.grid(row=1, column=0, columnspan=2, sticky="we", pady=(4, 12))

    rows = [("接口地址", "base_url"), ("模型", "model")]
    ents = {}
    r = 2
    for label, key in rows:
        tk.Label(frm, text=label, bg="#f5f5f5", font=ui).grid(row=r, column=0, sticky="w")
        e = tk.Entry(frm, width=40, font=("Consolas", 10))
        e.insert(0, str(cfg.get(key, "")))
        e.grid(row=r, column=1, sticky="we", pady=3)
        ents[key] = e
        r += 1

    msg = tk.Label(frm, text="API key 在 platform.deepseek.com 创建；充值 10 块能用很久。",
                   bg="#f5f5f5", fg="#888", font=ui, justify="left")
    msg.grid(row=r, column=0, columnspan=2, sticky="w", pady=(10, 8))

    def save():
        cfg["api_key"] = ent_key.get().strip()
        cfg["base_url"] = ents["base_url"].get().strip() or DEFAULTS["base_url"]
        cfg["model"] = ents["model"].get().strip() or DEFAULTS["model"]
        save_config(cfg)
        msg.config(text="已保存到 " + CONFIG_PATH, fg="#27ae60")
        root.after(900, root.destroy)

    bar = tk.Frame(frm, bg="#f5f5f5")
    bar.grid(row=r + 1, column=0, columnspan=2, sticky="e", pady=(6, 0))
    ttk.Button(bar, text="保存", command=save).pack(side="right")
    ttk.Button(bar, text="关闭", command=root.destroy).pack(side="right", padx=6)
    root.bind("<Escape>", lambda e: root.destroy())
    root.mainloop()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def parse_args(argv):
    p = argparse.ArgumentParser(prog="ccode", add_help=True)
    p.add_argument("mode", nargs="?", default="gen", choices=["gen", "complete", "config", "selftest"])
    p.add_argument("--file", default=None, help="当前源文件路径（Dev-C++ 会传入）")
    p.add_argument("--wordxy", default=None, help="光标位置，Dev-C++ 的 <WORDXY>")
    p.add_argument("--prompt", default=None, help="直接给需求，不弹输入框")
    p.add_argument("--mock", action="store_true", help="不联网，用假代码测试流程")
    return p.parse_args(argv)


def enable_dpi():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            u32.SetProcessDPIAware()
        except Exception:
            pass


def selftest(cfg):
    """不弹窗的自检：检查配置、Win32 能力、能否找到 Dev-C++。"""
    print("配置文件:", CONFIG_PATH, "(存在)" if os.path.exists(CONFIG_PATH) else "(未创建)")
    print("api_key :", "已设置" if cfg.get("api_key") else "未设置")
    print("base_url:", cfg.get("base_url"), "| model:", cfg.get("model"))
    set_clipboard("ccode-selftest")
    print("剪贴板  :", "读写正常" if get_clipboard() == "ccode-selftest" else "异常")
    hwnd = find_devcpp_window(cfg)
    print("Dev-C++ :", ("已找到窗口 hwnd=%s" % hwnd) if hwnd else "没找到（请先打开 Dev-C++）")
    print("python  :", sys.version.split()[0], "| tkinter OK")


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])
    cfg = load_config()

    if args.mode == "selftest":
        selftest(cfg)
        return 0

    enable_dpi()

    if args.mode == "config":
        run_config(cfg)
        return 0

    if not cfg.get("api_key") and not args.mock:
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox
        if messagebox.askyesno("AI 代码助手", "还没有配置 DeepSeek API key。现在去填？"):
            root.destroy()
            run_config(cfg)
            cfg = load_config()
            if not cfg.get("api_key"):
                return 1
        else:
            root.destroy()
            return 1

    root = tk.Tk()
    app = App(root, args.mode, cfg, args)
    if args.prompt:
        app.text.delete("1.0", "end")
        app.text.insert("1.0", args.prompt)
    app._center()
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
