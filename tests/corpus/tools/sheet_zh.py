# ruff: noqa: RUF001  (Chinese user-facing text uses full-width punctuation on purpose)
"""A Chinese sign-off sheet for the images a person must look at, with buttons and a copyable \
result.

Usage:
  python -m tests.corpus.tools.sheet_zh CORPUS_DIR OUT.html

Same images and order as `review_tool.py sheet --needed` (flagged first, then sampled). The English
texts (purpose, relevant facts, what gpt-4o said) are translated once by gpt-4o and cached in
work/sheet-zh-translations.json; the English original stays on the page under each translation.
The page only collects decisions: the person copies the result text back, and every decision is
still recorded with `review_tool.py sign`.
"""

import base64
import html
import io
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageFile

from tests.corpus.tools import corpus_paths, image_review, model_check

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(corpus_paths.WORK, 'sheet-zh-translations.json')
ImageFile.LOAD_TRUNCATED_IMAGES = True

TRANSLATE = """Translate each English text in this JSON object into simple, natural Simplified \
Chinese for a
non-specialist reviewer. Keep car-part and building-part names accurate (bonnet = 引擎盖, \
tailgate = 尾门,
spouting = 雨水槽, quarter panel = 后翼子板, kerb = 路缘石). Keep numbers, units and NZD amounts \
as they are.
Return a JSON object with exactly the same keys, each value being the Chinese translation.

{texts}"""


def _translate(key: str, texts: list[str]) -> dict[str, str]:
    """English -> Chinese for every text not yet in the cache; failures fall back to English."""
    cache: dict[str, str] = (
        json.loads(Path(CACHE).read_text(encoding='utf-8')) if os.path.exists(CACHE) else {}
    )
    todo = sorted({t for t in texts if t and t not in cache})
    for start in range(0, len(todo), 25):
        chunk = {f't{i}': text for i, text in enumerate(todo[start : start + 25])}
        body = {
            'model': model_check.MODEL,
            'temperature': 0,
            'response_format': {'type': 'json_object'},
            'messages': [
                {
                    'role': 'user',
                    'content': TRANSLATE.format(
                        texts=json.dumps(chunk, ensure_ascii=False, indent=1)
                    ),
                }
            ],
        }
        try:
            response = httpx.post(
                model_check.ENDPOINT,
                json=body,
                timeout=180.0,
                headers={
                    'Authorization': f'Bearer {key}',
                    'X-Title': 'Northwind FNOL controlled corpus sheet translation',
                },
            )
            response.raise_for_status()
            answer = json.loads(response.json()['choices'][0]['message']['content'])
        except (httpx.HTTPError, ValueError, KeyError) as error:
            print(f'  translation failed for {len(chunk)} texts, English kept: {error}')
            continue
        for slot, text in chunk.items():
            if isinstance(answer.get(slot), str):
                cache[text] = answer[slot]
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        with open(CACHE, 'w', encoding='utf-8') as handle:
            json.dump(cache, handle, ensure_ascii=False, indent=1)
        print(f'  translated {min(start + 25, len(todo))}/{len(todo)}')
    return cache


def _image_data(path: str) -> tuple[str | None, str | None]:
    """JPEG data for the page. TIFF and cut-off files are converted where possible, since a \
browser cannot show them."""
    raw = Path(path).read_bytes()
    if path.lower().endswith(('.jpg', '.jpeg')):
        return base64.b64encode(raw).decode(), None
    try:
        image = Image.open(io.BytesIO(raw)).convert('RGB')
        out = io.BytesIO()
        image.save(out, 'JPEG', quality=90)
        return base64.b64encode(out.getvalue()).decode(), '浏览器打不开这种格式，下面是转换后的预览'
    except Exception:  # a broken file is the point of some materials
        return None, '文件坏了，完全打不开，没有预览'


