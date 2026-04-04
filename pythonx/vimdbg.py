from __future__ import annotations
import vim
import os
from typing import Callable, NamedTuple

class Location(NamedTuple):
    linenumber: int
    filename: str
    abspath: str

def get_current_location() -> Location:
    cb = vim.current.buffer
    cw = vim.current.window
    pos = cw.cursor
    abspath = cb.name
    name = abspath
    try:
        rname = os.path.relpath(abspath)
    except:
        pass
    else:
        if '..' not in rname:
            name = rname
    return Location(pos[0], name, abspath)

def get_visual_selection() -> str:
    start_pos = vim.eval('getpos("\'<")')
    _, start_line, start_col, _ = start_pos
    end_pos = vim.eval('getpos("\'>")')
    _, end_line, end_col, _ = end_pos
    cb = vim.current.buffer
    start = int(start_line)-1
    end = int(end_line)
    txt = cb[start:end]
    if end - start == 1:
        return txt[0][int(start_col)-1:int(end_col)]
    begin = txt[0][int(start_col)-1:]
    ending = txt[-1][:int(end_col)]
    if len(txt) > 2:
        mid = '\n'.join(txt[1:-2])
    else:
        mid = ''
    return begin + ' ' + mid + ' ' + ending

def _lldb_quote(s: str) -> str:
    """Quote a string for LLDB's command parser."""
    if not any(c in s for c in ' \t"\\\''):
        return s
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"') + '"'

def _gdb_quote(s: str) -> str:
    """Quote a string for GDB's command parser."""
    if not any(c in s for c in ' \t"\\\''):
        return s
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"

def _pdb_quote(s: str) -> str:
    """pdb passes args as-is to Python's linecache; no quoting needed."""
    return s

class Flavor(NamedTuple):
    '''
    Debugger command templates.

    String substitutions are quoted via the flavor's quote function
    before interpolation. Integer substitutions are not quoted.

    Substitutions:
      {file}    - relative path
      {abspath} - absolute path
      {line}    - line number (int, not quoted)
      {idx}     - frame/thread index (int, not quoted)
      {name}    - variable name
      {expr}    - expression
    '''

    breakpoint_set: str
    breakpoint_del: str
    breakpoint_oneshot: str
    run_to: str
    print_var: str
    eval_expr: str
    stepout: str
    breakpoint_func: str
    backtrace: str
    locals: str
    threads: str
    quit: str
    kill: str
    frame_select: str
    thread_select: str
    quote: Callable[[str], str]
    run: str = 'run'
    next: str = 'n'
    step: str = 's'
    cont: str = 'c'
    up: str = 'up'
    down: str = 'down'
    recenter: str = 'rc'
    needs_recenter: bool = False

LLDB = Flavor(
    breakpoint_set='break set -f {file} -l {line}',
    breakpoint_del='bp_delete {file} {line}',
    breakpoint_oneshot='break set -o true -f {file} -l {line}',
    run_to='break set -o true -f {file} -l {line}\nc',
    print_var='v {name}',
    eval_expr='p {expr}',
    stepout='thread step-out',
    breakpoint_func='break set -n {name}',
    backtrace='btv',
    locals='localv',
    threads='threadv',
    quit='kill',
    kill='kill',
    run='run\ny',
    frame_select='frame select {idx}\nrc',
    thread_select='thread select {idx}\nrc',
    quote=_lldb_quote,
)

GDB = Flavor(
    breakpoint_set='break {file}:{line}',
    breakpoint_del='clear {file}:{line}',
    breakpoint_oneshot='tbreak {file}:{line}',
    run_to='tbreak {file}:{line}\nc',
    print_var='p {name}',
    eval_expr='p {expr}',
    stepout='finish',
    breakpoint_func='break {name}',
    backtrace='bt',
    locals='info locals',
    threads='info threads',
    quit='quit',
    kill='kill',
    frame_select='frame {idx}',
    thread_select='thread {idx}',
    quote=_gdb_quote,
)

_PDB_SELF = "__import__('sys')._getframe(1).f_locals['self']"

