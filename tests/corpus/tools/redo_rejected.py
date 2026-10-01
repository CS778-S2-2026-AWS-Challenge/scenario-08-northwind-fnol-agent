# ruff: noqa: RUF001  (Chinese user-facing text uses full-width punctuation on purpose)
"""Generate candidates for images a person rejected after the draw (v1, 2026-10-01).

Usage:
  python -m tests.corpus.tools.redo_rejected generate
      Three candidates per rejected image, into tests/corpus/work/redo/.
  python -m tests.corpus.tools.redo_rejected sheet OUT.html
      A page where the reviewer picks A, B, C or none.
  python -m tests.corpus.tools.redo_rejected apply PICKS.json --by @login
      PICKS.json maps "CASE/material_id" to the chosen seed. Writes the new prompt and seed into the
      spec with a `redo_history` entry (old prompt, old seed, the rejection, the candidate seeds and
      the pick), rebuilds the packs, runs both gpt-4o passes and records the pick as a per-image
      sign-off by the person who chose it.

Each prompt below is rewritten from the reviewer's rejection reason. After the draw a changed image
is signed per image, so choosing a candidate is that sign-off; gpt-4o is only recorded, not asked.
"""

import json
import os
import subprocess
import sys
from typing import Any, TypedDict

from tests.corpus.tools import corpus_paths, imagegen

HERE = os.path.dirname(os.path.abspath(__file__))
SPECS = corpus_paths.SPECS_V1
CORPUS = corpus_paths.CORPUS_V1
OUT = os.path.join(corpus_paths.WORK, 'redo')
SEED_OFFSETS = (7001, 7002, 7003)


class RedoEntry(TypedDict):
    """One rejected image: its number on the v1 sheet, the rejection and the rewritten prompt."""

    sheet: int
    rejection: str
    prompt: str


