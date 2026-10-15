"""Inspect source context, exact camera geometry and caption wording before encoding."""
import json
import math
import textwrap
import time
import hashlib
import copy
from pathlib import Path
import cv2
from PIL import Image, ImageDraw, ImageFont
from .render import edit_source,plan_camera,camera_frame,file_hash,run
from .tracking import crop_centers,fill_missing_centers
from .timeline import to_source,to_output
from .captions import make_ass,FONTS


def canonical_review(edit,tracking):
    """Stable source-bound review timeline, independent of small edge trims."""
    result=copy.deepcopy(edit);recipe=copy.deepcopy(tracking);targets=recipe.get('visual_targets',[])
    if targets:
        result['segments'][0]['source_start']=min(result['segments'][0]['source_start'],targets[0].get('scene_start',targets[0]['start']))
        result['segments'][-1]['source_end']=max(result['segments'][-1]['source_end'],targets[-1].get('scene_end',targets[-1]['end']))
        for target in targets:
            target['start']=target.get('scene_start',target['start']);target['end']=target.get('scene_end',target['end'])
    cursor=0.
    for segment in result['segments']:
        segment['output_start']=cursor;cursor+=segment['source_end']-segment['source_start'];segment['output_end']=cursor
    result['duration']=cursor
    for word in result['words']:
        word['start']=to_output(word['source_start'],result['segments']);word['end']=to_output(word['source_end'],result['segments'])
    return result,recipe


def review_scenes(edit,tracking):
    targets=tracking.get('visual_targets') or tracking.get('context_scenes') or tracking.get('speaker_plan',{}).get('scenes')
    if targets:return targets
    # Stable contextual footage still needs chronological coverage in full policy.
    result=[]
    for segment in edit['segments']:
        a,b=segment['source_start'],segment['source_end']
        cuts=sorted({a,b,*[t for t in tracking.get('camera_cuts',[]) if a<t<b]})
        result.extend({'start':x,'end':y} for x,y in zip(cuts,cuts[1:]))
    return result


