"""Build an explicitly synthetic offline page for the shared browser acceptance test."""
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import publication_desk as desk


def build(output):
    output.mkdir(parents=True, exist_ok=True)
    data = desk.new_project('synthetic-publication-panels', 'Synthetic publication panel fixture')
    item = data['items'][0]
    video = output / 'synthetic-not-playable.mp4'
    video.write_bytes(b'SYNTHETIC ONLY: tests file references, not media decoding or publication.')
    item['video'] = dict(path=str(video.resolve()), sha256=hashlib.sha256(video.read_bytes()).hexdigest())
    candidates = []
    for number, cid in enumerate(('A', 'B', 'F')):
        mapping = {}
        for ratio, size in {'3:4': (240, 320), '4:3': (320, 240), '16:9': (320, 180)}.items():
            aid = cid + '_' + ratio.replace(':', 'x')
            path = output / (aid + '.png')
            Image.new('RGB', size, (40 + number * 60, 80, 120)).save(path)
            item['covers'].append(dict(id=aid, label='Synthetic ' + cid + ' ' + ratio, path=str(path.resolve()),
                                      sha256=hashlib.sha256(path.read_bytes()).hexdigest(), width=size[0], height=size[1]))
            mapping[ratio] = aid
        candidates.append(dict(id=cid, name='Synthetic ' + cid, title='Synthetic title',
                               hypothesis='Synthetic comparison only', cover_by_ratio=mapping))
    item['cover_pk'].update(candidates=candidates, required_ratios=['3:4', '4:3', '16:9'])
    item['cover_pk']['platform_ratios']['kuaishou'] = ['3:4']
    desk.apply_cover_test_selection(item, ['A', 'B', 'F'])
    item['platforms']['xiaohongshu']['cover_test'].update(main_cover_id='', confirmed_candidate_limit=3)
    for key, p in item['platforms'].items():
        p['fields'].update(body='Synthetic body. No real project, person, account or publishing action.', tags='#synthetic')
        if 'title' in p['fields']:
            p['fields']['title'] = 'Synthetic title'
        if key == 'weixin_channels':
            p['fields']['short_title'] = 'Synthetic'
    data['editorial_context'] = dict(source='Synthetic test fixture', forbidden_public_phrases=[])
    data['ui_state'] = dict(platform_panels={item['id'] + '::' + k: k == 'xiaohongshu' for k in item['platforms']})
    Image.new('RGB', (240, 320), (55, 90, 130)).save(output / 'primary-fixture.png')
    desk.write_new(output / 'fixture.json', data)
    desk.write_new(output / 'fixture.html', desk.render(data))
    return output / 'fixture.html'


if __name__ == '__main__':
    print(json.dumps(dict(page=str(build(Path(sys.argv[1]).resolve())), synthetic=True)))
