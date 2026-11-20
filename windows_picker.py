"""Native Windows folder and Save As dialogs, with no third-party runtime."""

import ctypes as C
import os
from uuid import UUID


class GUID(C.Structure):
    _fields_ = [("value", C.c_ubyte * 16)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(UUID(value).bytes_le)


class FilterSpec(C.Structure):
    _fields_ = [("name", C.c_wchar_p), ("pattern", C.c_wchar_p)]


# Slots follow the Windows SDK's IUnknown / IModalWindow / IFileDialog interfaces.
_RELEASE, _SHOW, _FILE_TYPES = 2, 3, 4
_SET_OPTIONS, _GET_OPTIONS, _DEFAULT_FOLDER, _FOLDER = 9, 10, 11, 12
_FILE_NAME, _TITLE, _OK_LABEL, _RESULT, _DEFAULT_EXT, _CLIENT_GUID = 15, 17, 18, 20, 22, 24
_CANCELLED = 0x800704C7
_FOS_OVERWRITEPROMPT, _FOS_STRICTFILETYPES, _FOS_NOCHANGEDIR = 2, 4, 8
_FOS_PICKFOLDERS, _FOS_FORCEFILESYSTEM = 0x20, 0x40
_FOS_PATHMUSTEXIST, _FOS_FILEMUSTEXIST, _FOS_NOTESTFILECREATE = 0x800, 0x1000, 0x10000
_SIGDN_FILESYSPATH = 0x80058000

_CLIENTS = {
    "source": "d7fa206d-4fcd-40f6-9a50-f38131c0c8a2",
    "folder": "ec0d0d91-16cf-4a8b-ad43-804aaa54a688",
    "save": "74b544d3-f71f-47a3-95b6-038168d95783",
}
_TITLES = {"source": "选择材质包源文件夹", "folder": "选择 ZIP 保存文件夹", "save": "另存为 ZIP"}


def _method(obj, slot, result, *types):
    table = C.cast(obj, C.POINTER(C.POINTER(C.c_void_p))).contents
    return C.WINFUNCTYPE(result, C.c_void_p, *types)(table[slot])


def _check(hr):
    if hr < 0:
        raise OSError(f"Windows 对话框返回 0x{hr & 0xffffffff:08X}")


def _call(obj, slot, types, *args):
    _check(_method(obj, slot, C.c_long, *types)(obj, *args))


def _release(obj):
    if obj:
        _method(obj, _RELEASE, C.c_ulong)(obj)


def pick_path(mode, folder=None, filename="", *, prefer_folder=False):
    """Return a chosen local path, or None on user cancellation. Never write a file."""
    if os.name != "nt":
        raise OSError("原生选择窗口仅支持 Windows，请粘贴路径")
    save = mode == "save"
    clsid = GUID.parse("c0b4e2f3-ba21-4773-8dba-335ec946eb8b" if save else
                       "dc1c5a9c-e88a-4dde-a5a1-60f82a20aef7")
    iid = GUID.parse("84bccd23-5fde-4cdb-aea4-af64b83d78ab" if save else
                     "d57c7288-d4ad-4768-be02-9d969532d960")
    ole = C.windll.ole32
    ole.CoTaskMemFree.argtypes = [C.c_void_p]
    # Each HTTP handler runs on a separate thread; the modal dialog needs its own STA.
    _check(ole.CoInitializeEx(None, 2))
    dialog, initial, result, raw = (C.c_void_p() for _ in range(4))
    try:
        _check(ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(dialog)))
        _call(dialog, _CLIENT_GUID, (C.POINTER(GUID),), C.byref(GUID.parse(_CLIENTS[mode])))
        _call(dialog, _TITLE, (C.c_wchar_p,), _TITLES[mode])
        options = C.c_uint()
        _call(dialog, _GET_OPTIONS, (C.POINTER(C.c_uint),), C.byref(options))
        flags = options.value | _FOS_NOCHANGEDIR | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
        if save:
            # This dialog only chooses the path. Confirm replacement at build time.
            flags = (flags | _FOS_STRICTFILETYPES | _FOS_NOTESTFILECREATE) & ~_FOS_OVERWRITEPROMPT
            spec = FilterSpec("ZIP 压缩包 (*.zip)", "*.zip")
            _call(dialog, _FILE_TYPES, (C.c_uint, C.POINTER(FilterSpec)), 1, C.byref(spec))
            _call(dialog, _DEFAULT_EXT, (C.c_wchar_p,), "zip")
            if filename:
                _call(dialog, _FILE_NAME, (C.c_wchar_p,), filename)
        else:
            flags = (flags | _FOS_PICKFOLDERS) & ~_FOS_FILEMUSTEXIST
            _call(dialog, _OK_LABEL, (C.c_wchar_p,), "选择文件夹")
        _call(dialog, _SET_OPTIONS, (C.c_uint,), flags)
        if folder:
            shell_id = GUID.parse("43826d1e-e718-42ee-bc55-a1e261c37bfe")
            hr = C.windll.shell32.SHCreateItemFromParsingName(
                C.c_wchar_p(str(folder)), None, C.byref(shell_id), C.byref(initial))
            if hr >= 0:
                _call(dialog, _FOLDER if prefer_folder else _DEFAULT_FOLDER,
                      (C.c_void_p,), initial)
        hr = _method(dialog, _SHOW, C.c_long, C.c_void_p)(dialog, None)
        if hr & 0xffffffff == _CANCELLED:
            return None
        _check(hr)
        _call(dialog, _RESULT, (C.POINTER(C.c_void_p),), C.byref(result))
        _call(result, 5, (C.c_uint, C.POINTER(C.c_void_p)), _SIGDN_FILESYSPATH, C.byref(raw))
        return C.wstring_at(raw)
    finally:
        if raw:
            ole.CoTaskMemFree(raw)
        for obj in (result, initial, dialog):
            _release(obj)
        ole.CoUninitialize()
