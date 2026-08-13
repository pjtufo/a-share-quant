"""
tray_icon.py — 系统托盘图标模块（最小化到托盘 + 事件 tips + 双击恢复 + 右键菜单）。

优先使用 pystray；回退用纯 ctypes（零外部依赖）实现 Win32 托盘。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import os
import threading
import time
from typing import Callable, Optional

# ---------------------------------------------------------------------------
# 可选项：pystray
# ---------------------------------------------------------------------------
_tray = None
_use_pystray = False

try:
    import pystray  # type: ignore
    from PIL import Image, ImageDraw  # type: ignore
    _use_pystray = True
except Exception:
    _use_pystray = False

# ---------------------------------------------------------------------------
# Tkinter tooltip 小窗口
# ---------------------------------------------------------------------------
class TipsWindow:
    def __init__(self, root, text: str, duration_ms: int = 3000):
        self.root = root
        self._win = None
        try:
            tw = root.Toplevel(root)
            tw.overrideredirect(True)
            tw.attributes("-topmost", True)
            tw.attributes("-alpha", 0.96)
            try:
                tw.attributes("-toolwindow", True)
            except Exception:
                pass
            tw.configure(bg="#1e1e1e", padx=10, pady=6)
            lbl = tw.Label(tw, text=text, bg="#1e1e1e", fg="#ffffff",
                            font=("Microsoft YaHei UI", 9), justify="left")
            lbl.pack()
            tw.update_idletasks()
            w = tw.winfo_reqwidth()
            h = tw.winfo_reqheight()
            try:
                sx = tw.winfo_screenwidth()
                sy = tw.winfo_screenheight()
                x = max(10, sx - w - 20)
                y = max(10, sy - h - 60)
            except Exception:
                x, y = 10, 10
            tw.geometry(f"{w}x{h}+{x}+{y}")
            tw.after(duration_ms, tw.destroy)
            self._win = tw
        except Exception:
            pass

    def destroy(self):
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None


# ---------------------------------------------------------------------------
# 纯 ctypes 回退（零外部依赖）
# ---------------------------------------------------------------------------
if not _use_pystray:
    import ctypes
    from ctypes import wintypes

    NIM_ADD = 0x00000000
    NIM_MODIFY = 0x00000001
    NIM_DELETE = 0x00000002
    NIF_MESSAGE = 0x00000001
    NIF_ICON = 0x00000002
    NIF_TIP = 0x00000004
    NIF_STATE = 0x00000008
    NIF_INFO = 0x00000010
    WM_USER = 0x0400
    TRAY_ID = WM_USER + 1000
    TRAY_ICON_ID = 1
    WM_LBUTTONDBLCLK = 0x0203
    WM_RBUTTONUP = 0x0205
    WM_RBUTTONDOWN = 0x0204
    WM_COMMAND = 0x0111
    WM_DESTROY = 0x0002
    WM_QUIT = 0x0012
    TPM_RETURNCMD = 0x0100
    TPM_RIGHTBUTTON = 0x0002
    MF_STRING = 0x00000000

    IDM_RESTORE = 1001
    IDM_EXIT = 1002

    class GUID(ctypes.Structure):
        _fields_ = [
            ('Data1', ctypes.c_ulong),
            ('Data2', ctypes.c_ushort),
            ('Data3', ctypes.c_ushort),
            ('Data4', ctypes.c_ubyte * 8),
        ]

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [
            ('cbSize', wintypes.DWORD),
            ('hWnd', wintypes.HWND),
            ('uID', wintypes.UINT),
            ('uFlags', wintypes.UINT),
            ('uCallbackMessage', wintypes.UINT),
            ('hIcon', wintypes.HICON),
            ('szTip', wintypes.WCHAR * 128),
            ('dwState', wintypes.DWORD),
            ('dwStateMask', wintypes.DWORD),
            ('szInfo', wintypes.WCHAR * 256),
            ('uTimeoutOrVersion', ctypes.c_uint),
            ('szInfoTitle', wintypes.WCHAR * 64),
            ('dwInfoFlags', wintypes.DWORD),
            ('guidItem', GUID),
            ('hBalloonIcon', wintypes.HICON),
        ]

    Shell_NotifyIcon = ctypes.windll.shell32.Shell_NotifyIconW
    CreateWindowEx = ctypes.windll.user32.CreateWindowExW
    DefWindowProc = ctypes.windll.user32.DefWindowProcW
    DestroyWindow = ctypes.windll.user32.DestroyWindow
    GetModuleHandle = ctypes.windll.kernel32.GetModuleHandleW
    RegisterClass = ctypes.windll.user32.RegisterClassW
    CreatePopupMenu = ctypes.windll.user32.CreatePopupMenu
    AppendMenu = ctypes.windll.user32.AppendMenuW
    SetForegroundWindow = ctypes.windll.user32.SetForegroundWindow
    TrackPopupMenu = ctypes.windll.user32.TrackPopupMenu
    PostMessage = ctypes.windll.user32.PostMessageW
    GetMessage = ctypes.windll.user32.GetMessageW
    TranslateMessage = ctypes.windll.user32.TranslateMessage
    DispatchMessage = ctypes.windll.user32.DispatchMessageW
    LoadCursor = ctypes.windll.user32.LoadCursorW
    LoadImage = ctypes.windll.user32.LoadImageW
    DestroyIcon = ctypes.windll.user32.DestroyIcon

    CS_VREDRAW = 0x0001
    CS_HREDRAW = 0x0002
    CW_USEDEFAULT = 0x80000000
    HWND_MESSAGE = 0xFFFFFFFC
    IDC_ARROW = 32512
    IMAGE_ICON = 1
    LR_LOADFROMFILE = 0x00000010
    LR_DEFAULTSIZE = 0x00000040

    # Keep references alive
    _g_icon_handles = []

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ('style', wintypes.UINT),
            ('lpfnWndProc', ctypes.c_void_p),
            ('cbClsExtra', ctypes.c_int),
            ('cbWndExtra', ctypes.c_int),
            ('hInstance', wintypes.HINSTANCE),
            ('hIcon', wintypes.HICON),
            ('hCursor', wintypes.HICON),
            ('hbrBackground', wintypes.HBRUSH),
            ('lpszMenuName', wintypes.LPCWSTR),
            ('lpszClassName', wintypes.LPCWSTR),
        ]


# ---------------------------------------------------------------------------
# TrayIcon 公共类
# ---------------------------------------------------------------------------
class TrayIcon:
    def __init__(
        self,
        root,
        title: str = "A-Share Quant",
        icon_path: str = "",
        on_restore: Optional[Callable] = None,
        on_exit: Optional[Callable] = None,
        on_minimize: Optional[Callable] = None,
        tips_duration_ms: int = 3000,
    ):
        self.root = root
        self.title = title
        self.on_restore = on_restore
        self.on_exit = on_exit
        self.on_minimize = on_minimize
        self.tips_duration_ms = tips_duration_ms
        self._running = False
        self._icon_path = icon_path or self._default_icon()

        if _use_pystray:
            self._setup_pystray()
        else:
            self._setup_win32()

    def _default_icon(self) -> str:
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cache")
        os.makedirs(cache_dir, exist_ok=True)
        path = os.path.join(cache_dir, "tray_icon.ico")
        if not os.path.exists(path):
            try:
                from PIL import Image, ImageDraw
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.rounded_rectangle([4, 4, 60, 60], radius=12,
                                        fill=(0, 120, 215, 255), outline=(255, 255, 255, 255), width=2)
                img.save(path, format="ICO")
            except Exception:
                path = ""
        return path

    # ----- pystray 路径 -----
    def _setup_pystray(self):
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([4, 4, 60, 60], radius=12,
                                    fill=(0, 120, 215, 255), outline=(255, 255, 255, 255), width=2)
            self._pystray_image = img
        except Exception:
            self._pystray_image = None

        def _restore(icon, item):
            self._do_restore()

        def _exit(icon, item):
            self._do_exit()

        self._restore_cb = _restore
        self._exit_cb = _exit
        menu = pystray.Menu(
            pystray.MenuItem("恢复窗口", _restore, default=True),
            pystray.MenuItem("退出程序", _exit),
        )
        self._pystray_icon = pystray.Icon(
            self.title,
            self._pystray_image,
            self.title,
            menu,
        )
        try:
            self._pystray_icon.on_double_click = _restore
        except Exception:
            pass

    def _pystray_run(self):
        try:
            self._pystray_icon.run()
        except Exception:
            pass

    # ----- 纯 ctypes 路径 -----
    def _setup_win32(self):
        self._hIcon = self._load_icon()
        self._wndproc_ptr = ctypes.WINFUNCTYPE(
            ctypes.c_long,
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )(self._wndproc)
        wc = WNDCLASSW()
        wc.style = CS_VREDRAW | CS_HREDRAW
        wc.lpfnWndProc = ctypes.cast(self._wndproc_ptr, ctypes.c_void_p).value
        wc.hInstance = GetModuleHandle(None)
        wc.hCursor = LoadCursor(0, IDC_ARROW)
        wc.lpszClassName = "TrayAppWindow"
        RegisterClass(ctypes.byref(wc))
        self._hwnd = CreateWindowEx(
            0,
            "TrayAppWindow",
            "TrayApp",
            0,
            0, 0, 0, 0,
            HWND_MESSAGE,
            0,
            0,
            0,
        )
        self._add_tray()

    def _load_icon(self):
        path = self._icon_path
        if path and os.path.exists(path):
            h = LoadImage(0, path, IMAGE_ICON, 0, 0,
                          LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                _g_icon_handles.append(h)
                return h
        # generate via Pillow if available, else blank
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([2, 2, 60, 60], radius=10,
                                    fill=(0, 120, 215, 255), outline=(255, 255, 255, 255), width=1)
            tmp = os.path.join(os.environ.get("TEMP", "."), "_tray_icon.ico")
            img.save(tmp, format="ICO")
            h = LoadImage(0, tmp, IMAGE_ICON, 0, 0,
                          LR_LOADFROMFILE | LR_DEFAULTSIZE)
            if h:
                _g_icon_handles.append(h)
                return h
        except Exception:
            pass
        return 0

    def _add_tray(self):
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self._hwnd
        nid.uID = TRAY_ICON_ID
        nid.uFlags = NIF_ICON | NIF_TIP | NIF_MESSAGE
        nid.uCallbackMessage = TRAY_ID
        nid.hIcon = self._hIcon
        nid.szTip = self.title[:127]
        Shell_NotifyIcon(NIM_ADD, ctypes.byref(nid))

    def _remove_tray(self):
        try:
            nid = NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
            nid.hWnd = self._hwnd
            nid.uID = TRAY_ICON_ID
            nid.uFlags = 0
            Shell_NotifyIcon(NIM_DELETE, ctypes.byref(nid))
        except Exception:
            pass

    def _wndproc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == TRAY_ID:
                if lparam == WM_LBUTTONDBLCLK:
                    self._do_restore()
                elif lparam == WM_RBUTTONUP:
                    self._show_menu()
            elif msg == WM_COMMAND:
                cmd = wparam & 0xFFFF
                if cmd == IDM_RESTORE:
                    self._do_restore()
                elif cmd == IDM_EXIT:
                    self._do_exit()
            elif msg == WM_DESTROY:
                self._remove_tray()
        except Exception:
            pass
        return DefWindowProc(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        try:
            menu = CreatePopupMenu()
            AppendMenu(menu, MF_STRING, IDM_RESTORE, "恢复窗口")
            AppendMenu(menu, MF_STRING, IDM_EXIT, "退出程序")
            SetForegroundWindow(self._hwnd)
            TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON, 0, 0, 0, self._hwnd, None)
        except Exception:
            pass

    # ----- 公共 API -----
    def start(self):
        if self._running:
            return
        self._running = True
        if _use_pystray:
            self._thread = threading.Thread(target=self._pystray_run, daemon=True)
            self._thread.start()
        else:
            self._msg_thread = threading.Thread(target=self._msg_loop, daemon=True)
            self._msg_thread.start()
        self._show_tip("托盘已就绪", "程序已最小化到系统托盘\n双击恢复，右键查看更多")

    def _msg_loop(self):
        try:
            msg = wintypes.MSG()
            while self._running:
                ret = GetMessage(ctypes.byref(msg), 0, 0)
                if ret <= 0:
                    break
                TranslateMessage(ctypes.byref(msg))
                DispatchMessage(ctypes.byref(msg))
        except Exception:
            pass

    def stop(self):
        self._running = False
        if _use_pystray and hasattr(self, "_pystray_icon"):
            try:
                self._pystray_icon.stop()
            except Exception:
                pass
        if not _use_pystray:
            try:
                self._remove_tray()
            except Exception:
                pass
            try:
                PostMessage(self._hwnd, WM_QUIT, 0, 0)
            except Exception:
                pass

    def _do_restore(self):
        self._show_tip("恢复窗口", "正在恢复主窗口...")
        if self.on_restore:
            try:
                self.on_restore()
            except Exception:
                pass

    def _do_exit(self):
        if self.on_exit:
            try:
                self.on_exit()
            except Exception:
                pass
        self.stop()

    def _show_tip(self, title: str, message: str):
        try:
            _TipsWindow(self.root, f"{title}\n{message}", self.tips_duration_ms)
        except Exception:
            pass

    def notify(self, title: str, message: str):
        self._show_tip(title, message)
