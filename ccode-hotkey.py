#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ccode-hotkey -- 只在 Dev-C++ 窗口内生效的 Ctrl+I 热键守卫。

原理：装一个 WH_KEYBOARD_LL 低级键盘钩子，每次按键检查前台窗口的进程名：
  * 前台是 devcpp.exe 且按下 Ctrl+I  -> 拦下这个键，启动 ccode 生成窗
  * 前台是 devcpp.exe 且按下 Ctrl+Alt+K -> 拦下，启动 ccode 补全窗
  * 其它任何情况                     -> 直接放行，按键照常传给当前程序

所以它对外表现是「Dev-C++ 内的快捷键」，Word/浏览器里的 Ctrl+I 斜体、
VS Code 里的 Ctrl+I 都不会被影响。

用法：
    pythonw ccode-hotkey.py           后台常驻
    Ctrl+C                            退出（或用任务管理器结束 pythonw）
"""

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

u32 = ctypes.windll.user32
k32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104

VK_I = 0x49
VK_K = 0x4B
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt

CREATE_NO_WINDOW = 0x08000000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

HERE = os.path.dirname(os.path.abspath(__file__))
CCODE_PY = os.path.join(HERE, "ccode.py")
TARGET_EXE = "devcpp.exe"


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wt.DWORD),
        ("scanCode", wt.DWORD),
        ("flags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wt.ULONG)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)

u32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
u32.SetWindowsHookExW.restype = ctypes.c_void_p
u32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
u32.CallNextHookEx.restype = ctypes.c_ssize_t
u32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
u32.GetForegroundWindow.restype = wt.HWND
u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = ctypes.c_void_p
k32.QueryFullProcessImageNameW.argtypes = [
    ctypes.c_void_p, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
]
k32.CloseHandle.argtypes = [ctypes.c_void_p]
k32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
k32.GetModuleHandleW.restype = wt.HMODULE

_last_fire = 0.0
_exe_cache = {"hwnd": None, "exe": ""}


def _foreground_exe():
    """返回前台窗口所属进程的可执行文件名（小写）。带一层缓存，避免每次按键都查。"""
    hwnd = u32.GetForegroundWindow()
    if hwnd and hwnd == _exe_cache["hwnd"]:
        return _exe_cache["exe"]

    pid = wt.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    if pid.value:
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if h:
            try:
                buf = ctypes.create_unicode_buffer(1024)
                n = wt.DWORD(1024)
                if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)):
                    exe = os.path.basename(buf.value).lower()
            finally:
                k32.CloseHandle(h)

    _exe_cache["hwnd"] = hwnd
    _exe_cache["exe"] = exe
    return exe


def _key_down(vk):
    return bool(u32.GetAsyncKeyState(vk) & 0x8000)


def _launch(mode):
    if not os.path.isfile(CCODE_PY):
        return
    try:
        subprocess.Popen(
            [sys.executable, CCODE_PY, mode],
            cwd=HERE,
            creationflags=CREATE_NO_WINDOW,
            close_fds=True,
        )
    except Exception:
        pass


def _handler(nCode, wParam, lParam):
    global _last_fire
    try:
        if nCode == HC_ACTION and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            vk = kb.vkCode

            if vk in (VK_I, VK_K) and _foreground_exe() == TARGET_EXE:
                ctrl = _key_down(VK_CONTROL)
                alt = _key_down(VK_MENU)
                shift = _key_down(VK_SHIFT)

                if ctrl and not shift:
                    if vk == VK_I and not alt:
                        mode = "gen"
                    elif vk == VK_K and alt:
                        mode = "complete"
                    else:
                        mode = None

                    if mode:
                        now = time.time()
                        if now - _last_fire > 0.7:      # 防连发
                            _last_fire = now
                            _launch(mode)
                        return 1                        # 吞掉这个按键
    except Exception:
        pass
    return u32.CallNextHookEx(None, nCode, wParam, lParam)


def main():
    if not os.path.isfile(CCODE_PY):
        raise SystemExit("找不到 ccode.py，请把它和本文件放在同一目录")

    proc = HOOKPROC(_handler)
    hook = u32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, k32.GetModuleHandleW(None), 0)
    if not hook:
        raise SystemExit("安装键盘钩子失败（错误码 %d）。可能被杀毒软件拦截。" % k32.GetLastError())

    print("ccode-hotkey 已启动。")
    print("  Dev-C++ 内：Ctrl+I 生成，Ctrl+Alt+K 补全")
    print("  其他程序：完全不受影响")
    print("  退出：Ctrl+C 或结束 pythonw 进程")
    try:
        msg = wt.MSG()
        while u32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            u32.TranslateMessage(ctypes.byref(msg))
            u32.DispatchMessageW(ctypes.byref(msg))
    except KeyboardInterrupt:
        pass
    finally:
        u32.UnhookWindowsHookEx(hook)
    return 0


if __name__ == "__main__":
    sys.exit(main())