REDO: dict[str, RedoEntry] = {
    'CTL-C-010/photo-turntable': {
        'sheet': 5,
        'rejection': 'Only the plastic lid is broken; no damage to the turntable itself is visible',
        'prompt': (
            'Realistic smartphone photo, close-up from above of a walnut-veneer record turntable '
            'lying on a grey carpet, with its clear plastic dust cover lifted fully open. The thin '
            'silver tone arm is clearly bent sideways in a sharp kink halfway along its length and '
            'points off the edge of the empty platter instead of resting on its stand. The open '
            'dust cover has a crack across one corner. The frame shows the platter, the bent tone '
            'arm and its base, and the cracked corner of the cover. Afternoon window light. Plain '
            'turntable with no badges. No people, no text.'
        ),
    },
    'CTL-H-008/photo-blades': {
        'sheet': 8,
        'rejection': (
            'Cannot tell these are louvre blades; it looks like corrugated plastic sheeting'
        ),
        'prompt': (
            'Realistic smartphone photo of the outside of a bathroom window on a red brick house '
            'wall. The aluminium louvre window frame is empty: the narrow horizontal glass slats '
            'have been pulled out and two of the thin metal side clips are bent outward. On the '
            'gravel path directly below the window lie two broken louvre blades, each a flat strip '
            'of frosted glass about 10 cm wide and 60 cm long, one snapped in half with sharp '
            'shards, and four whole frosted glass louvre strips leaning flat against the bottom of '
            'the wall. Late afternoon light. No people, no text.'
        ),
    },
    'CTL-H-014/photo-laundry': {
        'sheet': 10,
        'rejection': 'The water damage shown is too small for the facts',
        'prompt': (
            'Realistic smartphone photo taken from the laundry doorway showing the whole floor of '
            'a small laundry room: the grey vinyl flooring is lifted into large bubbles and long '
            'raised ridges across almost the entire floor, about six square metres, with shallow '
            'standing water spread over most of it and reflecting the window light. A plain white '
            'washing machine stands against the back wall with a split rubber inlet hose hanging '
            'behind it. The bottom of the painted wall lining is swollen and stained along both '
            'side walls. Morning daylight. No people, no text.'
        ),
    },
    'CTL-H-024/photo-hallway': {
        'sheet': 12,
        # Round 2: the round-1 candidates were all rejected because the swollen wall
        # bottom was not clear.
        'rejection': (
            'The cupboard floor named in the purpose is not visible; then (redo round 1) the '
            'swollen bottom of the wall is not clear'
        ),
        'prompt': (
            'Realistic smartphone photo taken in a narrow house hallway, crouching beside an open '
            'hallway cupboard and looking along the wall. In the foreground, just inside the open '
            'cupboard door, the particle-board cupboard floor is dark, soaked and swollen, with a '
            'puddle around the base of a white hot water cylinder. The hallway wall runs away from '
            'the camera on the right: its bottom 30 cm of white plasterboard is clearly swollen '
            'and bulging outward, the paint is blistered and peeling, and a dark brown water line '
            'runs along the wall about 30 cm above the skirting board, which is pushed away from '
            'the wall. The beige hallway carpet along the wall is dark and soaked. Warm ceiling '
            'light, evening. No people, no text.'
        ),
    },
    'CTL-M-003/photo-gatepost': {
        'sheet': 16,
        'rejection': (
            'Implausible: a car sliding down the driveway would not hit the gatepost on this side'
        ),
        'prompt': (
            'Realistic smartphone photo taken standing on a steep concrete residential driveway on '
            'a frosty morning, looking down the driveway towards the street. At the bottom of the '
            'driveway, a red brick gatepost stands right at the edge of the driveway. The side '
            'face of the pillar that lines the driveway has a long horizontal scrape at car door '
            'height, running in the direction of the driveway, with streaks of silver car paint '
            'rubbed into the bricks and some brick dust on the frosty concrete below it. Frost on '
            'the lawn, low winter sun, long shadows. No cars, no people, no text.'
        ),
    },
    'CTL-M-021/photo-front-right': {
        'sheet': 20,
        'rejection': (
            'The licence plate is completely blank, which does not look like an ordinary photo'
        ),
        'prompt': (
            'Realistic smartphone photo taken standing beside the right side of a white hatchback '
            'at the side of a city street, looking along the side of the car towards its front: '
            'the front wing above the front right wheel is pushed in and creased, the headlight '
            'lens at the corner is cracked, and the right end of the front bumper is split and '
            'sagging, with streaks of grey paint transfer. The photo is taken from the side, so '
            'only the side of the car is seen: the front wheel, the front wing, the side of the '
            'headlight and the end of the bumper. Clear morning light. No people, no text.'
        ),
    },
    'CTL-M-023/photo-door': {
        'sheet': 22,
        'rejection': (
            'The damage is on the rear quarter panel, not the door, as the image-only pass said'
        ),
        'prompt': (
            'Realistic smartphone photo at night under orange street lights, lit by the phone '
            'flash: side view of the left rear passenger door of a dark green station wagon, with '
            'the door handle, the door window and the door shut lines clearly visible. The middle '
            'of the rear door, just below the door handle, is deeply dented with a sharp '
            'horizontal crease that continues past the rear edge of the door onto the rear wheel '
            'arch, with streaks of silver paint transfer on the door. No people, no text.'
        ),
    },
    'CTL-M-024/photo-side': {
        'sheet': 23,
        'rejection': (
            'The damage is on the rear quarter panel, not the door, as the image-only pass said'
        ),
        'prompt': (
            'Realistic smartphone photo in bright late-morning sun: side view of the rear left '
            'passenger door of a silver compact SUV parked on a suburban street, with the door '
            'handle, the door window and the door shut lines clearly visible. The rear door is '
            'dented inward with a long horizontal crease at bumper height that runs from the '
            'middle of the door back onto the panel above the rear wheel, with red paint transfer '
            'along the crease. The frame shows the rear door, the rear wheel arch and the rear '
            'wheel. No people, no text.'
        ),
    },
    'CTL-M-026/photo-tailgate': {
        'sheet': 24,
        'rejection': 'Does not look like tailgate damage',
        'prompt': (
            'Realistic smartphone photo taken close behind the right rear corner of a grey '
            'mid-size SUV in early evening light. The frame shows the right half of the lift-up '
            'tailgate from the bottom of its rear window down to the bumper, the right tail light '
            'and the right corner of the rear bumper. The bottom edge of the tailgate panel is '
            'clearly dented inward with cracked paint just above the bumper, the gap between the '
            'tailgate and the tail light is uneven, and the bumper corner below is pushed in and '
            'cracked with one round parking sensor hanging out on its wire. No people, no text.'
        ),
    },
    'CTL-M-032/photo-rear-window': {
        'sheet': 30,
        'rejection': 'Shows a side passenger window, not the rear window',
        'prompt': (
            'Realistic smartphone photo in morning daylight, taken standing directly behind a '
            'white SUV parked in a driveway and looking at the back of the car from above bumper '
            'height. The large rear windscreen in the top of the tailgate is completely shattered, '
            'with only a jagged edge of crazed glass left in its frame, and a thick gum tree '
            'branch lies across the roof and over the top of the tailgate. The roof spoiler above '
            'the rear windscreen is snapped in the middle. Through the empty rear window frame the '
            'rear seats are covered with glass fragments and gum leaves. The frame shows the upper '
            'half of the back of the car only. No people, no text.'
        ),
    },
    'CTL-M-036/photo-driveway': {
        'sheet': 34,
        'rejection': 'The contact damage looks much lighter than the facts describe',
        'prompt': (
            'Realistic smartphone photo in morning light, looking down a steep concrete driveway '
            'to the street. At the bottom of the driveway a brick letterbox pillar has been hit '
            'hard: its corner facing the driveway is smashed away, a large crack runs up through '
            'the pillar, and about a dozen loose bricks and broken mortar lie scattered on the '
            'driveway and the grass. Deep tyre ruts run across the grass verge from the letterbox '
            'towards a deep roadside ditch. Suburban street, trees. No vehicles, no people, no '
            'text.'
        ),
    },
}


