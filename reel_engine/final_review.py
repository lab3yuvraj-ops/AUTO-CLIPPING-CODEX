"""One real-MP4 review for source-reviewed stable dominant presenters."""
import hashlib
import json
import copy
from pathlib import Path
from PIL import Image,ImageDraw
from .render import probe,file_hash
from .review import review_frames
from .timeline import to_output
from .youtube_transcript import atomic_json


def review_route(job,spec):
    # The baseline is mandatory for every source; the old render-first bypass is retired.
    return 'pre-render-combined-review'


def interior_fingerprint(edit,tracking):
    # Boundary-only trim: same source word intervals, crop recipe and cuts.
    words=[{k:w.get(k) for k in ('id','source_start','source_end','roman')} for w in edit['words']] if 'words' in edit else []
    recipe=copy.deepcopy(tracking);a=edit['segments'][0]['source_start'];b=edit['segments'][-1]['source_end']
    for target in recipe.get('visual_targets',[]):
        if abs(target['start']-a)<.001:target['start']='story_start'
        if abs(target['end']-b)<.001:target['end']='story_end'
        for key in ('box_keyframes','safety_box_keyframes'):
            for point in target.get(key,[]):
                if abs(point['t']-a)<.001:point['t']='story_start'
                elif abs(point['t']-b)<.001:point['t']='story_end'
    for point in recipe.get('crop_keyframes',[]):
        if abs(point['t']-a)<.001:point['t']='story_start'
        elif abs(point['t']-b)<.001:point['t']='story_end'
    return hashlib.sha256(json.dumps([words,recipe],sort_keys=True).encode()).hexdigest()


def sample_final(video,edit,tracking,root):
    from .review_policy import inspection_plan,pixel_hash
    video=Path(video);out=Path(root)/'final-mp4-review';out.mkdir(exist_ok=True)
    digest=file_hash(video);fingerprint=interior_fingerprint(edit,tracking)
    signature=hashlib.sha256(json.dumps([digest,edit['segments'],tracking,3,file_hash(Path(__file__).with_name('review.py'))]).encode()).hexdigest()
    record=out/'review.json';old=json.loads(record.read_text(encoding='utf-8')) if record.is_file() else {}
    if (old.get('signature')==signature
        and all(Path(p).is_file() and file_hash(p)==h for p,h in old['page_hashes'].items())
        and all(Path(p).is_file() and pixel_hash(p)==h for p,h in old.get('frame_pixel_hashes',{}).items())):
        frame_plan=inspection_plan(root,'final_frames',list(old['frame_pixel_hashes']),old.get('flagged_frames',[]))
        required=set(frame_plan['required_pages']);frames=list(old['frame_pixel_hashes'])
        required_pages=[p for i,p in enumerate(old['pages']) if any(f in required for f in frames[i*12:i*12+12])]
        return {**old,'required_pages':required_pages,'carried_frames':frame_plan['carried_pages'],'cache_reused':True}
    meta=probe(video);v=next(s for s in meta['streams'] if s['codec_type']=='video')
    num,den=v['r_frame_rate'].split('/');fps=float(num)/float(den)
    duration=float(meta['format']['duration']);story=edit['duration']
    boundary_only=bool(old.get('interior_fingerprint')==fingerprint and old.get('segments')!=edit['segments'])
    points={0.,.1,max(0,story-.1),max(0,story-1/fps),min(duration-.05,story+.05),min(duration-.05,story+.5),duration-.1}
    if not boundary_only:
        for cut in tracking.get('camera_cuts',[]):
            for stamp in (cut-.05,cut+.05):
                mapped=to_output(stamp,edit['segments'])
                if mapped is not None:points.add(mapped)
    points.update(tracking.get('flagged_output_seconds',[]))
    indices=sorted({max(0,int(round(t*fps))) for t in points if 0<=t<duration-.025})
    frames=review_frames(video,indices,out)
    pages=[];frame_hashes={str(p.resolve()):pixel_hash(p) for p in frames}
    for first in range(0,len(frames),12):
        group=frames[first:first+12];sheet=Image.new('RGB',(960,1356),'#151515');draw=ImageDraw.Draw(sheet)
        for i,f in enumerate(group):
            x=i%4*240;y=i//4*452
            image=Image.open(f).resize((240,427));sheet.paste(image,(x,y+25))
            draw.text((x+4,y+4),f'Final MP4 {indices[first+i]/fps:.3f}s',fill='white')
        p=out/f'page-{first//12+1:02}.jpg';sheet.save(p,quality=95);pages.append(str(p.resolve()))
    # Per-frame pixel hashes carry approval even if timestamps/page grouping move.
    flag_indices={max(0,int(round(t*fps))) for t in tracking.get('flagged_output_seconds',[]) if 0<=t<duration-.025}
    flagged_frames=[str(f.resolve()) for i,f in zip(indices,frames) if i in flag_indices]
    carried=inspection_plan(root,'final_frames',frames,flagged_frames)
    required_set=set(carried['required_pages'])
    required_pages=[p for i,p in enumerate(pages) if any(str(f.resolve()) in required_set for f in frames[i*12:i*12+12])]
    report={'signature':signature,'video_sha256':digest,'pages':pages,'page_hashes':{p:file_hash(p) for p in pages},
        'pixel_hashes':{p:pixel_hash(p) for p in pages},'frame_pixel_hashes':frame_hashes,
        'required_pages':required_pages,'carried_frames':carried['carried_pages'],'flagged_frames':flagged_frames,
        'sample_seconds':[i/fps for i in indices],'interval_seconds':None,'cache_reused':False,
        'interior_fingerprint':fingerprint,'segments':edit['segments'],'boundary_only':boundary_only,
        'review_strategy':'final-exceptions','human_inspection_required':True,
        'note':'Inspect opening, ending, CTA join, scene cuts and flagged frames once. Boundary-only trim with identical interior recipe samples only edges/CTA. Pixel carry-over requires actual prior inspection; encoded file hashes alone are insufficient.'}
    atomic_json(record,report);return report
