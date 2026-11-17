"""Windows current-user DPAPI storage. Secret values never enter run config."""
import ctypes
import os
from pathlib import Path
from .core import require, ReviewError
from .local_io import atomic, load_json

ENTROPY = b'ReviewProject/DeepSeek/API/1'


def trial_config_path():
    """Optional packaging asset beside this module, including frozen bundles."""
    return Path(__file__).with_name('trial-config.json')


def _trial_key():
    try:
        raw=trial_config_path().read_bytes()
    except FileNotFoundError:
        return None
    except OSError:
        raise ReviewError('E_DEEPSEEK_TRIAL_CONFIG') from None
    try:
        value=load_json(raw)
        require(isinstance(value,dict),'E_DEEPSEEK_TRIAL_CONFIG')
        return _key(value.get('deepseek_api_key'))
    except Exception:
        raise ReviewError('E_DEEPSEEK_TRIAL_CONFIG') from None


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
        if target.is_file():
            return _key(_dpapi(target.read_bytes(),False).decode('utf-8'))
        default=_trial_key()
        require(default is not None,'E_DEEPSEEK_CREDENTIAL_MISSING')
        return default
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
    """Report availability without decrypting the personal credential store."""
    return credential_status(path=path,environ=environ)['configured']


def credential_status(*, path=None, environ=None):
    """Public status contains only availability, source and a sanitized error."""
    env=os.environ if environ is None else environ
    try:
        if 'DEEPSEEK_API_KEY' in env:
            _key(env['DEEPSEEK_API_KEY'])
            return {'configured':True,'source':'environment'}
        if (credential_path() if path is None else Path(path)).is_file():
            return {'configured':True,'source':'personal'}
        if _trial_key() is not None:
            return {'configured':True,'source':'trial'}
        return {'configured':False,'source':'none'}
    except ReviewError as exc:
        return {'configured':False,'source':'none','error':str(exc)}