def scene_review_groups(edit,tracking,fps=30):
    """Keep page slots within scene pairs, not a shifting global point list."""
    targets=review_scenes(edit,tracking);groups={}
    def add(stamp,scene):
        mapped=to_output(stamp,edit['segments'])
        if mapped is not None:groups.setdefault(scene//2,set()).add(round(mapped*fps)/fps)
    for scene,target in enumerate(targets):
        a=target.get('scene_start',target['start']);b=target.get('scene_end',target['end'])
        for stamp in (a+.2,(a+b)/2,b-.2):add(stamp,scene)
        anchors=target.get('camera_center_keyframes') or target.get('box_keyframes',[])
        for before,anchor in zip(anchors,anchors[1:]):
            def center(p):return p['center'] if 'center' in p else p['box'][0]+p['box'][2]/2
            if abs(center(before)-center(anchor))>=.08:add(min(b-.05,anchor['t']+.1),scene)
    add(edit['segments'][0]['source_start']+.3,0)
    add(edit['segments'][-1]['source_end']-.3,max(0,len(targets)-1))
    for stamp in tracking.get('flagged_output_seconds',[]):
        source=to_source(stamp,edit['segments'])
        scene=next((i for i,t in enumerate(targets) if t['start']<=source<t['end']),0)
        add(source,scene)
    return [(group,sorted(points)) for group,points in sorted(groups.items())]


def compact_review_groups(edit,tracking,fps=30):
    """One baseline sheet, then stable scene-keyed exception pages only."""
    from .config import settings
    if not settings.compact_pre_review and not tracking.get('review_coverage'):return scene_review_groups(edit,tracking,fps)
    a=edit['segments'][0]['source_start'];b=edit['segments'][-1]['source_end']
    targets=review_scenes(edit,tracking)
    stamps=[a+.1,b-.1]
    interior=[(t['start']+t['end'])/2 for t in targets]
    if interior:
        stamps.extend(interior[round(i*(len(interior)-1)/3)] for i in range(4))
    baseline={round(t*fps)/fps for s in stamps if (t:=to_output(s,edit['segments'])) is not None}
    groups={-1:set(baseline)}
    if tracking.get('review_coverage')=='all-scenes':
        for group,points in scene_review_groups(edit,tracking,fps):groups.setdefault(group,set()).update(points)
    flags=tracking.get('flagged_output_seconds',[])
    for index,target in enumerate(targets):
        points=[t for t in flags if target['start']<=to_source(t,edit['segments'])<target['end']]
        if points:
            stamps=[target['start']+.05,(target['start']+target['end'])/2,target['end']-.05]
            points.extend(t for s in stamps if (t:=to_output(s,edit['segments'])) is not None)
            # Stable scene-pair slots fit two four-frame exceptions per sheet.
            groups.setdefault(index//2,set()).update(round(t*fps)/fps for t in points)
    return [(key,sorted(points)) for key,points in sorted(groups.items())]


def review_frames(edited,indices,out):
    """Extract exact ordered frames once instead of repeated decoder seeks.

    960px source thumbnails exceed both review display resolutions (420px
    source and 216px portrait). Final rendering still uses original pixels.
    """
    from .youtube_transcript import atomic_json
    folder=out/'frames';folder.mkdir(exist_ok=True)
    signature=hashlib.sha256(json.dumps([file_hash(edited),indices,960,3]).encode()).hexdigest()
    cache=folder/'frames.json'
    old=json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    if old.get('signature')==signature and all(Path(p).is_file() and file_hash(p)==sha for p,sha in old.get('hashes',{}).items()) and len(old.get('hashes',{}))==len(indices):
        return [Path(p) for p in old['hashes']]
    # FFmpeg's evaluator has a recursion limit; balance large sample lists.
    terms=[f'eq(n,{n})' for n in indices]
    while len(terms)>1:
        terms=[f'({terms[i]}+{terms[i+1]})' if i+1<len(terms) else terms[i] for i in range(0,len(terms),2)]
    expression=terms[0]
    for stale in folder.glob('frame-*.jpg'):
        stale.unlink()
    # Story/CTA concat can change SAR metadata without changing pixels. Default
    # filter reinitialization resets select's n, corrupting ordered sampling.
    run(['ffmpeg','-v','error','-y','-hwaccel','none','-reinit_filter','0','-i',str(edited),'-an',
         '-vf',f"select='{expression}',setpts=N/TB,scale=960:-2",'-fps_mode','vfr','-q:v','2',
         str(folder/'frame-%04d.jpg')],timeout=600)
    files=[folder/f'frame-{i+1:04d}.jpg' for i in range(len(indices))]
    if any(not p.is_file() for p in files):raise RuntimeError('Missing sequential review frame.')
    atomic_json(cache,{'signature':signature,'hashes':{str(p.resolve()):file_hash(p) for p in files}})
    return files


def proxy_review_input(source,edit,tracking,root):
    """Map final-media source times to accepted proxy times for review only."""
    record=Path(root)/'job.json'
    if not record.is_file():return source,edit,tracking,False
    job=json.loads(record.read_text(encoding='utf-8'));offset=job.get('source_time_offset')
    parent=Path(root).parent/job.get('source_job_id','')/'job.json'
    if offset is None or not parent.is_file():return source,edit,tracking,False
    proxy=json.loads(parent.read_text(encoding='utf-8')).get('proxy',{})
    path=Path(proxy.get('source',''))
    if not path.is_file():return source,edit,tracking,False
    if file_hash(path)!=proxy.get('source_sha256'):raise ValueError('Review proxy hash changed.')
    result=copy.deepcopy(edit);recipe=copy.deepcopy(tracking)
    for segment in result['segments']:
        for key in ('source_start','source_end'):segment[key]+=offset
    for word in result['words']:
        for key in ('source_start','source_end'):word[key]+=offset
    for target in recipe.get('visual_targets',[]):
        for key in ('start','end','scene_start','scene_end'):
            if key in target:target[key]+=offset
        for key in ('box_keyframes','safety_box_keyframes','action_box_keyframes','camera_center_keyframes'):
            for point in target.get(key,[]):point['t']+=offset
    for key in ('crop_keyframes','samples'):
        for point in recipe.get(key,[]):point['t']+=offset
    recipe['camera_cuts']=[t+offset for t in recipe.get('camera_cuts',[])]
    return path,result,recipe,True


def make_review(source,edit,tracking,root):
    started=time.perf_counter();root=Path(root);out=root/'review';out.mkdir(exist_ok=True)
    final_source_hash=file_hash(source)
    source,edit,tracking,uses_proxy=proxy_review_input(source,edit,tracking,root)
    edited_path=out/'proxy-edited.mkv' if uses_proxy else root/'edited.mkv'
    implementation=hashlib.sha256()
    for module in ('review','render','captions','camera','tracking','visual_focus','timeline'):
        implementation.update(Path(__file__).with_name(module+'.py').read_bytes())
    signature=hashlib.sha256(json.dumps({'source':file_hash(source),'final_source':final_source_hash,'edit':edit,'tracking':tracking,
        'implementation':implementation.hexdigest(),'compact_pre_review':__import__('reel_engine.config',fromlist=['settings']).settings.compact_pre_review,
        'font':file_hash(Path(__file__).resolve().parents[1]/'assets'/FONTS['Creepster'])},sort_keys=True).encode()).hexdigest()
    report_path=out/'review.json'
    previous=json.loads(report_path.read_text(encoding='utf-8')) if report_path.exists() else {}
    old_hashes=previous.get('page_hashes',{})
    if previous.get('signature')==signature and old_hashes and all(
            Path(p).is_file() and file_hash(p)==sha for p,sha in old_hashes.items()):
        from .review_policy import inspection_plan
        return {k:v for k,v in previous.items() if k!='samples'} | inspection_plan(root,'pre',previous['pages'],previous.get('flagged_pages',[])) | {
            'sample_count':len(previous['samples']),'cache_reused':True,'changed_pages':[],
            'seconds':time.perf_counter()-started}
    actual_segments=copy.deepcopy(edit['segments'])
    edit,tracking=canonical_review(edit,tracking)
    tracking['flagged_output_seconds']=[mapped for t in tracking.get('flagged_output_seconds',[]) if (mapped:=to_output(to_source(t,actual_segments),edit['segments'])) is not None]
    reused=edit_source(source,edit,edited_path)
    cap=cv2.VideoCapture(str(edited_path));fps=30
    count=math.floor(edit['duration']*fps)
    times=[to_source(i/fps,edit['segments']) for i in range(count)]
    words=[{**w,'start':w['source_start'],'end':w['source_end']} for w in edit['words']]
    centers=fill_missing_centers(crop_centers(tracking,words,times),tracking,times)
    camera,_,anchored=plan_camera(cap,tracking,centers,times,fps)
    events=make_ass(edit['words'],out/'captions.ass','Creepster',1420)
    groups=compact_review_groups(edit,tracking,fps)
    grouped={group:set(points) for group,points in groups}
    # Actual edges need inspection, but only their scene pair/page may change.
    edge_groups=(-1,-1) if -1 in grouped else (0,max(grouped,default=0))
    for stamp,group in zip((actual_segments[0]['source_start']+.1,actual_segments[-1]['source_end']-.1),edge_groups):
        mapped=to_output(stamp,edit['segments'])
        if mapped is not None:grouped.setdefault(group,set()).add(round(mapped*fps)/fps)
    batches=[]
    for group,stamps in sorted(grouped.items()):
        stamps=sorted(t for t in stamps if 0<=t<count/fps and to_output(to_source(t,edit['segments']),actual_segments) is not None)
        batches.extend((group,i//8,stamps[i:i+8]) for i in range(0,len(stamps),8))
    points=sorted({t for _,_,stamps in batches for t in stamps})
    lookup={t:i for i,t in enumerate(points)}
    indices=[min(count-1,round(t*fps)) for t in points]
    frame_files=review_frames(edited_path,indices,out)
    font=ImageFont.truetype(str(Path(__file__).resolve().parents[1]/'assets'/FONTS['Creepster']),14)
    pages=[];samples=[]
    page_for_point={}
    for group,part,page_points in batches:
        sheet=Image.new('RGB',(1440,4*424),(22,26,24));draw=ImageDraw.Draw(sheet)
        for tile,t in enumerate(page_points):
            index=lookup[t];n=indices[index]
            frame=cv2.imread(str(frame_files[index]))
            if frame is None:raise RuntimeError('Missing review frame.')
            geo=camera[n];crop=camera_frame(frame,geo)
            x=(tile%2)*720;y=(tile//2)*424
            draw.text((x+8,y+6),f'Source {times[n]:.2f}s',fill='white')
            full=Image.fromarray(cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)).resize((420,236))
            portrait=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB)).resize((216,384))
            sheet.paste(full,(x+8,y+32));sheet.paste(portrait,(x+448,y+32))
            cx,cy,ch=geo;cw=ch*frame.shape[0]/frame.shape[1]*9/16
            draw.rectangle((x+8+(cx-cw/2)*420,y+32+(cy-ch/2)*236,
                x+8+(cx+cw/2)*420,y+32+(cy+ch/2)*236),outline='yellow',width=2)
            event=next((e for e in events if e['start']<=t<e['end']),None)
            if event:
                labels=event['display_text'].split();active={w['roman'].upper() for w in edit['words'] if w['id'] in event['active_ids']}
                widths=[draw.textlength(label+' ',font=font) for label in labels]
                px=x+448+500/1080*216-sum(widths)/2;py=y+32+1420/1920*384-7
                for label,width in zip(labels,widths):
                    draw.text((px+1,py+1),label,font=font,fill='black',stroke_width=2,stroke_fill='black')
                    draw.text((px,py),label,font=font,fill=(255,51,51) if label in active else 'white',stroke_width=1,stroke_fill='black');px+=width
            nearby=' '.join(w['roman'] for w in edit['words'] if t-1<=w['end'] and w['start']<=t+2)
            for line_i,line in enumerate(textwrap.wrap(nearby,62)[:5]):draw.text((x+8,y+284+line_i*18),line,fill='white')
            samples.append({'output':t,'source':times[n],'camera':geo,'roman_context':nearby})
        name=f'page-baseline-{part+1:02}.jpg' if group==-1 else f'page-scene-pair-{group+1:02}-{part+1:02}.jpg'
        destination=out/name;sheet.save(destination,quality=94);pages.append(str(destination.resolve()))
        page_for_point.update({t:str(destination.resolve()) for t in page_points})
    cap.release()
    hashes={p:file_hash(p) for p in pages}
    from .review_policy import inspection_plan
    flagged=[]
    for stamp in tracking.get('flagged_output_seconds',[]):
        if points:
            index=min(range(len(points)),key=lambda i:abs(points[i]-stamp))
            flagged.append(page_for_point[points[index]])
    inspection=inspection_plan(root,'pre',pages,flagged)
    report={'pages':pages,'page_hashes':hashes,'signature':signature,'cache_reused':False,'review_media':'proxy' if uses_proxy else 'final-source','final_source_sha256':final_source_hash,
            'flagged_pages':sorted(set(flagged)),
            'changed_pages':[p for p in pages if old_hashes.get(p)!=hashes[p]],
            **inspection,'samples':samples,'seconds':time.perf_counter()-started,'lossless_edit_reused':reused,
            'anchor_only_planning':anchored,'note':'Caption thumbnails approximate ASS styling; final encoding still burns the original ASS. No publication approval or validated final video is created by review.'}
    (out/'review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return {k:v for k,v in report.items() if k!='samples'} | {'sample_count':len(samples)}
