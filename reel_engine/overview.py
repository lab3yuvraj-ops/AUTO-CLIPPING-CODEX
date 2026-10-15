"""CPU-only chronological source overview with actual decoded frame timestamps."""
import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from PIL import Image, ImageDraw
from .render import file_hash, probe
from .youtube_transcript import atomic_json


def make_overview(source, root, interval=12):
    if not math.isfinite(interval) or interval < 1:
        raise ValueError('Overview interval must be at least one second.')
    started = time.perf_counter()
    fingerprint = file_hash(Path(source))
    signature = hashlib.sha256(json.dumps([fingerprint, interval, 3]).encode()).hexdigest()
    out = Path(root) / 'overview' / signature[:16]
    out.mkdir(parents=True, exist_ok=True)
    report_path = out / 'overview.json'
    if report_path.exists():
        old = json.loads(report_path.read_text(encoding='utf-8'))
        if all(Path(row['file']).is_file() and file_hash(Path(row['file'])) == row['sha256']
               for row in old['frames'] + old['page_files']):
            return {**old, 'cache_reused': True, 'seconds_this_run': time.perf_counter()-started}
    duration = float(probe(source)['format']['duration'])
    # Decode keyframes sequentially, rather than seeking and decoding a GOP per thumbnail.
    # showinfo supplies actual PTS; requested intervals are never presented as exact times.
    frames = []
    mode = 'keyframes'
    for skip in (True, False):
        args = ['ffmpeg', '-hide_banner', '-y', '-hwaccel', 'none']
        if skip:
            args += ['-skip_frame', 'nokey']
        args += ['-i', str(source), '-an', '-vf',
                 f"select='isnan(prev_selected_t)+gte(t,(floor(prev_selected_t/{interval})+1)*{interval})',scale=640:-2,showinfo",
                 '-fps_mode', 'vfr', str(out / 'frame-%04d.jpg')]
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=600)
        stamps = [float(t) for t in re.findall(r'\bn:\s*\d+.*?\bpts_time:([\d.eE+-]+)', result.stderr)]
        files = sorted(out.glob('frame-*.jpg'))[:len(stamps)]
        if result.returncode:
            raise RuntimeError('Source overview extraction failed; saved source is unchanged.')
        if stamps and stamps[0] <= interval and duration-stamps[-1] <= interval*2 and all(
                b-a <= interval*2 for a,b in zip(stamps, stamps[1:])):
            frames = [{'source_seconds':t, 'file':str(f.resolve()), 'sha256':file_hash(f)} for t,f in zip(stamps,files)]
            break
        mode = 'all_frames'
    if not frames:
        raise RuntimeError('Could not obtain a chronological overview covering this source.')
    pages = []
    for offset in range(0, len(frames), 12):
        sheet = Image.new('RGB', (1280, 6*384), '#171b19')
        draw = ImageDraw.Draw(sheet)
        for i,row in enumerate(frames[offset:offset+12]):
            x,y=(i%2)*640,(i//2)*384
            with Image.open(row['file']) as im:
                im.thumbnail((632,356)); sheet.paste(im,(x+4,y+24))
            draw.text((x+8,y+5),f"Source {row['source_seconds']:.3f}s",fill='white')
        page = out / f'page-{offset//12+1:02d}.jpg'
        sheet.save(page, quality=94)
        pages.append({'file':str(page.resolve()), 'sha256':file_hash(page)})
    report = {'source_sha256':fingerprint,'source_seconds':duration,'interval_seconds':interval,
              'decode_mode':mode,'frames':frames,'pages':[p['file'] for p in pages], 'page_files':pages,
              'seconds_this_run':time.perf_counter()-started,'cache_reused':False,
              'note':'Sampled chronological context, not continuous tracking or human approval. Inspect denser frames around chosen moments and scene changes.'}
    atomic_json(report_path, report)
    return report
