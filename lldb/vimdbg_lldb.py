from __future__ import annotations
import lldb
import os
import json

def recenter(debugger, command, result, internal_dict):
    for thread in debugger.GetTargetAtIndex(0).process:
        if (thread.GetStopReason() != lldb.eStopReasonNone) and (thread.GetStopReason() != lldb.eStopReasonInvalid):
            frame = thread.GetSelectedFrame()
            return _recenter(frame)

def _recenter(frame:lldb.SBFrame) -> bool:
    le = frame.line_entry
    f, l = le.file, le.line
    if not l: return
    if not f.fullpath: return
    path = os.path.relpath(f.fullpath).replace(' ', '\\ ')
    js = json.dumps(['call', 'Tapi_open', [path, l, 'lldb']])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def _sync_breakpoints(target:lldb.SBTarget) -> None:
    bps = []
    for bp in target.breakpoint_iter():
        if not bp.IsEnabled():
            continue
        for loc in bp:
            le = loc.GetAddress().GetLineEntry()
            f = le.GetFileSpec()
            if not f.fullpath:
                continue
            path = os.path.relpath(f.fullpath).replace(' ', '\\ ')
            bps.append([path, le.GetLine(), bp.IsOneShot()])
    js = json.dumps(['call', 'Tapi_breakpoints', [bps]])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def bp_delete(debugger, command, result, internal_dict):
    """bp_delete <file> <line>"""
    args = command.split()
    if len(args) != 2:
        result.SetError('usage: bp_delete <file> <line>')
        return
    file_path = args[0]
    line = int(args[1])
    target = debugger.GetSelectedTarget()
    to_delete = []
    for bp in target.breakpoint_iter():
        for loc in bp:
            le = loc.GetAddress().GetLineEntry()
            f = le.GetFileSpec()
            if not f.fullpath:
                continue
            if os.path.relpath(f.fullpath) == file_path and le.GetLine() == line:
                to_delete.append(bp.GetID())
                break
    for bid in to_delete:
        target.BreakpointDelete(bid)
    if to_delete:
        _sync_breakpoints(target)

def localv(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    frame = target.GetProcess().GetSelectedThread().GetSelectedFrame()
    variables = frame.GetVariables(True, True, False, True)
    vars_data = []
    for var in variables:
        name = var.GetName() or '?'
        type_name = var.GetTypeName() or '?'
        summary = var.GetSummary()
        value = var.GetValue()
        display = summary.strip() if summary else value if value else ''
        vars_data.append([name, type_name, display])
    js = json.dumps(['call', 'Tapi_locals', [vars_data]])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def threadv(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    process = target.GetProcess()
    selected_tid = process.GetSelectedThread().GetThreadID()
    threads = []
    for thread in process:
        tid = thread.GetThreadID()
        idx = thread.GetIndexID()
        name = thread.GetName() or ''
        reason = thread.GetStopDescription(256)
        frame = thread.GetFrameAtIndex(0)
        func = frame.GetFunctionName() or '???'
        le = frame.GetLineEntry()
        f = le.GetFileSpec()
        if f.fullpath:
            path = os.path.basename(f.fullpath)
            loc = f'{path}:{le.GetLine()}'
        else:
            loc = ''
        is_selected = tid == selected_tid
        threads.append([idx, name, func, loc, reason, is_selected])
    js = json.dumps(['call', 'Tapi_threads', [threads]])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def btv(debugger, command, result, internal_dict):
    target = debugger.GetSelectedTarget()
    thread = target.GetProcess().GetSelectedThread()
    frames = []
    for i in range(thread.GetNumFrames()):
        frame = thread.GetFrameAtIndex(i)
        func = frame.GetDisplayFunctionName() or '???'
        args = frame.GetVariables(True, False, False, False)
        if args.GetSize() > 0:
            parts = []
            for j in range(args.GetSize()):
                arg = args.GetValueAtIndex(j)
                name = arg.GetName() or '?'
                val = arg.GetSummary() or arg.GetValue() or '?'
                parts.append(f'{name}={val}')
            func = f'{func}({", ".join(parts)})'
        le = frame.GetLineEntry()
        f = le.GetFileSpec()
        if f.fullpath:
            path = os.path.relpath(f.fullpath)
            line = le.GetLine()
        else:
            path = ''
            line = 0
        frames.append([i, func, path, line])
    js = json.dumps(['call', 'Tapi_backtrace', [frames]])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

class StopHook:
    def __init__(self, target:lldb.SBTarget, extra_args:lldb.SBStructuredData, internal_dict:dict) -> None:
        pass

    def handle_stop(self, exe_ctx: lldb.SBExecutionContext, stream: lldb.SBStream) -> bool:
        _recenter(exe_ctx.frame)
        _sync_breakpoints(exe_ctx.GetTarget())
        return True

def register(debugger):
    modname = 'vimdbg_lldb'
    debugger.HandleCommand(f'command script add -f {modname}.recenter rc')
    debugger.HandleCommand(f'command script add -f {modname}.bp_delete bp_delete')
    debugger.HandleCommand(f'command script add -f {modname}.btv btv')
    debugger.HandleCommand(f'command script add -f {modname}.localv localv')
    debugger.HandleCommand(f'command script add -f {modname}.threadv threadv')
    debugger.HandleCommand(f'target stop-hook add -P {modname}.StopHook')
    debugger.HandleCommand('settings set stop-line-count-before 0')
    debugger.HandleCommand('settings set stop-line-count-after 0')
    debugger.HandleCommand('settings set auto-confirm true')
    debugger.HandleCommand(r'settings set frame-format ""')
    debugger.HandleCommand(r'settings set thread-stop-format ""')

import threading
import socket
import tempfile

_server_thread = None
_server_socket = None

import atexit
def _cleanup_socket():
    if _server_socket:
        addr = _server_socket.getsockname()
        _server_socket.close()
        if isinstance(addr, str):
            try:
                os.unlink(addr)
            except:
                pass
atexit.register(_cleanup_socket)

def _start_cmd_server(debugger):
    global _server_thread, _server_socket
    if hasattr(socket, 'AF_UNIX'):
        sock_path = os.path.join(tempfile.gettempdir(), f'vimdbg_lldb_{os.getpid()}.sock')
        try:
            os.unlink(sock_path)
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        addr_for_vim = sock_path
    else:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(('127.0.0.1', 0))
        addr_for_vim = f'127.0.0.1:{srv.getsockname()[1]}'
    srv.listen(1)
    _server_socket = srv
    def serve():
        while True:
            conn, _ = srv.accept()
            data = b''
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
            conn.close()
            for line in data.decode().strip().split('\n'):
                line = line.strip()
                if line:
                    debugger.HandleCommand(line)
    _server_thread = threading.Thread(target=serve, daemon=True)
    _server_thread.start()
    js = json.dumps(['call', 'Tapi_socket', [addr_for_vim]])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def __lldb_init_module(debugger, internal_dict):
    if os.environ.get('VIM_TERMINAL'):
        register(debugger)
        _start_cmd_server(debugger)
