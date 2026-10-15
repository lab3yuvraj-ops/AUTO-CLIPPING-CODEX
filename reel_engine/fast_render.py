"""Optional CPU single-pass renderer for reviewed, anchored fast-mode clips.

The normal renderer remains the fallback. Camera geometry is the same offline
plan as that renderer; FFmpeg receives each integer crop position at 30 fps.
No lossless video/audio intermediate or automatic identity estimate is made.
"""
import hashlib
import json
import math
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .captions import FONTS, make_ass
from .render import file_hash, plan_camera, probe, run
from .review import review_frames
from .timeline import to_output
from .tracking import crop_centers, fill_missing_centers
from .visual_focus import camera_frame, validate_targets


def camera_plan(source, edit, tracking):
    """Reuse exact normal camera math, requiring reviewed identity anchors."""
    if tracking.get('mode') == 'fit':
        raise ValueError('Fast mode requires a full-height source crop.')
    if abs(tracking.get('camera_easing_seconds', 1.2)-1.2)>1e-9:
        raise ValueError('Fast mode requires the approved 1.2-second easing.')
    targets=validate_targets(tracking.get('visual_targets', []),
                             edit['segments'][0]['source_start'], edit['segments'][-1]['source_end'])
    if any(not t.get('box_keyframes') for t in targets):
        raise ValueError('Fast targets need reviewed identity anchors; use normal rendering otherwise.')
    if not edit.get('segments') or any(not 0<=s['source_start']<s['source_end'] for s in edit['segments']):
        raise ValueError('Fast segments require increasing nonnegative local source bounds.')
    if abs(sum(s['source_end']-s['source_start'] for s in edit['segments'])-edit['duration'])>.001:
        raise ValueError('Edit duration must match kept source segments.')
    count=math.floor(edit['duration']*30)
    if count<1:raise ValueError('Empty clip.')
    # Frame intervals are half-open. Exactly at a removed-gap boundary the
    # first frame belongs to the next segment, not the previous source end.
    def frame_source(t):
        for s in edit['segments']:
            if s['output_start']<=t<s['output_end']:
                return s['source_start']+t-s['output_start']
        raise ValueError('Edit segments do not cover the output frame timeline.')
    times=[frame_source(i/30) for i in range(count)]
    words=[{**w,'start':w.get('source_start',w['start']), 'end':w.get('source_end',w['end'])} for w in edit['words']]
    raw=crop_centers(tracking,words,times)
    centers=fill_missing_centers(raw,tracking,times)
    cap=cv2.VideoCapture(str(source))
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    try:path, tracker, anchored=plan_camera(cap,tracking,centers,times,30)
    finally:cap.release()
    crop_width=round(height*9/16)
    if width<crop_width or any(abs(g[1]-.5)>1e-9 or abs(g[2]-1)>1e-9 for g in path):
        raise ValueError('Fast mode cannot preserve the approved full-height crop.')
    xs=[int(np.clip(g[0]*width-crop_width/2,0,width-crop_width)) for g in path]
    return {'geometry':path,'times':times,'xs':xs,'width':width,'height':height,
            'crop_width':crop_width,'count':count,'uncertain':sum(v is None for v in raw),
            'anchored':anchored,'target_frames':tracker.anchored_frames}