PDB = Flavor(
    breakpoint_set='break {abspath}:{line}',
    breakpoint_del='clear {abspath}:{line}',
    breakpoint_oneshot='tbreak {abspath}:{line}',
    run_to='tbreak {abspath}:{line}\nc',
    print_var='pp {name}',
    eval_expr='pp {expr}',
    stepout='return',
    breakpoint_func='break {name}',
    backtrace=f'!_vdbg.backtrace({_PDB_SELF})',
    locals=f'!_vdbg.locals_({_PDB_SELF})',
    threads='!_vdbg.threads_()',
    quit='die',
    kill='die',
    frame_select='!_vdbg.select_frame(' + _PDB_SELF + ', {idx})',
    thread_select='',
    quote=_pdb_quote,
    needs_recenter=True,
)

FLAVORS = {'lldb': LLDB, 'gdb': GDB, 'pdb': PDB}

class SignLoc(NamedTuple):
    bufnr: int
    line: int

_next_sign_id = 1
_pending_breakpoints: dict[Location, bool] = {}
_pending_bp_signs: dict[SignLoc, int] = {}

_active_popup = None  # type: _Popup | None

class _Popup:
    def __init__(self, entries:list[str], title:str, on_select, on_delete=None, maxheight:int=20, minwidth:int=40) -> None:
        self.on_select = on_select
        self.on_delete = on_delete
        self.entries = entries
        self.count = len(entries)
        self.cursor = 0
        list_str = "[" + ",".join(entries) + "]"
        opts = (f"{{'title':' {title} ','border':[1,1,1,1],"
                f"'maxheight':{maxheight},'minwidth':{minwidth},"
                f"'cursorline':1,'wrap':0,'mapping':0,"
                f"'filter':'VimdbgPopupFilter','callback':'VimdbgPopupClose'}}")
        self.winid = int(vim.eval(f"popup_create({list_str}, {opts})"))

    def move(self, delta:int) -> None:
        self.cursor = max(0, min(self.count - 1, self.cursor + delta))
        vim.command(f"call win_execute({self.winid}, 'normal! {self.cursor + 1}G')")

    def select(self) -> None:
        idx = self.cursor
        vim.command(f"call popup_close({self.winid})")
        self.on_select(idx)

    def delete(self) -> None:
        if self.on_delete is None or self.count == 0:
            return
        idx = self.cursor
        self.on_delete(idx)
        del self.entries[idx]
        self.count -= 1
        if self.count == 0:
            self.close()
            return
        if self.cursor >= self.count:
            self.cursor = self.count - 1
        list_str = "[" + ",".join(self.entries) + "]"
        vim.command(f"call popup_settext({self.winid}, {list_str})")
        vim.command(f"call win_execute({self.winid}, 'normal! {self.cursor + 1}G')")

    def close(self) -> None:
        vim.command(f"call popup_close({self.winid})")

def _popup_move(delta:int) -> None:
    if _active_popup is not None:
        _active_popup.move(delta)

def _popup_delete() -> None:
    if _active_popup is not None:
        _active_popup.delete()

def _popup_select() -> None:
    global _active_popup
    if _active_popup is not None:
        _active_popup.select()
        _active_popup = None

def _popup_closed() -> None:
    global _active_popup
    _active_popup = None

def _show_popup(entries:list[str], title:str, on_select, on_delete=None, **kwargs) -> None:
    global _active_popup
    if _active_popup is not None:
        _active_popup.close()
    _active_popup = _Popup(entries, title, on_select, on_delete=on_delete, **kwargs)

def _find_source_win() -> int:
    for w in vim.windows:
        if vim.eval(f"getbufvar({w.buffer.number}, '&buftype')") != 'terminal':
            return int(vim.eval(f"win_getid({w.number})"))
    return int(vim.eval("win_getid(1)"))

