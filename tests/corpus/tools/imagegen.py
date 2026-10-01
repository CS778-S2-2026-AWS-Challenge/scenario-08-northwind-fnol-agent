"""Generate a synthetic photo on the remote ComfyUI (Qwen-Image 2.1) and save it as JPEG.

Results are cached by prompt, seed and size under tools/.image-cache, so rebuilding a pack does not
spend GPU time again. The saved JPEG carries no EXIF or other metadata.

The ComfyUI address comes only from the CORPUS_COMFYUI environment variable, for example
http://<host>:8188. It is needed only when an image is not in the cache yet.
"""

import copy
import hashlib
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, cast

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
GRAPH = os.path.join(HERE, 'qwen-image-2.1-api.json')
CACHE = os.path.join(HERE, '.image-cache')


def _base() -> str:
    base = os.environ.get('CORPUS_COMFYUI', '').rstrip('/')
    if not base:
        raise RuntimeError(
            'Set CORPUS_COMFYUI to the ComfyUI base URL, for example http://<host>:8188'
        )
    return base


def _call(
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 60,
    attempts: int = 5,
) -> bytes | None:
    """Call ComfyUI, retrying a dropped connection (the home link over Tailscale can blip)."""
    data = json.dumps(payload).encode() if payload is not None else None
    for attempt in range(attempts):
        request = urllib.request.Request(
            _base() + path, data=data, headers={'Content-Type': 'application/json'}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return cast(bytes, response.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == attempts - 1:
                raise
            time.sleep(15 * (attempt + 1))
    return None


def model_name() -> str:
    return cast(
        str, json.loads(Path(GRAPH).read_text(encoding='utf-8'))['1']['inputs']['unet_name']
    )


def generate(
    prompt: str,
    seed: int,
    width: int,
    height: int,
    out_path: str,
    quality: int = 88,
    timeout: float = 600,
) -> dict[str, Any]:
    """Write a JPEG to out_path and return provenance details.

    With CORPUS_PLACEHOLDER_IMAGES=1 it writes a plain grey image instead and calls no service, so
    a spec's labels, documents and checks can be tried before any GPU time is spent. Placeholder
    packs are for drafting only and never go into a corpus.
    """
    key = hashlib.sha256(json.dumps([prompt, seed, width, height]).encode()).hexdigest()[:24]
    if os.environ.get('CORPUS_PLACEHOLDER_IMAGES') == '1':
        cached = os.path.join(CACHE, key + '.png')
        if os.path.exists(cached):
            img = Image.open(cached).convert('RGB')
            source = 'cache'
        else:
            img = Image.new('RGB', (width, height), (128, 128, 128))
            source = 'placeholder'
        img.save(out_path, format='JPEG', quality=quality)
        return {
            'model': f'{source} (drafting only)',
            'prompt': prompt,
            'seed': seed,
            'width': width,
            'height': height,
            'remote_prompt_id': None,
            'generation_seconds': 0,
            'cache_key': key,
        }
    os.makedirs(CACHE, exist_ok=True)
    cached_png = os.path.join(CACHE, key + '.png')
    cached_meta = os.path.join(CACHE, key + '.json')
    if not os.path.exists(cached_png):
        graph = copy.deepcopy(json.loads(Path(GRAPH).read_text(encoding='utf-8')))
        graph['5']['inputs']['prompt'] = prompt
        graph['6']['inputs']['width'] = width
        graph['6']['inputs']['height'] = height
        graph['7']['inputs']['seed'] = seed
        graph['9']['inputs']['filename_prefix'] = 'fnol_corpus/' + key
        started = time.time()
        prompt_id = json.loads(cast(bytes, _call('/prompt', {'prompt': graph})))['prompt_id']
        while True:
            item = json.loads(cast(bytes, _call('/history/' + prompt_id))).get(prompt_id)
            status = (item or {}).get('status', {})
            if status.get('completed'):
                break
            if status.get('status_str') == 'error':
                raise RuntimeError('ComfyUI error: ' + json.dumps(status)[:400])
            if time.time() - started > timeout:
                raise TimeoutError(prompt_id)
            time.sleep(2)
        image = [img for out in item['outputs'].values() for img in out.get('images', [])][0]  # noqa: RUF015 - next() raises StopIteration, not IndexError, on no image
        query = urllib.parse.urlencode(
            {
                'filename': image['filename'],
                'subfolder': image.get('subfolder', ''),
                'type': image.get('type', 'output'),
            }
        )
        with open(cached_png, 'wb') as handle:
            handle.write(cast(bytes, _call('/view?' + query, timeout=120)))
        Path(cached_meta).write_text(
            json.dumps({'remote_prompt_id': prompt_id, 'seconds': round(time.time() - started, 1)})
        )
    meta = json.loads(Path(cached_meta).read_text())
    img = Image.open(cached_png).convert('RGB')
    clean = Image.new('RGB', img.size)
    clean.putdata(list(img.getdata()))
    buffer = io.BytesIO()
    clean.save(buffer, format='JPEG', quality=quality, optimize=True)
    with open(out_path, 'wb') as handle:
        handle.write(buffer.getvalue())
    return {
        'model': model_name(),
        'prompt': prompt,
        'seed': seed,
        'width': width,
        'height': height,
        'remote_prompt_id': meta['remote_prompt_id'],
        'generation_seconds': meta['seconds'],
        'cache_key': key,
    }
