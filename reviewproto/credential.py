"""Windows current-user DPAPI storage. Secret values never enter run config."""
import ctypes
import os
from pathlib import Path
from .core import require, ReviewError
from .local_io import atomic

ENTROPY = b'ReviewProject/DeepSeek/API/1'


class _Blob(ctypes.Structure):
    _fields_=[('size',ctypes.c_uint32),('data',ctypes.POINTER(ctypes.c_ubyte))]


def credential_path():
    base=os.environ.get('LOCALAPPDATA')
    require(bool(base),'E_DEEPSEEK_CREDENTIAL_STORE')
    return Path(base)/'ReviewProject'/'credentials'/'deepseek.dpapi'


def _key(value):
    require(isinstance(value,str) and bool(value.strip()) and value.isascii() and
            not any(c.isspace() for c in value),'E_DEEPSEEK_CREDENTIAL_MISSING')
    return value


def _dpapi(data, protect):
    require(os.name=='nt','E_DEEPSEEK_CREDENTIAL_STORE')
    def blob(value):
        buffer=ctypes.create_string_buffer(value)
        return _Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte))),buffer
    source,source_buffer=blob(data)
    entropy,entropy_buffer=blob(ENTROPY)
    result=_Blob()
    crypt=ctypes.windll.crypt32
    operation=crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    operation.argtypes=[ctypes.POINTER(_Blob),ctypes.c_void_p,ctypes.POINTER(_Blob),ctypes.c_void_p,
                       ctypes.c_void_p,ctypes.c_uint32,ctypes.POINTER(_Blob)]
    operation.restype=ctypes.c_int
    require(bool(operation(ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(result))),
            'E_DEEPSEEK_CREDENTIAL_STORE')
    try:
        return ctypes.string_at(result.data,result.size)
    finally:
        ctypes.memset(result.data,0,result.size)
        ctypes.windll.kernel32.LocalFree.argtypes=[ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(result.data,ctypes.c_void_p))


def load_deepseek_key(*, path=None, environ=None):
    """Resolve only at invocation time. Explicit env takes precedence over DPAPI."""
    env=os.environ if environ is None else environ
    try:
        if 'DEEPSEEK_API_KEY' in env: return _key(env['DEEPSEEK_API_KEY'])
        target=credential_path() if path is None else Path(path)
        require(target.is_file(),'E_DEEPSEEK_CREDENTIAL_MISSING')
        return _key(_dpapi(target.read_bytes(),False).decode('utf-8'))
    except ReviewError:
        raise
    except Exception:
        raise ReviewError('E_DEEPSEEK_CREDENTIAL_STORE') from None


def save_deepseek_key(value, *, path=None):
    try:
        secret=_key(value)
        target=credential_path() if path is None else Path(path)
        target.parent.mkdir(parents=True,exist_ok=True)
        atomic(target,_dpapi(secret.encode('utf-8'),True))
    except ReviewError:
        raise
    except Exception:
        raise ReviewError('E_DEEPSEEK_CREDENTIAL_STORE') from None


def credential_available(*, path=None, environ=None):
    """Check only explicit env or file existence; do not decrypt for UI status."""
    env=os.environ if environ is None else environ
    if 'DEEPSEEK_API_KEY' in env: return bool(env['DEEPSEEK_API_KEY'].strip())
    try: return (credential_path() if path is None else Path(path)).is_file()
    except ReviewError: return False