def _spec(case_id: str) -> tuple[str, dict[str, Any]]:
    path = os.path.join(SPECS, case_id + '.json')
    with open(path, encoding='utf-8') as spec_file:
        return path, json.load(spec_file)


def generate(only: list[str] | None = None, offsets: tuple[int, ...] = SEED_OFFSETS) -> None:
    """Candidates for every image, or with `only` for those keys, merged into candidates.json."""
    os.makedirs(OUT, exist_ok=True)
    index = os.path.join(OUT, 'candidates.json')
    previous: list[dict[str, Any]]
    if os.path.exists(index):
        with open(index, encoding='utf-8') as index_file:
            previous = json.load(index_file)
    else:
        previous = []
    plan = [row for row in previous if only and row['key'] not in only]
    for key, redo in REDO.items():
        if only and key not in only:
            continue
        case_id, material_id = key.split('/')
        _, spec = _spec(case_id)
        material = next(m for m in spec['materials'] if m['id'] == material_id)
        width, height = material.get('size', [1216, 912])
        seeds = [material['seed'] + offset for offset in offsets]
        files: list[dict[str, Any]] = []
        for seed in seeds:
            path = os.path.join(OUT, f'{case_id}-{material_id}-{seed}.jpg')
            try:
                imagegen.generate(redo['prompt'], seed, width, height, path)
                files.append({'seed': seed, 'file': os.path.basename(path)})
                print(f'  {case_id} {material_id} seed {seed}', flush=True)
            except Exception as error:  # one failed candidate must not stop the run
                print(f'  FAILED {case_id} {material_id} seed {seed}: {error}', flush=True)
        plan.append(
            {
                'key': key,
                'case_id': case_id,
                'material_id': material_id,
                'file': material['file'],
                'sheet': redo['sheet'],
                'rejection': redo['rejection'],
                'purpose': material.get('purpose', ''),
                'old_seed': material['seed'],
                'candidates': files,
            }
        )
    with open(os.path.join(OUT, 'candidates.json'), 'w', encoding='utf-8') as out_file:
        json.dump(plan, out_file, indent=1, ensure_ascii=False)
    print(f'done: {sum(len(p["candidates"]) for p in plan)} candidates for {len(plan)} images')


