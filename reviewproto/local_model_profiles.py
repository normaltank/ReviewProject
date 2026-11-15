"""Fixed installed weights only; shared identity and sampling with PowerShell."""
import copy
import json
from pathlib import Path
from .core import require, digest

CATALOG_PATH = Path(__file__).with_name('local_model_profiles.json')
DEFAULT_MODEL = 'reviewproject-qwen3-4b-q4km'


def profiles():
    return json.loads(CATALOG_PATH.read_text(encoding='utf-8'))['profiles']


def profile(model):
    catalog = profiles()
    require(model in catalog, 'E_ATTENTION_MODEL_PROFILE')
    return copy.deepcopy(catalog[model])


def catalog_hash():
    return digest(CATALOG_PATH.read_bytes())
