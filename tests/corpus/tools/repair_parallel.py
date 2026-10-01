"""Regenerate flagged model images with new seeds, keeping the GPU busy while gpt-4o checks \
in parallel.

Usage:
  python -m tests.corpus.tools.repair_parallel CORPUS_DIR SPEC_DIR [--attempts 3] [--workers 4]

Same rule as repair_flagged.py, laid out for speed:
- one thread generates candidates on ComfyUI, round by round (seed 1 for every target, then seed 2
  for the targets still open, then seed 3), so the GPU never waits for the model check;
- a pool of workers runs both gpt-4o passes on each candidate as soon as it exists and scores it
  with the corpus flag rule; a target is closed at its first clean candidate;
- at the end each target gets its first clean seed, or the seed with the fewest reasons, with every
  attempt in `seed_history`; the touched packs are rebuilt from the image cache and both passes are
  run on them so the review records belong to the corpus.
Images already repaired (they have a `seed_history`) are skipped. Run it only before the draw.
"""

import json
import os
import queue
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from tests.corpus.tools import corpus_paths, image_review, imagegen, model_check

HERE = os.path.dirname(os.path.abspath(__file__))
SKIP_TRANSFORMS = {'blur', 'truncate', 'to_tiff'}
LOCK = threading.Lock()


def log(message: str) -> None:
    with LOCK:
        print(message, flush=True)


def targets(corpus: str, specs: str) -> list[dict[str, Any]]:
    images = image_review.corpus_images(corpus)
    groups = image_review.by_hash(images)
    found: list[dict[str, Any]] = []
    for image in images:
        if not groups[image['sha256']]['reasons'] or image['review'].get('human_signoff'):
            continue
        inputs = image['entry'].get('inputs', {})
        if inputs.get('transform'):
            # a variant (crop, blur, ...) is left to a person; only direct model images are
            # regenerated
            continue
        with open(os.path.join(specs, image['case_id'] + '.json'), encoding='utf-8') as handle:
            spec = json.load(handle)
        material = next(m for m in spec['materials'] if m['id'] == image['material_id'])
        if material.get('method') != 'image_model' or material.get('seed_history'):
            continue
        facts_path = os.path.join(corpus, 'cases', image['case_id'], 'input', 'facts.json')
        with open(facts_path, encoding='utf-8') as handle:
            facts = json.load(handle)['facts']
        found.append(
            {
                'case_id': image['case_id'],
                'file': image['file'],
                'material': material,
                'facts': facts,
                'entry': image['entry'],
                'base_seed': material['seed'],
                'first_reasons': groups[image['sha256']]['reasons'],
            }
        )
    return found


def score(target: dict[str, Any], path: str, key: str) -> list[str]:
    blind, _ = model_check._ask_blind(key, path)
    led, _ = model_check._ask(
        key, path, target['entry']['purpose'], image_review.fact_text(target['facts'])
    )
    sha = image_review.sha256(path)
    inputs_sha = image_review.prompt_inputs_sha256(target['entry']['purpose'], target['facts'])
    fake = {
        'sha256': sha,
        'entry': target['entry'],
        'inputs_sha256': inputs_sha,
        'review': {
            'model_blind': {
                'sha256': sha,
                'answers': blind,
                'question_version': image_review.BLIND_QUESTION_VERSION,
            },
            'model_check': {'sha256': sha, 'answers': led, 'inputs_sha256': inputs_sha},
        },
    }
    reasons: list[str] = image_review.copy_flag_reasons(fake)
    return reasons


def main() -> None:
    corpus, specs = sys.argv[1], sys.argv[2]
    attempts = int(sys.argv[sys.argv.index('--attempts') + 1]) if '--attempts' in sys.argv else 3
    workers = int(sys.argv[sys.argv.index('--workers') + 1]) if '--workers' in sys.argv else 4
    if image_review.load_sampling(corpus) is not None:
        sys.exit('sampling.json exists: images can no longer be regenerated in this corpus version')
    todo = targets(corpus, specs)
    log(f'{len(todo)} flagged images to try')
    key, source = model_check._secret_key()
    scratch = os.path.join(corpus_paths.WORK, 'candidates')
    os.makedirs(scratch, exist_ok=True)
    results: dict[int, list[dict[str, Any]]] = {i: [] for i in range(len(todo))}
    closed: set[int] = set()
    ready: queue.Queue[tuple[int, int, str] | None] = queue.Queue()

    def generate() -> None:
        for k in range(1, attempts + 1):
            for index, target in enumerate(todo):
                if index in closed:
                    continue
                material = target['material']
                seed = target['base_seed'] + 1000 * k
                width, height = material.get('size', [1216, 912])
                path = os.path.join(scratch, f'{target["case_id"]}-{material["id"]}-{seed}.jpg')
                try:
                    imagegen.generate(material['prompt'], seed, width, height, path)
                except Exception as error:  # one failed candidate must not stop the run
                    log(f'  generate failed {target["case_id"]} seed {seed}: {error}')
                    continue
                ready.put((index, seed, path))
            # Let the checks of this round catch up before deciding which targets stay open.
            ready.join()
        ready.put(None)

    def check(item: tuple[int, int, str]) -> None:
        index, seed, path = item
        target = todo[index]
        try:
            reasons = score(target, path, key)
        except Exception as error:
            reasons = [f'check failed: {error}']
        with LOCK:
            results[index].append({'seed': seed, 'reasons': reasons})
            if not reasons:
                closed.add(index)
        log(
            f'  {target["case_id"]} {target["file"]} seed {seed}: '
            f'{"clean" if not reasons else len(reasons)} '
        )

    generator = threading.Thread(target=generate)
    generator.start()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        while True:
            item = ready.get()
            if item is None:
                ready.task_done()
                break
            future = pool.submit(check, item)
            future.add_done_callback(lambda _f: ready.task_done())
    generator.join()

    touched: set[str] = set()
    for index, target in enumerate(todo):
        spec_path = os.path.join(specs, target['case_id'] + '.json')
        with open(spec_path, encoding='utf-8') as handle:
            spec = json.load(handle)
        material = next(m for m in spec['materials'] if m['id'] == target['material']['id'])
        history = [
            {'seed': target['base_seed'], 'reasons': target['first_reasons']},
            *sorted(results[index], key=lambda r: r['seed']),
        ]
        clean = [r for r in history[1:] if not r['reasons']]
        chosen = clean[0] if clean else min(history, key=lambda r: len(r['reasons']))
        material['seed'] = chosen['seed']
        material['seed_history'] = history
        with open(spec_path, 'w', encoding='utf-8') as handle:
            json.dump(spec, handle, indent=1, ensure_ascii=False)
        touched.add(spec_path)
        log(
            f'{target["case_id"]} {target["file"]}: seed {chosen["seed"]} '
            f'{"clean" if not chosen["reasons"] else "still flagged"}'
        )
    if touched:
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        subprocess.run(
            [sys.executable, '-m', 'tests.corpus.tools.build_pack', corpus, *sorted(touched)],
            cwd=corpus_paths.REPO_ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        cases = sorted({os.path.basename(p)[:-5] for p in touched})
        subprocess.run(
            [sys.executable, '-m', 'tests.corpus.tools.model_check', '--blind', corpus, *cases],
            cwd=corpus_paths.REPO_ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        subprocess.run(
            [sys.executable, '-m', 'tests.corpus.tools.model_check', corpus, *cases],
            cwd=corpus_paths.REPO_ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
    log('done')


if __name__ == '__main__':
    main()