ZH = {
    'CTL-C-010/photo-turntable': (
        '唱机本身坏了：唱臂明显弯折，防尘盖一角裂开',
        '只有塑料盖坏了，看不出唱机本身坏了',
    ),
    'CTL-H-008/photo-blades': (
        '浴室外墙上的百叶窗框空了；地上两片碎掉的磨砂玻璃百叶片，墙边靠着四片完好的',
        '看不出是百叶窗玻璃片，像塑料波纹板',
    ),
    'CTL-H-014/photo-laundry': (
        '洗衣房整个地板（约 6 平方米）的地板胶起泡翘起，地上有积水，墙根泡胀',
        '水渍太小',
    ),
    'CTL-H-024/photo-hallway': (
        (
            '热水器柜的地板泡胀发黑；走廊墙根下面 30 厘米明显鼓起、油漆起泡脱落、有一道水痕；'
            '走廊地毯湿透'
        ),
        '第一次：看不到橱柜地板；第二次（上一轮三张）：墙根不明显',
    ),
    'CTL-M-003/photo-gatepost': (
        '倒车下坡时车左侧擦到门柱：门柱靠车道的那一面有水平擦痕和银色车漆',
        '逻辑不对，滑下来不该撞在这一侧',
    ),
    'CTL-M-021/photo-front-right': (
        '从侧面拍白色两厢车右前角：翼子板凹陷、大灯裂、保险杠右端裂开，拍不到车牌',
        '车牌完全是空的',
    ),
    'CTL-M-023/photo-door': (
        '左后门（看得到门把手、车窗、门缝）中间凹陷，折痕一直延伸到后轮拱',
        '损坏不在门上，在后侧围板',
    ),
    'CTL-M-024/photo-side': (
        '左后门（看得到门把手、车窗、门缝）凹陷，长折痕从门中间延伸到后轮上方，有红色车漆',
        '损坏不在门上，在后侧围板',
    ),
    'CTL-M-026/photo-tailgate': (
        'SUV 尾门右下边缘凹陷；下面保险杠角裂开，一个倒车雷达吊出来',
        '不像尾门损坏',
    ),
    'CTL-M-032/photo-rear-window': (
        '从车正后方拍：后挡风玻璃全碎，树枝横在车顶和尾门上，尾翼断了',
        '拍的是侧窗不是后窗',
    ),
    'CTL-M-036/photo-driveway': (
        '车道底部的砖砌信箱被撞得很厉害：角被撞掉、大裂缝、十几块砖散在地上，草地上有车辙通向沟渠',
        '碰得太轻了',
    ),
}
LETTERS = 'ABC'


def pick_sheet(out_path: str, only: list[str] | None = None) -> None:
    """A page where the reviewer picks one candidate per rejected image, or none."""
    import base64
    import html

    with open(os.path.join(OUT, 'candidates.json'), encoding='utf-8') as index_file:
        candidates: list[dict[str, Any]] = json.load(index_file)
    plan = [row for row in candidates if not only or row['key'] in only]
    cards: list[str] = []
    for row in plan:
        expect, rejection = ZH[row['key']]
        options: list[str] = []
        for letter, cand in zip(LETTERS, row['candidates'], strict=False):
            with open(os.path.join(OUT, cand['file']), 'rb') as image_file:
                data = base64.b64encode(image_file.read()).decode()
            options.append(f'''<figure class="cand" data-letter="{letter}">
  <div class="pic"><img src="data:image/jpeg;base64,{data}" alt="{letter}" loading="lazy"></div>
  <button type="button" class="pick">选 {letter}</button></figure>''')
        cards.append(
            f'''
<section class="card" data-key="{html.escape(row['key'])}" '''
            f"""data-label="#{row['sheet']} {row['case_id']} {html.escape(row['file'])}">
 <div class="head"><span class="num">#{row['sheet']}</span>"""
            f"""<span class="name">{row['case_id']} · {html.escape(row['file'])}</span></div>
 <p><b>你上次不通过的原因：</b>{html.escape(rejection)}</p>
 <p><b>这次要拍成：</b>{html.escape(expect)}</p>
 <div class="cands">{''.join(options)}</div>
 <div class="choose"><button type="button" class="none">三张都不行</button>
  <input type="text" class="reason" placeholder="都不行的原因" hidden></div>
</section>"""
        )
    page = PICK_PAGE.replace('{{CARDS}}', ''.join(cards)).replace('{{TOTAL}}', str(len(plan)))
    with open(out_path, 'w', encoding='utf-8') as page_file:
        page_file.write(page)
    print(f'pick sheet: {len(plan)} images -> {out_path}')


