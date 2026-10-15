"""Dense selected-passage frames and scene-change candidates in one CPU pass."""
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


def make_details(source, root, ranges, interval=.5):
    duration=float(probe(source)['format']['duration'])
    if not ranges or not math.isfinite(interval) or interval<.1 or any(
            not math.isfinite(a+b) or not 0<=a<b<=duration or b-a>180 for a,b in ranges):
        raise ValueError('Detail ranges must be within source, at most 180 seconds each.')
    fingerprint=file_hash(Path(source));started=time.perf_counter();reports=[]
    for a,b in ranges:
        signature=hashlib.sha256(json.dumps([fingerprint,float(a),float(b),interval,2]).encode()).hexdigest()
        out=Path(root)/'details'/signature[:16];out.mkdir(parents=True,exist_ok=True)
        path=out/'detail.json'
        if path.exists():
            report=json.loads(path.read_text(encoding='utf-8'))
            if all(Path(f['file']).exists() and file_hash(Path(f['file']))==f['sha256']
                   for f in report['frames']+report['page_files']):
                reports.append({**report,'cache_reused':True});continue
        # Accurate input seek rebases frame PTS to the requested passage start.
        args=['ffmpeg','-hide_banner','-y','-hwaccel','none','-ss',str(a),'-i',str(source),'-t',str(b-a),
              '-an','-filter_threads','1','-vf',
              f"scale=640:-2,select='isnan(prev_selected_t)+gte(t-prev_selected_t,{interval})+gt(scene,0.18)',metadata=print:key=lavfi.scene_score,showinfo",
              '-fps_mode','vfr',str(out/'frame-%04d.jpg')]
        result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600)
        if result.returncode:raise RuntimeError('Selected source-frame extraction failed.')
        stamps=[float(t) for t in re.findall(r'\bn:\s*\d+.*?\bpts_time:([\d.eE+-]+)',result.stderr)]
        scores=[float(s) for s in re.findall(r'lavfi.scene_score=([\d.eE+-]+)',result.stderr)]
        if not stamps:raise RuntimeError('No frames in selected source range.')
        frames=[]
        for i,t in enumerate(stamps):
            f=out/f'frame-{i+1:04d}.jpg'
            # showinfo can observe a final frame discarded by the output -t limit.
            if a+t>=b or not f.exists():continue
            frames.append({'source_seconds':a+t,'file':str(f.resolve()),'sha256':file_hash(f),
                           'scene_score':scores[i] if i<len(scores) else None})
        if not frames or frames[0]['source_seconds']-a>interval*2 or b-frames[-1]['source_seconds']>interval*2:
            raise RuntimeError('Selected frame coverage is incomplete.')
        pages=[]
        for offset in range(0,len(frames),12):
            sheet=Image.new('RGB',(1280,2304),'#171b19');draw=ImageDraw.Draw(sheet)
            for i,f in enumerate(frames[offset:offset+12]):
                x,y=(i%2)*640,(i//2)*384
                with Image.open(f['file']) as im:
                    im.thumbnail((632,356));sheet.paste(im,(x+4,y+24))
                    # Review-only horizontal coordinates avoid guessing box centers.
                    for tick in range(1,10):
                        gx=x+4+im.width*tick/10
                        draw.line((gx,y+24,gx,y+24+im.height),fill='#88752d')
                        draw.text((gx+2,y+27),f'.{tick}',fill='#fff2a2')
                mark=' | possible scene cut' if (f['scene_score'] or 0)>.18 else ''
                draw.text((x+8,y+5),f"Source {f['source_seconds']:.3f}s{mark}",fill='white')
            f=out/f'page-{offset//12+1:02d}.jpg';sheet.save(f,quality=94)
            pages.append({'file':str(f.resolve()),'sha256':file_hash(f)})
        report={'source_sha256':fingerprint,'range':[a,b],'interval_seconds':interval,'frames':frames,
                'pages':[p['file'] for p in pages],'page_files':pages,'cache_reused':False,
                'candidate_scene_cuts':[f['source_seconds'] for f in frames if (f['scene_score'] or 0)>.18],
                'note':'Actual sequential source frames; scene scores are candidates requiring visual confirmation, not automatic identity or tracking approval.'}
        atomic_json(path,report);reports.append(report)
    return {'passages':reports,'seconds_this_run':time.perf_counter()-started}