class DebugState:
    def __init__(self, bufid:int, flavor:Flavor) -> None:
        self.bufid = bufid
        self.flavor: Flavor = flavor
        self.src_win: int = _find_source_win()
        self.dbg_line_buf: int|None = None
        self.dbg_line: int|None = None
        self.bp_signs: dict[SignLoc, int] = {}
        self.bp_locs: dict[SignLoc, Location] = {}  # reverse map for breakpoint popup

    def _send(self, template:str, **kwargs) -> None:
        quoted = {k: self.flavor.quote(v) if isinstance(v, str) else v
                  for k, v in kwargs.items()}
        text = template.format(**quoted)
        for line in text.split('\n'):
            escaped = line.replace('\\', '\\\\').replace('"', '\\"')
            cmd = f'call term_sendkeys({self.bufid}, "{escaped}\\<Enter>")'
            vim.command(cmd)

    def _recenter(self) -> None:
        self._send(self.flavor.recenter)

    def _loc_kwargs(self, loc:Location) -> dict:
        return dict(file=loc.filename, abspath=loc.abspath, line=loc.linenumber)

    def toggle_breakpoint(self) -> None:
        loc = get_current_location()
        bufnr = vim.current.buffer.number
        key = SignLoc(bufnr, loc.linenumber)
        if key in self.bp_signs:
            self._send(self.flavor.breakpoint_del, **self._loc_kwargs(loc))
            vim.command(f"sign unplace {self.bp_signs[key]} buffer={bufnr}")
            del self.bp_signs[key]
            self.bp_locs.pop(key, None)
        else:
            self._send(self.flavor.breakpoint_set, **self._loc_kwargs(loc))
            self._place_bp_sign(loc.linenumber)
            self.bp_locs[key] = loc

    def breakpoint_func(self) -> None:
        cword = vim.eval("expand('<cword>')")
        self._send(self.flavor.breakpoint_func, name=cword)

    def oneshot_breakpoint(self) -> None:
        loc = get_current_location()
        self._send(self.flavor.breakpoint_oneshot, **self._loc_kwargs(loc))

    def run_to(self) -> None:
        loc = get_current_location()
        self._send(self.flavor.run_to, **self._loc_kwargs(loc))

    def print_ident(self) -> None:
        cword = vim.eval("expand('<cword>')")
        self._send(self.flavor.print_var, name=cword)

    def eval_expr(self) -> None:
        cword = vim.eval("expand('<cword>')")
        self._send(self.flavor.eval_expr, expr=cword)

    def print_selection(self) -> None:
        sel = get_visual_selection()
        self._send(self.flavor.eval_expr, expr=sel)

    def next(self) -> None:
        self._send(self.flavor.next)
        if self.flavor.needs_recenter:
            self._recenter()

    def up(self) -> None:
        self._send(self.flavor.up)
        self._recenter()

    def down(self) -> None:
        self._send(self.flavor.down)
        self._recenter()

    def run(self) -> None:
        self._send(self.flavor.run)

    def cont(self) -> None:
        self._send(self.flavor.cont)
        if self.flavor.needs_recenter:
            self._recenter()

    def step(self) -> None:
        self._send(self.flavor.step)
        if self.flavor.needs_recenter:
            self._recenter()

    def stepout(self) -> None:
        self._send(self.flavor.stepout)
        if self.flavor.needs_recenter:
            self._recenter()

    def trace(self) -> None:
        self._send(self.flavor.backtrace)

    def locals(self) -> None:
        self._send(self.flavor.locals)

    def threads(self) -> None:
        if self.flavor.threads:
            self._send(self.flavor.threads)

    def show_backtrace(self, frames:list) -> None:
        entries = []
        for f in frames:
            idx, func, path, line = f[0], f[1], f[2], f[3]
            prefix = f"#{idx} "
            fc = len(prefix) + 1
            fl = len(func)
            if path:
                short = os.path.basename(path)
                loc = f"  {short}:{line}"
                lc = len(prefix) + len(func) + 1
                ll = len(loc)
                text = f"{prefix}{func}{loc}".replace("'", "''")
                entries.append(f"{{'text':'{text}','props':[{{'col':{fc},'length':{fl},'type':'bt_func'}},{{'col':{lc},'length':{ll},'type':'bt_loc'}}]}}")
            else:
                text = f"{prefix}{func}".replace("'", "''")
                entries.append(f"{{'text':'{text}','props':[{{'col':{fc},'length':{fl},'type':'bt_func'}}]}}")
        def on_select(idx):
            self._send(self.flavor.frame_select, idx=frames[idx][0])
        _show_popup(entries, 'backtrace', on_select)

    def show_locals(self, vars_data:list) -> None:
        if not vars_data:
            vim.command("echo 'No locals'")
            return
        max_name = max(len(v[0]) for v in vars_data)
        max_type = max(len(v[1]) for v in vars_data)
        entries = []
        for v in vars_data:
            name, typ, val = v[0], v[1], v[2]
            padded_name = name.ljust(max_name)
            padded_type = typ.ljust(max_type)
            text = f"{padded_name}  {padded_type}  {val}".replace("'", "''")
            nc = 1
            nl = len(padded_name)
            tc = nl + 3
            tl = len(padded_type)
            vc = tc + tl + 2
            vl = len(val)
            props = f"[{{'col':{nc},'length':{nl},'type':'loc_name'}},{{'col':{tc},'length':{tl},'type':'loc_type'}},{{'col':{vc},'length':{vl},'type':'loc_val'}}]"
            entries.append(f"{{'text':'{text}','props':{props}}}")
        def on_select(idx):
            self._send(self.flavor.print_var, name=vars_data[idx][0])
        _show_popup(entries, 'locals', on_select, maxheight=25)

    def show_threads(self, threads_data:list) -> None:
        if not threads_data:
            vim.command("echo 'No threads'")
            return
        entries = []
        for t in threads_data:
            idx, name, func, loc, reason, is_selected = t[0], t[1], t[2], t[3], t[4], t[5]
            marker = '> ' if is_selected == '1' else '  '
            prefix = f"{marker}#{idx}"
            if name:
                prefix += f" {name}"
            text_parts = [prefix, f"  {func}"]
            if loc:
                text_parts.append(f"  {loc}")
            if reason:
                text_parts.append(f"  ({reason})")
            text = ''.join(text_parts).replace("'", "''")
            props = []
            if is_selected == '1':
                props.append(f"{{'col':1,'length':{len(marker) + len(f'#{idx}')},'type':'thr_cur'}}")
            fc = len(prefix) + 3
            fl = len(func)
            props.append(f"{{'col':{fc},'length':{fl},'type':'thr_func'}}")
            if loc:
                lc = fc + fl + 2
                ll = len(loc)
                props.append(f"{{'col':{lc},'length':{ll},'type':'thr_loc'}}")
            if reason:
                rc = len(text) - len(f"({reason})") + 1
                rl = len(f"({reason})")
                props.append(f"{{'col':{rc},'length':{rl},'type':'thr_reason'}}")
            entries.append(f"{{'text':'{text}','props':[{','.join(props)}]}}")
        def on_select(idx):
            self._send(self.flavor.thread_select, idx=threads_data[idx][0])
        _show_popup(entries, 'threads', on_select)

    def quit(self) -> None:
        self._send(self.flavor.quit)
        self.remove_dbgline()
        self.remove_bp_signs()

    def kill(self) -> None:
        self._send(self.flavor.kill)
        self.remove_dbgline()
        self.remove_bp_signs()

    def remove_dbgline(self) -> None:
        if self.dbg_line is None:
            return
        cmd = f"call prop_remove({{'type':'dbgline', 'bufnr':{self.dbg_line_buf}}}, {self.dbg_line}, {self.dbg_line})"
        vim.command(cmd)
        self.dbg_line = None
        self.dbg_line_buf = None

    def set_dbgline(self) -> None:
        cb = vim.current.buffer
        cw = vim.current.window
        pos = cw.cursor
        line = pos[0]
        self.dbg_line = line
        self.dbg_line_buf = cb.number
        cmd=f"call prop_add({line}, 1, {{'type':'dbgline', 'length':8}})"
        vim.command(cmd)

    def _place_bp_sign(self, line:int) -> None:
        global _next_sign_id
        bufnr = vim.current.buffer.number
        key = SignLoc(bufnr, line)
        if key in self.bp_signs:
            return
        sid = _next_sign_id
        _next_sign_id += 1
        vim.command(f"sign place {sid} line={line} name=dbgbreak buffer={bufnr}")
        self.bp_signs[key] = sid

    def remove_bp_signs(self) -> None:
        for loc, sid in self.bp_signs.items():
            vim.command(f"sign unplace {sid} buffer={loc.bufnr}")
        self.bp_signs.clear()

    def sync_bp_signs(self, bp_list:list) -> None:
        global _next_sign_id
        new_keys: set[SignLoc] = set()
        for entry in bp_list:
            path = entry[0]
            line = int(entry[1])
            bufnr = int(vim.eval(f"bufnr('{path}')"))
            if bufnr == -1:
                continue
            key = SignLoc(bufnr, line)
            new_keys.add(key)
            if key not in self.bp_signs:
                sid = _next_sign_id
                _next_sign_id += 1
                vim.command(f"sign place {sid} line={line} name=dbgbreak buffer={bufnr}")
                self.bp_signs[key] = sid
            abspath = os.path.abspath(path)
            self.bp_locs[key] = Location(line, path, abspath)
        for key in list(self.bp_signs):
            if key not in new_keys:
                vim.command(f"sign unplace {self.bp_signs[key]} buffer={key.bufnr}")
                del self.bp_signs[key]
                self.bp_locs.pop(key, None)


