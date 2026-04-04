from __future__ import annotations
import os
import sys
import json
import threading

IN_VIM = bool(os.environ.get('VIM_TERMINAL'))

import builtins
builtins._vdbg = sys.modules[__name__]

try:
    import readline as _readline
except ImportError:
    _readline = None

def _tapi(func, args):
    if not IN_VIM:
        return
    js = json.dumps(['call', func, args])
    print('\033]51;', js, '\07', end='', sep='', flush=True)

def _scrub_history():
    if _readline is None:
        return
    n = _readline.get_current_history_length()
    if n > 0:
        _readline.remove_history_item(n - 1)

_PDB_SELF = "__import__('sys')._getframe(1).f_locals['self']"

def setup(pdb_instance):
    pdb_instance.aliases['rc'] = f'!_vdbg.recenter({_PDB_SELF})'
    pdb_instance.aliases['die'] = '!_vdbg.die()'
    _scrub_history()
    recenter(pdb_instance)

def recenter(pdb_instance):
    _scrub_history()
    frame = pdb_instance.curframe
    if frame is None:
        return
    _tapi('Tapi_open', [frame.f_code.co_filename, frame.f_lineno, 'pdb'])

def die():
    os._exit(0)

def backtrace(pdb_instance):
    _scrub_history()
    frames = []
    for i, (frame, lineno) in enumerate(pdb_instance.stack):
        func = frame.f_code.co_name
        path = frame.f_code.co_filename
        frames.append([i, func, path, lineno])
    _tapi('Tapi_backtrace', [frames])

def locals_(pdb_instance):
    _scrub_history()
    frame = pdb_instance.curframe
    if frame is None:
        return
    vars_data = []
    for name, val in frame.f_locals.items():
        if name.startswith('__') and name.endswith('__'):
            continue
        type_name = type(val).__name__
        try:
            display = repr(val)
            if len(display) > 80:
                display = display[:77] + '...'
        except:
            display = '???'
        vars_data.append([name, type_name, display])
    _tapi('Tapi_locals', [vars_data])

def select_frame(pdb_instance, idx):
    _scrub_history()
    if idx < 0 or idx >= len(pdb_instance.stack):
        return
    pdb_instance.curindex = idx
    pdb_instance.curframe = pdb_instance.stack[idx][0]
    pdb_instance.curframe_locals = pdb_instance.curframe.f_locals
    pdb_instance.print_stack_entry(pdb_instance.stack[idx])
    recenter(pdb_instance)

def threads_():
    _scrub_history()
    current_tid = threading.current_thread().ident
    threads = []
    for i, t in enumerate(threading.enumerate()):
        idx = i
        name = t.name or ''
        is_selected = t.ident == current_tid
        func = ''
        loc = ''
        if t.ident in sys._current_frames():
            f = sys._current_frames()[t.ident]
            func = f.f_code.co_name
            loc = f'{os.path.basename(f.f_code.co_filename)}:{f.f_lineno}'
        reason = 'alive' if t.is_alive() else 'dead'
        if t.daemon:
            reason += ' daemon'
        threads.append([idx, name, func, loc, reason, is_selected])
    _tapi('Tapi_threads', [threads])
