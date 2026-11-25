"""Bounded by the caller. Prove real llvmpipe GLX clear/readback, not a library name."""
import ctypes as c
import sys

def function(lib, name, result, *args):
    fn = getattr(lib, name); fn.restype = result; fn.argtypes = list(args); return fn

def main():
    x = c.CDLL('libX11.so.6'); gl = c.CDLL('libGL.so.1')
    ptr = c.c_void_p; integer = c.c_int; ulong = c.c_ulong
    display = function(x, 'XOpenDisplay', ptr, c.c_char_p)(None)
    if not display: raise RuntimeError('X11 display unavailable')
    screen = function(x, 'XDefaultScreen', integer, ptr)(display)
    count = integer()
    attrs = (integer * 9)(0x8010, 4, 0x8011, 1, 8, 8, 9, 8, 0)
    configs = function(gl, 'glXChooseFBConfig', c.POINTER(ptr), ptr, integer, c.POINTER(integer), c.POINTER(integer))(display, screen, attrs, c.byref(count))
    if not configs or count.value < 1: raise RuntimeError('No GLX pbuffer configuration')
    context = function(gl, 'glXCreateNewContext', ptr, ptr, ptr, integer, ptr, integer)(display, configs[0], 0x8014, None, 1)
    if not context: raise RuntimeError('No software GLX context')
    sizes = (integer * 5)(0x8041, 16, 0x8040, 16, 0)
    buffer = function(gl, 'glXCreatePbuffer', ulong, ptr, ptr, c.POINTER(integer))(display, configs[0], sizes)
    if not function(gl, 'glXMakeContextCurrent', integer, ptr, ulong, ulong, ptr)(display, buffer, buffer, context):
        raise RuntimeError('Cannot bind software GLX context')
    renderer = function(gl, 'glGetString', c.c_char_p, c.c_uint)(0x1F01)
    print('Software OpenGL renderer:', renderer.decode(errors='replace') if renderer else 'unavailable', flush=True)
    if not renderer or b'llvmpipe' not in renderer.lower(): raise RuntimeError('The selected renderer is not llvmpipe')
    function(gl, 'glViewport', None, integer, integer, integer, integer)(0, 0, 16, 16)
    function(gl, 'glClearColor', None, c.c_float, c.c_float, c.c_float, c.c_float)(0, 1, 0, 1)
    function(gl, 'glClear', None, c.c_uint)(0x4000)
    pixels = (c.c_ubyte * (16*16*4))()
    function(gl, 'glReadPixels', None, integer, integer, integer, integer, c.c_uint, c.c_uint, ptr)(0, 0, 16, 16, 0x1908, 0x1401, pixels)
    if function(gl, 'glGetError', c.c_uint)() or bytes(pixels) != bytes([0,255,0,255]) * 256:
        raise RuntimeError('Software OpenGL pixel readback failed')
    function(gl, 'glXMakeContextCurrent', integer, ptr, ulong, ulong, ptr)(display, 0, 0, None)
    function(gl, 'glXDestroyPbuffer', None, ptr, ulong)(display, buffer)
    function(gl, 'glXDestroyContext', None, ptr, ptr)(display, context)
    function(x, 'XFree', integer, ptr)(configs)
    function(x, 'XCloseDisplay', integer, ptr)(display)
    print('PASS: llvmpipe GLX pixel readback')

if __name__ == '__main__':
    try: main()
    except Exception as error: print('Software graphics unavailable:', error, file=sys.stderr); sys.exit(1)