state = None

def set_dbg(flavor_name:str) -> None:
    global state
    if state:
        state.remove_dbgline()
    else:
        flavor = FLAVORS[flavor_name]
        state = DebugState(vim.current.buffer.number, flavor)
    setup_mappings()

def _flush_pending_breakpoints() -> None:
    if not state: return
    for loc in _pending_breakpoints:
        state._send(state.flavor.breakpoint_set, **state._loc_kwargs(loc))
    # Transfer signs to state ownership
    for key, sid in _pending_bp_signs.items():
        state.bp_signs[key] = sid
    _pending_breakpoints.clear()
    _pending_bp_signs.clear()

def src_win() -> int:
    if not state: return 1
    return state.src_win

def set_dbgline() -> None:
    if not state: return
    state.set_dbgline()

def sync_breakpoints(bp_list) -> None:
    if not state: return
    state.sync_bp_signs(bp_list)

_NMAPS = [
    ('a',             ':python3 vimdbg.toggle_breakpoint()<CR>'),
    ('n',             ':python3 vimdbg.next()<CR>'),
    ('f',             ':python3 vimdbg.breakpoint_func()<CR>'),
    ('r',             ':python3 vimdbg.oneshot_breakpoint()<CR>'),
    ('<cr>',          ':python3 vimdbg.run_to()<CR>'),
    ('p',             ':python3 vimdbg.print_ident()<CR>'),
    ('e',             ':python3 vimdbg.eval_expr()<CR>'),
    ('u',             ':python3 vimdbg.up()<CR>'),
    ('d',             ':python3 vimdbg.down()<CR>', '<nowait>'),
    ('s',             ':python3 vimdbg.step()<CR>'),
    ('q',             ':python3 vimdbg.close()<CR>'),
    ('x',             ':python3 vimdbg.stop()<CR>'),
    ('c',             ':python3 vimdbg.cont()<CR>'),
    ('o',             ':python3 vimdbg.stepout()<CR>'),
    ('t',             ':python3 vimdbg.trace()<CR>'),
    ('P',             ':python3 vimdbg.locals()<CR>'),
    ('T',             ':python3 vimdbg.threads()<CR>'),
    ('K',             ':python3 vimdbg.show_breakpoints()<CR>'),
    ('<leader><esc>', ':python3 vimdbg.remove_mappings()<CR>'),
    ('R',             ':python3 vimdbg.run()<CR>'),
    ('I',             '<Nop>'),
    ('A',             '<Nop>'),
    ('O',             '<Nop>'),
    ('S',             '<Nop>'),
    ('C',             '<Nop>'),
    ('gi',            '<Nop>'),
    ('gI',            '<Nop>'),
]
_VMAPS = [
    ('p', ':python3 vimdbg.print_selection()<CR>'),
    ('e', ':python3 vimdbg.print_selection()<CR>'),
    ('c', '<Nop>'),
    ('s', '<Nop>'),
    ('C', '<Nop>'),
    ('S', '<Nop>'),
    ('r', '<Nop>'),
    ('R', '<Nop>'),
    ('I', '<Nop>'),
    ('A', '<Nop>'),
]