def fast_render_clip(source,edit,tracking,path,config,threads=None):
    started=time.perf_counter();path=Path(path).resolve();root=path.parent;root.mkdir(parents=True,exist_ok=True)
    if config.get('encoder','libx264')!='libx264':raise ValueError('Fast mode is CPU libx264 only.')
    if config.get('font','Creepster')!='Creepster' or config.get('caption_y',1420)!=1420 or edit.get('caption_positions'):
        raise ValueError('Fast mode keeps the approved locked Creepster caption position.')
    camera=camera_plan(source,edit,tracking)
    events=make_ass(edit['words'],root/'captions.ass','Creepster',1420)
    (root/'caption-events.json').write_text(json.dumps(events),encoding='utf-8')
    (root/'camera-path.json').write_text(json.dumps({'version':1,'fps':30,'times':camera['times'],'geometry':camera['geometry']}),encoding='utf-8')
    # A named crop receives exact per-frame integer positions. No long nested
    # expression, approximate sparse interpolation or fixed-filter-width zoom.
    (root/'crop-commands.txt').write_text('\n'.join(f'{i/30:.9f} crop@portrait x {x};' for i,x in enumerate(camera['xs'])),encoding='utf-8')
    parts=[];labels=[]
    for i,s in enumerate(edit['segments']):
        a=s['source_start'];b=s['source_end'];d=b-a
        parts.append(f'[0:v]trim=start={a}:end={b},setpts=PTS-STARTPTS[v{i}]')
        parts.append(f'[0:a]atrim=start={a}:end={b},asetpts=PTS-STARTPTS,afade=t=in:d=0.005,afade=t=out:st={max(0,d-.005)}:d=0.005[a{i}]')
        labels.append(f'[v{i}][a{i}]')
    if len(labels)==1:video='[v0]';audio='[a0]'
    else:
        parts.append(''.join(labels)+f'concat=n={len(labels)}:v=1:a=1[joinedv][joineda]');video='[joinedv]';audio='[joineda]'
    fonts=(Path(__file__).resolve().parents[1]/'assets').as_posix().replace(':','\\:')
    parts.append(video+f"fps=30:start_time=0,sendcmd=f=crop-commands.txt,crop@portrait=w={camera['crop_width']}:h={camera['height']}:x={camera['xs'][0]}:y=0:exact=1,scale=1080:1920:flags=lanczos:param0=4,setsar=1,ass=captions.ass:fontsdir='{fonts}'[outv]")
    (root/'fast-filter.txt').write_text(';'.join(parts),encoding='utf-8')
    planning=time.perf_counter()-started
    temp=root/'fast-render.tmp.mp4'
    thread_options=[] if threads is None else ['-threads',str(max(1,int(threads)))]
    run(['ffmpeg','-v','error','-y','-hwaccel','none',*thread_options,'-i',str(Path(source).resolve()),
         '-filter_complex_threads',str(max(1,int(threads or 2))),'-filter_complex_script','fast-filter.txt',
         '-map','[outv]','-map',audio,'-c:v','libx264','-preset','fast','-crf','18',*thread_options,
         '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-ar','48000','-ac','2',
         '-t',str(camera['count']/30),'-movflags','+faststart',str(temp)],cwd=root)
    temp.replace(path)
    return {'caption_events':events,'render_frames':camera['count'],'fps':30,'encoder':'libx264',
            'timings':{'camera_planning_seconds':planning,'compose_encode_seconds':time.perf_counter()-started-planning,'total_render_seconds':time.perf_counter()-started},
            'lossless_edit_reused':False,'anchor_only_planning':True,'full_source_height':True,
            'fallback_frames':0,'uncertain_framing_frames':camera['uncertain'],'composition':'fill',
            'visual_target_frames':camera['target_frames'],'focus_motion_failed_frames':0,
            'focus_motion_tracked_frames':0,'focus_identity_anchored_frames':camera['target_frames'],
            'focus_reacquired_frames':0,'camera_easing_seconds':1.2,'single_pass':True,
            'scaler':'FFmpeg Lanczos with four lobes; normal path uses OpenCV Lanczos4 (not pixel identical)'}