def apply(picks_path: str, by: str) -> None:
    (
        """Write the picked prompt and seed into each spec, rebuild, run both passes and sign """
        """per image."""
    )
    with open(picks_path, encoding='utf-8') as picks_file:
        picks: dict[str, Any] = json.load(picks_file)
    with open(os.path.join(OUT, 'candidates.json'), encoding='utf-8') as index_file:
        plan: dict[str, dict[str, Any]] = {row['key']: row for row in json.load(index_file)}
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    touched: list[dict[str, Any]] = []
    for key, seed in picks.items():
        row = plan[key]
        if seed not in [c['seed'] for c in row['candidates']]:
            sys.exit(f'{key}: seed {seed} is not one of its candidates')
        path, spec = _spec(row['case_id'])
        material = next(m for m in spec['materials'] if m['id'] == row['material_id'])
        material.setdefault('redo_history', []).append(
            {
                'date': '2026-10-01',
                'rejected_by': by,
                'rejection': REDO[key]['rejection'],
                'old_prompt': material['prompt'],
                'old_seed': material['seed'],
                'candidates': [c['seed'] for c in row['candidates']],
                'picked': seed,
                'picked_by': by,
            }
        )
        material['prompt'] = REDO[key]['prompt']
        material['seed'] = seed
        with open(path, 'w', encoding='utf-8') as spec_file:
            json.dump(spec, spec_file, indent=1, ensure_ascii=False)
        touched.append(row)
    cases = sorted({row['case_id'] for row in touched})
    subprocess.run(
        [
            sys.executable,
            '-m',
            'tests.corpus.tools.build_pack',
            CORPUS,
            *[os.path.join(SPECS, c + '.json') for c in cases],
        ],
        cwd=corpus_paths.REPO_ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [sys.executable, '-m', 'tests.corpus.tools.model_check', '--blind', CORPUS, *cases],
        cwd=corpus_paths.REPO_ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        [sys.executable, '-m', 'tests.corpus.tools.model_check', CORPUS, *cases],
        cwd=corpus_paths.REPO_ROOT,
        env=env,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    for row in touched:
        letter = LETTERS[[c['seed'] for c in row['candidates']].index(picks[row['key']])]
        note = (
            f'Picked candidate {letter} of three on the redo sheet after the rejection on the '
            f'v1 sheet (#{row["sheet"]})'
        )
        subprocess.run(
            [
                sys.executable,
                '-m',
                'tests.corpus.tools.review_tool',
                'sign',
                CORPUS,
                row['case_id'],
                row['file'],
                'accepted',
                note,
                '--by',
                by,
            ],
            cwd=corpus_paths.REPO_ROOT,
            env=env,
            check=True,
        )
        print(f'{row["case_id"]} {row["file"]}: candidate {letter} signed')


PICK_PAGE = (
    """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>挑图</title>
<style>
:root { --bg:#f6f5f2; --card:#fff; --fg:#1d1d1b; --muted:#6b6a66; --line:#dddbd5; --ok:#1f7a45; """
    """--no:#b3261e; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#151514; """
    """--card:#1f1f1d; --fg:#ecebe7; --muted:#a3a19b; --line:#34332f; --ok:#5cc28a; """
    """--no:#f08b84; } }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, "Microsoft YaHei", """
    """sans-serif; margin:0; }
.bar { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid """
    """var(--line); padding:10px 16px; display:flex; gap:12px; align-items:center; """
    """flex-wrap:wrap; }
.bar b { font-size:18px; } .bar button { font:inherit; padding:6px 14px; border-radius:8px; """
    """border:1px solid var(--line); background:var(--bg); color:var(--fg); cursor:pointer; }
#copied { color:var(--muted); font-size:14px; }
main { max-width:1200px; margin:0 auto; padding:16px; }
.intro, .card, .result { background:var(--card); border:1px solid var(--line); """
    """border-radius:12px; padding:16px 20px; margin-bottom:20px; }
.card { border-left:6px solid var(--line); } .card.done { border-left-color:var(--ok); } """
    """.card.none { border-left-color:var(--no); }
.head { display:flex; gap:10px; align-items:center; flex-wrap:wrap; } .num { font-size:22px; """
    """font-weight:700; } .name { color:var(--muted); font-size:13px; word-break:break-all; }
.cands { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr)); gap:12px; """
    """margin-top:10px; }
.cand { margin:0; border:3px solid transparent; border-radius:10px; padding:4px; }
.cand.chosen { border-color:var(--ok); }
.pic img { width:100%; height:auto; border-radius:8px; display:block; cursor:zoom-in; }
.pic.big { position:fixed; inset:0; z-index:10; background:rgba(0,0,0,.92); display:flex; """
    """align-items:center; justify-content:center; padding:8px; }
.pic.big img { width:auto; max-width:100%; max-height:100%; cursor:zoom-out; }
.cand button, .choose button { font:inherit; font-size:16px; padding:8px 18px; margin-top:6px; """
    """border-radius:10px; border:2px solid var(--line); background:var(--bg); color:var(--fg); """
    """cursor:pointer; }
.cand.chosen button { background:var(--ok); border-color:var(--ok); color:#fff; }
.card.none .none { background:var(--no); border-color:var(--no); color:#fff; }
.choose { display:flex; gap:10px; flex-wrap:wrap; margin-top:10px; }
.reason { flex:1 1 260px; font:inherit; padding:8px; border-radius:10px; border:2px solid """
    """var(--no); background:var(--card); color:var(--fg); }
#out { width:100%; min-height:120px; font:14px/1.5 ui-monospace, monospace; """
    """background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:8px; """
    """padding:8px; }
</style></head><body>
<div class="bar"><b>已挑 <span id="done">0</span> / {{TOTAL}}</b><button type="button" """
    """id="copy">复制结果</button><span id="copied"></span></div>
<main>
<div class="intro"><p><b>一共 {{TOTAL}} 张要重做的图，每张有 3 个候选（A、B、C）。</b></p>
<p>每张选一个最好的：和"这次要拍成"对得上，没有能读的车牌、人脸、logo、文字，像普通手机照片。三张都不行就点"三张都不行"，写一句原因。点图片可以放大。</p>
<p>选中的那张就算你签了字。看完点最上面的"复制结果"发给我。</p></div>
{{CARDS}}
<div class="result"><b>结果</b><textarea id="out" readonly></textarea></div>
</main>
<script>
const STORE = 'redo-pick-v1-20261001';
let state = {};
try { state = JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch (e) { state = {}; }
function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
const cards = [...document.querySelectorAll('.card')];
function render() {
  let done = 0; const lines = [];
  for (const card of cards) {
    const s = state[card.dataset.key] || {};
    card.querySelectorAll('.cand').forEach((c) => c.classList.toggle('chosen', s.pick === """
    """c.dataset.letter));
    card.classList.toggle('done', !!s.pick); card.classList.toggle('none', s.none === true);
    const reason = card.querySelector('.reason'); reason.hidden = s.none !== true;
    if (document.activeElement !== reason) reason.value = s.r || '';
    if (s.pick || s.none) done++;
    lines.push(card.dataset.label + ' ' + (s.pick ? '选 ' + s.pick : s.none ? '都不行：' + (s.r """
    """|| '（没写原因）') : '还没挑'));
  }
  document.getElementById('done').textContent = done;
  document.getElementById('out').value = '挑图结果 ' + done + '/' + cards.length + '\\n' + """
    """lines.join('\\n');
}
for (const card of cards) {
  const key = card.dataset.key;
  card.querySelectorAll('.cand').forEach((c) => {
    c.querySelector('.pick').onclick = () => { state[key] = { pick: c.dataset.letter }; save(); """
    """render(); };
    const pic = c.querySelector('.pic'); pic.onclick = () => pic.classList.toggle('big');
  });
  card.querySelector('.none').onclick = () => { state[key] = { none: true, r: (state[key] || """
    """{}).r || '' }; save(); render(); card.querySelector('.reason').focus(); };
  card.querySelector('.reason').oninput = (e) => { state[key] = { none: true, r: e.target.value """
    """}; save(); render(); };
}
document.getElementById('copy').onclick = async () => {
  render(); const out = document.getElementById('out'), m = document.getElementById('copied');
  try { await navigator.clipboard.writeText(out.value); m.textContent = '已复制'; }
  catch (e) { out.focus(); out.select(); try { document.execCommand('copy'); m.textContent = """
    """'已复制'; } catch (e2) { m.textContent = '请手动复制最下面的结果'; } }
  setTimeout(() => { m.textContent = ''; }, 3000);
};
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') """
    """document.querySelectorAll('.pic.big').forEach((p) => p.classList.remove('big')); });
render();
</script></body></html>"""
)


if __name__ == '__main__':
    command = sys.argv[1:2]
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else None
    if command == ['generate']:
        offsets = (
            tuple(int(o) for o in sys.argv[sys.argv.index('--offsets') + 1].split(','))
            if '--offsets' in sys.argv
            else SEED_OFFSETS
        )
        generate(only, offsets)
    elif command == ['sheet']:
        pick_sheet(sys.argv[2], only)
    elif command == ['apply'] and '--by' in sys.argv:
        apply(sys.argv[2], sys.argv[sys.argv.index('--by') + 1])
    else:
        sys.exit(__doc__)