def setup_mappings() -> None:
    for entry in _NMAPS:
        key, rhs = entry[0], entry[1]
        extra = entry[2] if len(entry) > 2 else ''
        vim.command(f"nnoremap <silent> {extra} {key} {rhs}")
    for key, rhs in _VMAPS:
        vim.command(f"vnoremap <silent> {key} {rhs}")
    vim.command("nnoremap <silent> <expr> i &buftype=='terminal' ? 'i' : ''")

def remove_mappings() -> None:
    for entry in _NMAPS:
        vim.command(f"nunmap {entry[0]}")
    for key, _ in _VMAPS:
        vim.command(f"vunmap {key}")
    vim.command("nunmap i")

def _restore_persistent_signs() -> None:
    """Re-place signs for persistent breakpoints after session ends."""
    global _next_sign_id
    _pending_bp_signs.clear()
    for loc in _pending_breakpoints:
        bufnr = int(vim.eval(f"bufnr('{loc.abspath}')"))
        if bufnr == -1:
            continue
        key = SignLoc(bufnr, loc.linenumber)
        sid = _next_sign_id
        _next_sign_id += 1
        vim.command(f"sign place {sid} line={loc.linenumber} name=dbgbreak buffer={bufnr}")
        _pending_bp_signs[key] = sid