def _readable(value: Any) -> str:
    """A fact as one plain sentence: item lists become their descriptions, area lists a comma \
list."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [
            str(v.get('contents.item.description', '')) if isinstance(v, dict) else str(v)
            for v in value
        ]
        return (
            'Items: ' + '; '.join(p for p in parts if p)
            if any(isinstance(v, dict) for v in value)
            else ', '.join(parts)
        )
    return json.dumps(value, ensure_ascii=False)


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    return [str(value)] if value and str(value).strip() else []


def _reason_zh(
    reason: str,
    entry: dict[str, Any],
    blind: dict[str, Any] | None,
    led: dict[str, Any] | None,
    zh: dict[str, str],
    damage: str = '',
) -> str:
    """One flag reason in plain Chinese, with what the reviewer should look for."""

    def t(text: str) -> str:
        return zh.get(text, text)

    if reason.startswith('deliberately broken file'):
        return (
            '<b>这是故意做坏的文件</b>（用来测试系统会不会拒收）。'
            'AI 读不了这种文件，所以这张没有 AI 描述，'
            '这是正常的，你是唯一看它的人。打不开或只显示一半也是正常的。'
            '看能看到的部分：大体是不是客户说的那处损坏；有没有车牌、人脸、logo、能读的字。没问题就点通过。'
        )
    if reason.startswith('deliberately unreadable image'):
        said = (
            f'客户说坏的地方是：<b>{html.escape(t(damage))}</b>'
            f'<span class="en">（{html.escape(damage)}）</span>。'
            if damage
            else ''
        )
        return (
            f'<b>这是故意拍糊的图</b>（用来测试系统会不会让客户重拍）。{said}'
            '请看照片：<b>能看出这个损坏吗？</b>看不出就点通过（糊得合格）；能看清损坏，点不通过（糊得不够）。'
            '能认出是什么东西没关系，关键是看不清坏的地方。'
        )
    if reason.startswith('image-only pass names'):
        seen = str((blind or {}).get('what_is_damaged', ''))
        expected = entry.get('expect_object', [])
        return (
            f'AI 只看图（不给它任何描述）时，说坏的是「{html.escape(t(seen))}」'
            f'<span class="en">（{html.escape(seen)}）</span>，'
            f'但这张图应该拍的是「{html.escape(t(expected[0]) if expected else "")}」'
            f'<span class="en">（{html.escape(", ".join(expected))}）</span>。'
            '请你看看：图里坏的到底是不是它？只是叫法不同的话，点通过。'
        )
    if 'matches_facts is' in reason:
        level: Any = (led or {}).get('matches_facts')
        words = {'partly': '只有部分对得上', 'no': '对不上'}.get(level, str(level))
        items = _list((led or {}).get('mismatches')) + _list((led or {}).get('notes'))
        detail = ''.join(
            f'<li>{html.escape(t(i))}<span class="en">（{html.escape(i)}）</span></li>'
            for i in items
        )
        return (
            f'AI 拿着描述对照这张图，说「{words}」。它说的不一致：<ul>{detail}</ul>'
            '请你判断：这些差别要紧吗？描述里说的东西图上大体都有，就点通过。'
        )
    if 'licence plate is' in reason:
        plate = str((blind or {}).get('licence_plate') or (led or {}).get('licence_plate') or '')
        return (
            f'AI 说图里有车牌（{html.escape(t(plate))}）。'
            '请看：车牌上的字能读出来吗？看起来像外国车牌吗？读不出、也不像外国车牌，就点通过。'
        )
    for key, label in (
        ('people', '人或人脸'),
        ('brand_logo', '品牌标志'),
        ('readable_text', '能读的文字'),
    ):
        if f' pass: {key} ' in reason:
            values = _list((blind or {}).get(key)) + _list((led or {}).get(key))
            shown = '；'.join(html.escape(t(v)) for v in dict.fromkeys(values))
            return f'AI 说图里有{label}：{shown}。请看是不是真的有。有的话点不通过。'
    return f'其他原因（原文）：{html.escape(reason)}'


def main() -> None:
    corpus, out_path = sys.argv[1], sys.argv[2]
    images = image_review.corpus_images(corpus)
    groups = image_review.by_hash(images)
    sampling = image_review.load_sampling(corpus)
    if sampling is None:
        sys.exit('no sampling.json yet: run review_tool.py sample first')
    sampled = {r['sha256'] for r in sampling['sample']}

    def rank(image: dict[str, Any]) -> int:
        return 0 if groups[image['sha256']]['reasons'] else 1 if image['sha256'] in sampled else 2

    needed = [i for i in sorted(images, key=rank) if rank(i) < 2]
    rows: list[dict[str, Any]] = []
    for image in needed:
        case_dir = os.path.join(corpus, 'cases', image['case_id'])
        facts: dict[str, Any] = json.loads(
            Path(os.path.join(case_dir, 'input', 'facts.json')).read_text(encoding='utf-8')
        )['facts']
        record = image['review']
        blind = (record.get('model_blind') or {}).get('answers')
        led = (record.get('model_check') or {}).get('answers')
        hints = [(k, _readable(facts[k])) for k in image_review.FACT_HINTS if k in facts]
        # by_hash prefixes every reason with "CASE/file: " of the copy it came from.
        reasons = [
            r.split(': ', 1)[1] if re.match(r'^CTL-[A-Z]-\d+/[^:]+: ', r) else r
            for r in groups[image['sha256']]['reasons']
        ]
        damage = next(
            (
                facts[k]
                for k in ('loss.description', 'vehicle.damage_description', 'incident.description')
                if isinstance(facts.get(k), str)
            ),
            '',
        )
        rows.append(
            {
                'image': image,
                'facts': hints,
                'blind': blind,
                'led': led,
                'reasons': reasons,
                'damage': damage,
            }
        )

    texts: list[str] = []
    for row in rows:
        entry = row['image']['entry']
        texts += (
            [entry.get('purpose', '')]
            + [v for _, v in row['facts']]
            + entry.get('expect_object', [])[:1]
        )
        texts.append(str((row['blind'] or {}).get('what_is_damaged', '')))
        texts.append(str((row['blind'] or {}).get('description', '')))
        texts += _list((row['led'] or {}).get('mismatches')) + _list(
            (row['led'] or {}).get('notes')
        )
        for key in ('licence_plate',):
            texts.append(str((row['blind'] or {}).get(key) or (row['led'] or {}).get(key) or ''))
        for key in image_review.PRIVACY_LISTS:
            texts += _list((row['blind'] or {}).get(key)) + _list((row['led'] or {}).get(key))
    key, _ = model_check._secret_key()
    zh = _translate(key, texts)

    def both(text: object) -> str:
        text = str(text)
        if not text:
            return ''
        if zh.get(text) and zh[text] != text:
            return f'{html.escape(zh[text])}<div class="en">{html.escape(text)}</div>'
        return html.escape(text)

    cards: list[str] = []
    for number, row in enumerate(rows, 1):
        image, entry = row['image'], row['image']['entry']
        path = os.path.join(corpus, 'cases', image['case_id'], 'input', 'materials', image['file'])
        data, note = _image_data(path)
        picture = (
            f'<img src="data:image/jpeg;base64,{data}" '
            f'alt="{html.escape(image["file"])}" loading="lazy">'
            if data
            else '<div class="broken">文件打不开</div>'
        )
        kind = '被标出' if row['reasons'] else '随机抽查'
        why = (
            '<li>随机抽查。AI 觉得这张没问题，请你确认一下：'
            '图和描述对得上，没有车牌、人脸、logo、能读的字。</li>'
            if not row['reasons']
            else ''.join(
                f'<li>{_reason_zh(r, entry, row["blind"], row["led"], zh, row["damage"])}</li>'
                for r in dict.fromkeys(row['reasons'])
            )
        )
        facts_html = ''.join(f'<li>{both(v)}</li>' for _, v in row['facts'])
        ai_said = both((row['blind'] or {}).get('description', ''))
        label = f'#{number} {image["case_id"]} {image["file"]}'
        cards.append(f'''
<section class="card" id="n{number}" data-n="{number}" data-label="{html.escape(label)}">
 <div class="head"><span class="num">#{number}</span>\
<span class="tag {'flag' if row['reasons'] else 'sample'}">{kind}</span>
  <span class="name">{image['case_id']} · {html.escape(image['file'])}</span></div>
 <div class="pic" title="点一下放大或缩小">{picture}</div>
 {f'<p class="note">{note}</p>' if note else ''}
 <h3>这张图应该拍的是</h3><p>{both(entry.get('purpose', ''))}</p>
 <h3>客户是这么说的</h3><ul>{facts_html}</ul>
 <h3>为什么要你看</h3><ul class="why">{why}</ul>
 {
            f'<details><summary>AI 只看图时是怎么描述的</summary><p>{ai_said}</p></details>'
            if ai_said
            else ''
        }
 <div class="choose">
  <button type="button" class="ok">✓ 通过</button>
  <button type="button" class="no">✗ 不通过</button>
  <input type="text" class="reason" placeholder="不通过的原因（例如：车牌能读出来）" hidden>
 </div>
</section>''')

    draw = sampling.get('draw_sha256', 'v1')[:12]
    page = (
        PAGE.replace('{{CARDS}}', ''.join(cards))
        .replace('{{TOTAL}}', str(len(rows)))
        .replace('{{FLAGGED}}', str(sum(1 for r in rows if r['reasons'])))
        .replace('{{STORE}}', f'sheet-zh-{draw}')
    )
    with open(out_path, 'w', encoding='utf-8') as handle:
        handle.write(page)
    print(f'sheet: {len(rows)} images -> {out_path}')


PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>看图签字</title>
<style>
:root { --bg:#f6f5f2; --card:#fff; --fg:#1d1d1b; --muted:#6b6a66; --line:#dddbd5; --ok:#1f7a45; \
--no:#b3261e; --flag:#a15c00; --sample:#3557a8; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#151514; \
--card:#1f1f1d; --fg:#ecebe7; --muted:#a3a19b; --line:#34332f; --ok:#5cc28a; --no:#f08b84; \
--flag:#e0a24d; --sample:#8fa8ec; } }
* { box-sizing:border-box; }
body { background:var(--bg); color:var(--fg); font:16px/1.6 system-ui, "Microsoft YaHei", \
sans-serif; margin:0; }
.bar { position:sticky; top:0; z-index:5; background:var(--card); border-bottom:1px solid \
var(--line); padding:10px 16px; display:flex; gap:12px; align-items:center; flex-wrap:wrap; }
.bar b { font-size:18px; }
.bar button { font:inherit; padding:6px 14px; border-radius:8px; border:1px solid var(--line); \
background:var(--bg); color:var(--fg); cursor:pointer; }
.bar label { color:var(--muted); font-size:14px; }
main { max-width:860px; margin:0 auto; padding:16px; }
.intro { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px \
20px; margin-bottom:20px; }
.intro ol { margin:8px 0 0; padding-left:22px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px \
20px; margin-bottom:20px; border-left:6px solid var(--line); }
.card.ok { border-left-color:var(--ok); } .card.no { border-left-color:var(--no); }
.head { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
.num { font-size:22px; font-weight:700; }
.tag { font-size:13px; padding:2px 8px; border-radius:999px; color:#fff; }
.tag.flag { background:var(--flag); } .tag.sample { background:var(--sample); }
.name { color:var(--muted); font-size:13px; word-break:break-all; }
.pic img { width:100%; height:auto; border-radius:8px; border:1px solid var(--line); \
cursor:zoom-in; display:block; }
.pic.big { position:fixed; inset:0; z-index:10; background:rgba(0,0,0,.92); display:flex; \
align-items:center; justify-content:center; padding:8px; }
.pic.big img { width:auto; max-width:100%; max-height:100%; cursor:zoom-out; border:0; }
.broken { padding:40px; text-align:center; border:2px dashed var(--line); border-radius:8px; \
color:var(--muted); }
.note { color:var(--muted); font-size:14px; }
h3 { font-size:15px; margin:14px 0 4px; color:var(--muted); }
p, li { margin:4px 0; } ul { padding-left:20px; margin:4px 0; }
.en { color:var(--muted); font-size:13px; }
details { margin-top:8px; } summary { cursor:pointer; color:var(--muted); font-size:14px; }
.choose { display:flex; gap:10px; flex-wrap:wrap; margin-top:16px; }
.choose button { font:inherit; font-size:17px; padding:10px 22px; border-radius:10px; border:2px \
solid var(--line); background:var(--bg); color:var(--fg); cursor:pointer; }
.card.ok .ok { background:var(--ok); border-color:var(--ok); color:#fff; }
.card.no .no { background:var(--no); border-color:var(--no); color:#fff; }
.reason { flex:1 1 260px; font:inherit; padding:10px; border-radius:10px; border:2px solid \
var(--no); background:var(--card); color:var(--fg); }
body.hide-done .card.ok, body.hide-done .card.no { display:none; }
#out { width:100%; min-height:140px; font:14px/1.5 ui-monospace, monospace; margin-top:8px; \
background:var(--card); color:var(--fg); border:1px solid var(--line); border-radius:8px; \
padding:8px; }
.result { background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px \
20px; }
</style></head><body>
<div class="bar"><b>已看 <span id="done">0</span> / {{TOTAL}}</b>
 <button type="button" id="copy">复制结果</button>
 <label><input type="checkbox" id="hide"> 只显示还没看的</label>
 <span id="copied" class="en"></span></div>
<main>
<div class="intro">
 <p><b>一共 {{TOTAL}} 张。</b>前 {{FLAGGED}} 张是 AI \
觉得有问题的，后面的是随机抽查的。每张图都看这 4 点：</p>
 <ol>
  <li>图里拍的东西和"应该拍的是"对得上（同一个东西，颜色、位置、坏的程度大体一致）</li>
  <li>没有能读出来的车牌，没有看起来像外国的车牌，没有真实的品牌 logo</li>
  <li>没有人脸，没有真实的路牌，没有能读出来的字</li>
  <li>看起来像普通人用手机拍的照片</li>
 </ol>
 <p>都没问题就点 <b>✓ 通过</b>；有问题就点 <b>✗ 不通过</b>，写一句原因。点图片可以放大。</p>
 <p>看完点最上面的 \
<b>复制结果</b>，粘贴到聊天里发给我。中途关掉页面也没关系，再打开会记得你点过的。</p>
</div>
{{CARDS}}
<div class="result"><b>结果</b>（点"复制结果"会复制下面这段；复制不了就手动全选复制）<textarea \
id="out" readonly></textarea></div>
</main>
<script>
const STORE = '{{STORE}}';
let state = {};
try { state = JSON.parse(localStorage.getItem(STORE) || '{}') || {}; } catch (e) { state = {}; }
function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) {} }
const cards = [...document.querySelectorAll('.card')];
function render() {
  let done = 0;
  const lines = [];
  for (const card of cards) {
    const n = card.dataset.n, s = state[n] || {};
    card.classList.toggle('ok', s.v === 'ok');
    card.classList.toggle('no', s.v === 'no');
    const reason = card.querySelector('.reason');
    reason.hidden = s.v !== 'no';
    if (document.activeElement !== reason) reason.value = s.r || '';
    if (s.v) done++;
    lines.push(card.dataset.label + ' ' + (s.v === 'ok' ? '通过' : s.v === 'no' ? '不通过：' + \
(s.r || '（没写原因）') : '还没看'));
  }
  document.getElementById('done').textContent = done;
  document.getElementById('out').value = '看图结果 ' + done + '/' + cards.length + '\\n' + \
lines.join('\\n');
}
for (const card of cards) {
  const n = card.dataset.n;
  card.querySelector('.ok').onclick = () => { state[n] = { v: 'ok' }; save(); render(); };
  card.querySelector('.no').onclick = () => { state[n] = { v: 'no', r: (state[n] || {}).r || '' }; \
save(); render(); card.querySelector('.reason').focus(); };
  card.querySelector('.reason').oninput = (e) => { state[n] = { v: 'no', r: e.target.value }; \
save(); render(); };
  const pic = card.querySelector('.pic');
  pic.onclick = () => pic.classList.toggle('big');
}
document.getElementById('hide').onchange = (e) => document.body.classList.toggle('hide-done', \
e.target.checked);
document.getElementById('copy').onclick = async () => {
  render();
  const out = document.getElementById('out'), msg = document.getElementById('copied');
  try { await navigator.clipboard.writeText(out.value); msg.textContent = '已复制'; }
  catch (e) { out.focus(); out.select(); try { document.execCommand('copy'); msg.textContent = \
'已复制'; } catch (e2) { msg.textContent = '请手动复制最下面的结果'; } }
  setTimeout(() => { msg.textContent = ''; }, 3000);
};
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') \
document.querySelectorAll('.pic.big').forEach(p => p.classList.remove('big')); });
render();
</script></body></html>"""


if __name__ == '__main__':
    main()