def fast_review(source,edit,tracking,root):
    """One compact combined sheet per clip, no edited-media intermediate."""
    started=time.perf_counter();root=Path(root);out=root/'fast-review';out.mkdir(parents=True,exist_ok=True)
    signature=hashlib.sha256(json.dumps({'source':file_hash(source),'edit':edit,'tracking':tracking,
        'code':file_hash(__file__),'normal_camera':file_hash(Path(__file__).with_name('camera.py')),
        'normal_render':file_hash(Path(__file__).with_name('render.py')),
        'focus':file_hash(Path(__file__).with_name('visual_focus.py')),
        'tracking_code':file_hash(Path(__file__).with_name('tracking.py')),
        'timeline':file_hash(Path(__file__).with_name('timeline.py')),
        'review_frames':file_hash(Path(__file__).with_name('review.py')),
        'captions':file_hash(Path(__file__).with_name('captions.py')),
        'font':file_hash(Path(__file__).resolve().parents[1]/'assets'/FONTS['Creepster'])},sort_keys=True).encode()).hexdigest()
    report_path=out/'review.json';old=json.loads(report_path.read_text()) if report_path.exists() else {}
    if old.get('signature')==signature and old.get('page_hashes') and all(Path(p).is_file() and file_hash(p)==h for p,h in old['page_hashes'].items()):
        return {**old,'cache_reused':True,'changed_pages':[],'seconds':time.perf_counter()-started}
    camera=camera_plan(source,edit,tracking)
    points={.1,edit['duration']-.1,*np.arange(0,edit['duration'],3.5).tolist()}
    for source_cut in tracking.get('camera_cuts',[]):
        for t in (source_cut-.05,source_cut+.05):
            mapped=to_output(t,edit['segments'])
            if mapped is not None:points.add(mapped)
    for target in tracking.get('visual_targets',[]):
        for anchor in target.get('box_keyframes',[]):
            for stamp in (anchor['t']-.1,anchor['t'],anchor['t']+.1):
                mapped=to_output(stamp,edit['segments'])
                if mapped is not None:points.add(mapped)
    indices=sorted({min(camera['count']-1,max(0,round(t*30))) for t in points if 0<=t<edit['duration']})
    source_meta=probe(source);v=next(s for s in source_meta['streams'] if s['codec_type']=='video')
    numerator,denominator=v['avg_frame_rate'].split('/');fps=float(numerator)/float(denominator)
    srcindices=[round(camera['times'][n]*fps) for n in indices]
    unique=sorted(set(srcindices));files=review_frames(source,unique,out);lookup=dict(zip(unique,files))
    cols=3;cellw=640;cellh=408;sheet=Image.new('RGB',(cols*cellw,math.ceil(len(indices)/cols)*cellh),(22,26,24));draw=ImageDraw.Draw(sheet)
    font=ImageFont.truetype(str(Path(__file__).resolve().parents[1]/'assets'/FONTS['Creepster']),13)
    events=make_ass(edit['words'],out/'captions.ass','Creepster',1420);samples=[]
    for i,n in enumerate(indices):
        t=n/30;source_t=camera['times'][n];frame=cv2.imread(str(lookup[srcindices[i]]));geo=camera['geometry'][n]
        crop=camera_frame(frame,geo);x=i%cols*cellw;y=i//cols*cellh
        full=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB));full.thumbnail((380,230))
        sheet.paste(full,(x+6,y+30));portrait=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)).resize((202,360));sheet.paste(portrait,(x+420,y+30))
        original_t=source_t+float(tracking.get('source_time_offset',0))
        draw.text((x+6,y+7),f'Output {t:.2f}s | source {original_t:.2f}s',fill='white')
        cw=frame.shape[0]/frame.shape[1]*9/16
        draw.rectangle((x+6+(geo[0]-cw/2)*full.width,y+30,x+6+(geo[0]+cw/2)*full.width,y+30+full.height-1),outline='yellow',width=2)
        event=next((e for e in events if e['start']<=t<e['end']),None)
        if event:
            active={w['roman'].upper() for w in edit['words'] if w['id'] in event['active_ids']};labels=event['display_text'].split()
            widths=[draw.textlength(s+' ',font=font) for s in labels];px=x+420+500/1080*202-sum(widths)/2;py=y+30+1420/1920*360-7
            for label,width in zip(labels,widths):
                draw.text((px,py),label,font=font,fill=(255,51,51) if label in active else 'white',stroke_width=1,stroke_fill='black');px+=width
        samples.append({'output':t,'source':original_t,'section_source':source_t,'camera':geo})
    dest=out/'combined.jpg';sheet.save(dest,quality=94);p=str(dest.resolve());h=file_hash(dest)
    report={'signature':signature,'pages':[p],'page_hashes':{p:h},'changed_pages':[p] if old.get('page_hashes',{}).get(p)!=h else [],
            'sample_count':len(samples),'samples':samples,'seconds':time.perf_counter()-started,'cache_reused':False,
            'note':'Sampled source/crop review, caption approximation; not final playback or publication approval.'}
    report_path.write_text(json.dumps(report,indent=2),encoding='utf-8');return report
