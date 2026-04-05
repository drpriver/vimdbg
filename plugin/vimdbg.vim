if exists('g:loaded_vimdbg')
    finish
endif
let g:loaded_vimdbg = 1

python3 import vimdbg

" Highlights
hi DBGLINE term=underline cterm=underline gui=underline
hi DBGBREAK ctermfg=1 cterm=bold guifg=red gui=bold

" Signs
sign define dbgbreak text=>> texthl=DBGBREAK

" Text properties
call prop_type_add('dbgline', {'combine':v:true, 'highlight':'DBGLINE'})
silent! call prop_type_add('bt_func', {'highlight': 'Function'})
silent! call prop_type_add('bt_loc', {'highlight': 'Comment'})
silent! call prop_type_add('loc_name', {'highlight': 'Identifier'})
silent! call prop_type_add('loc_type', {'highlight': 'Type'})
silent! call prop_type_add('loc_val', {'highlight': 'String'})
silent! call prop_type_add('thr_cur', {'highlight': 'WarningMsg'})
silent! call prop_type_add('thr_func', {'highlight': 'Function'})
silent! call prop_type_add('thr_loc', {'highlight': 'Comment'})
silent! call prop_type_add('thr_reason', {'highlight': 'String'})

" Tapi handlers
function g:Tapi_open(_, arglist)
    let l:flavor = get(a:arglist, 2, 'lldb')
    execute 'python3 vimdbg.set_dbg("' . l:flavor . '")'
    call win_gotoid(py3eval('vimdbg.src_win()'))
    let l:file = a:arglist[0]
    if expand('%:p') !=# fnamemodify(l:file, ':p')
        exe "silent! edit " . l:file
    endif
    exe "silent! " . a:arglist[1]
    normal! zv
    normal! zz
    python3 vimdbg.set_dbgline()
    call timer_start(0, {-> py3eval('vimdbg._flush_pending_breakpoints()')})
endfunction

function g:Tapi_breakpoints(_, arglist)
    python3 vimdbg.sync_breakpoints(vim.eval('a:arglist[0]'))
endfunction

function g:Tapi_backtrace(_, arglist)
    python3 vimdbg.show_backtrace(vim.eval('a:arglist[0]'))
endfunction

function g:Tapi_locals(_, arglist)
    python3 vimdbg.show_locals(vim.eval('a:arglist[0]'))
endfunction

function g:Tapi_threads(_, arglist)
    python3 vimdbg.show_threads(vim.eval('a:arglist[0]'))
endfunction

function g:Tapi_socket(_, arglist)
    execute "python3 vimdbg.set_socket('" . a:arglist[0] . "')"
endfunction

" Popup selection highlight (underline, only affects popups)
hi PopupSelected cterm=underline gui=underline ctermbg=NONE guibg=NONE

" Popup filter and callback
function g:VimdbgPopupFilter(winid, key)
    if a:key ==# 'j' || a:key ==# "\<Down>"
        python3 vimdbg._popup_move(1)
        return 1
    elseif a:key ==# 'k' || a:key ==# "\<Up>"
        python3 vimdbg._popup_move(-1)
        return 1
    elseif a:key ==# "\<CR>"
        python3 vimdbg._popup_select()
        return 1
    elseif a:key ==# 'd'
        python3 vimdbg._popup_delete()
        return 1
    elseif a:key ==# "\<Esc>" || a:key ==# 'q' || a:key ==# 'x'
        call popup_close(a:winid)
        return 1
    endif
    return 1
endfunction

function g:VimdbgPopupClose(winid, result)
    python3 vimdbg._popup_closed()
endfunction

nnoremap <F8> :python3 vimdbg.persistent_breakpoint()<CR>