def close() -> None:
    global state
    if not state: return
    state.quit()
    state = None
    remove_mappings()
    _restore_persistent_signs()

def stop() -> None:
    global state
    if not state: return
    state.kill()
    state = None
    remove_mappings()
    _restore_persistent_signs()

def persistent_breakpoint() -> None:
    global _next_sign_id
    loc = get_current_location()
    bufnr = vim.current.buffer.number
    key = SignLoc(bufnr, loc.linenumber)
    removing = loc in _pending_breakpoints
    if removing:
        # Remove persistent breakpoint
        _pending_breakpoints.pop(loc, None)
        if key in _pending_bp_signs:
            vim.command(f"sign unplace {_pending_bp_signs[key]} buffer={bufnr}")
            del _pending_bp_signs[key]
        if state and key in state.bp_signs:
            state._send(state.flavor.breakpoint_del, **state._loc_kwargs(loc))
            vim.command(f"sign unplace {state.bp_signs[key]} buffer={bufnr}")
            del state.bp_signs[key]
    else:
        # Add persistent breakpoint
        _pending_breakpoints[loc] = True
        if state:
            state._send(state.flavor.breakpoint_set, **state._loc_kwargs(loc))
            state._place_bp_sign(loc.linenumber)
        else:
            sid = _next_sign_id
            _next_sign_id += 1
            vim.command(f"sign place {sid} line={loc.linenumber} name=dbgbreak buffer={bufnr}")
            _pending_bp_signs[key] = sid

def show_breakpoints() -> None:
    # Gather all breakpoints: pending + live debugger
    seen: set[tuple[str, int]] = set()
    locs: list[Location] = []
    is_persistent: list[bool] = []
    for loc in _pending_breakpoints:
        key = (loc.abspath, loc.linenumber)
        if key not in seen:
            seen.add(key)
            locs.append(loc)
            is_persistent.append(True)
    if state:
        for sl, loc in state.bp_locs.items():
            key = (loc.abspath, loc.linenumber)
            if key not in seen:
                seen.add(key)
                locs.append(loc)
                is_persistent.append(False)
    if not locs:
        vim.command("echo 'No breakpoints'")
        return
    entries = []
    for i, loc in enumerate(locs):
        short = os.path.basename(loc.filename)
        marker = '*' if is_persistent[i] else ' '
        preview = ''
        bufnr = int(vim.eval(f"bufnr('{loc.abspath}')"))
        if bufnr != -1:
            lines = vim.eval(f"getbufline({bufnr}, {loc.linenumber})")
            if lines:
                preview = '  ' + lines[0].strip()
                if len(preview) > 60:
                    preview = preview[:57] + '...'
        location = f"{short}:{loc.linenumber}"
        text = f"{marker} {location}{preview}".replace("'", "''")
        lc = len(f"{marker} ") + 1
        ll = len(location)
        props = f"[{{'col':{lc},'length':{ll},'type':'bt_loc'}}]"
        entries.append(f"{{'text':'{text}','props':{props}}}")
    def on_select(idx):
        loc = locs[idx]
        vim.command(f"call win_gotoid({src_win()})")
        vim.command(f"silent! edit {loc.abspath}")
        vim.command(f"silent! {loc.linenumber}")
        vim.command("normal! zv")
        vim.command("normal! zz")
    def on_delete(idx):
        loc = locs.pop(idx)
        persistent = is_persistent.pop(idx)
        bufnr = int(vim.eval(f"bufnr('{loc.abspath}')"))
        key = SignLoc(bufnr, loc.linenumber)
        if persistent:
            _pending_breakpoints.pop(loc, None)
            if key in _pending_bp_signs:
                vim.command(f"sign unplace {_pending_bp_signs[key]} buffer={bufnr}")
                del _pending_bp_signs[key]
        if state and key in state.bp_signs:
            state._send(state.flavor.breakpoint_del, **state._loc_kwargs(loc))
            vim.command(f"sign unplace {state.bp_signs[key]} buffer={bufnr}")
            del state.bp_signs[key]
            state.bp_locs.pop(key, None)
    _show_popup(entries, 'breakpoints', on_select, on_delete=on_delete)

_mod = __import__('sys').modules[__name__]
for _name in (n for n in dir(DebugState) if not n.startswith('_')):
    if not hasattr(_mod, _name):
        def _make(name):
            def fn(*args):
                if not state: return
                getattr(state, name)(*args)
            fn.__name__ = name
            return fn
        setattr(_mod, _name, _make(_name))
