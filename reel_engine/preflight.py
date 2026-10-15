"""Source-bound cut checks and geometric crop safety; no image approval."""
import copy,json,math,re,hashlib
from pathlib import Path
import numpy as np
from .render import probe,run,file_hash,plan_camera
from .tracking import crop_centers,fill_missing_centers
from .timeline import to_source
from .youtube_transcript import atomic_json

def detect_boundary_cuts(source,start,end,root):
    # Same FFmpeg scene score as detail.py, at full temporal resolution. Scores
    # are proposals, not calibrated probabilities or proof of identity.
    from .editing_plan import fingerprint
    cache=Path(root)/'boundary-detection-cache.json'
    signature=fingerprint({'source':file_hash(source),'start':start,'end':end,
                           'implementation':file_hash(__file__),'threshold':.18,'window':.5})
    if cache.exists():
        try:
            old=json.loads(cache.read_text(encoding='utf8'))
            if old.get('signature')==signature and old.get('content_hash')==fingerprint(old.get('rows')):
                return old['rows']
        except (ValueError,TypeError,KeyError):pass
    meta=probe(source);duration=float(meta['format']['duration']);rows=[]
    for label,a,b in [('opening',max(0,start-.5),min(duration,start+.5)),('ending',max(0,end-.5),min(duration,end+.5))]:
        result=run(['ffmpeg','-hide_banner','-hwaccel','none','-ss',str(a),'-t',str(b-a),'-i',str(source),'-an','-filter_threads','1','-vf',"scale=640:-2,select='gt(scene,0.18)',metadata=print:key=lavfi.scene_score,showinfo",'-fps_mode','vfr','-f','null','-'])
        stamps=[float(x) for x in re.findall(r'\bn:\s*\d+.*?\bpts_time:([\d.eE+-]+)',result.stderr)]
        scores=[float(x) for x in re.findall(r'lavfi.scene_score=([\d.eE+-]+)',result.stderr)]
        rows.extend({'time':a+t,'score':scores[i] if i<len(scores) else 0,'edge':label,'evidence':'Actual boundary audio/video-source frames; FFmpeg scene score'} for i,t in enumerate(stamps) if a<=a+t<b)
    atomic_json(cache,{'signature':signature,'rows':rows,'content_hash':fingerprint(rows)})
    return rows

def snap_boundaries(candidate,words,cuts,fps=30,window=.5,threshold=.30):
    plan=copy.deepcopy(candidate);snaps=[];flags=[]
    selected=[w for w in words if candidate['start']<=w['start']<w['end']<=candidate['end']]
    if not selected:return plan,[],[{'reason':'No boundary words available'}]
    first=min(w['start'] for w in selected);last=max(w['end'] for w in selected)
    for edge in ('start','end'):
        original=candidate[edge]
        near=[c for c in cuts if original<c['time']<=original+window] if edge=='start' else [c for c in cuts if original-window<=c['time']<original]
        for c in sorted(near,key=lambda c:abs(c['time']-original)):
            if c.get('score',0)<threshold:
                flags.append({'edge':edge,'time':c['time'],'reason':'Ambiguous scene-cut confidence; no automatic snap'});continue
            proposed=c['time']+1/fps if edge=='start' else c['time']-1/fps
            intact=proposed<=first if edge=='start' else proposed>=last
            if not intact:
                flags.append({'edge':edge,'time':c['time'],'reason':'Snap would clip first/last spoken word; no automatic snap','options':'Start one word later, or keep the flash.'});continue
            if not 30<= (plan['end']-proposed if edge=='start' else proposed-plan['start'])<=60:
                flags.append({'edge':edge,'time':c['time'],'reason':'Snap would violate story duration'});continue
            plan[edge]=proposed;snaps.append({'edge':edge,'from':original,'to':proposed,'cut':c,'first_word_start':first,'last_word_end':last});break
    return plan,snaps,flags

def boundary_flashes(start,end,cuts,window=.5):
    return [dict(c,reason='Different shot inside first/last 0.5 seconds') for c in cuts if start+1e-5<c['time']<start+window or end-window<c['time']<end-1e-5]

def box_at(target,t,key='box_keyframes'):
    points=target.get(key,[])
    if not points:return target['box']
    return [float(np.interp(t,[p['t'] for p in points],[p['box'][axis] for p in points])) for axis in range(4)]

def margin_violation(box,geometry,width,height,margin=.04):
    cx,cy,ch=geometry;cw=ch*height/width*9/16;left=cx-cw/2;right=cx+cw/2;top=cy-ch/2;bottom=cy+ch/2
    x,y,w,h=box;m=margin*cw
    amounts={'left':max(0,left+m-x),'right':max(0,x+w-right+m),'top':max(0,top-y),'bottom':max(0,y+h-bottom),'source_left':max(0,-left),'source_right':max(0,right-1),'source_top':max(0,-top),'source_bottom':max(0,bottom-1)}
    return {k:v*width if k in ('left','right','source_left','source_right') else v*height for k,v in amounts.items() if v>1e-6}


def assess_subject_action(subject,action,geometry,width,height,margin=.04):
    subject_overflow=margin_violation(subject,geometry,width,height,margin)
    action_overflow=margin_violation(action,geometry,width,height,0) if action is not None else {}
    return {'subject_passed':not subject_overflow,'subject_overflow_pixels':subject_overflow,
        'action_overflow_pixels':action_overflow,
        'action_excess_width_pixels':max(0,action[2]*width-geometry[2]*height*9/16) if action is not None else 0,
        'action_status':('wide action, accepted' if not subject_overflow else 'wide action, subject unsafe') if action_overflow else None}

def crop_safety(source,edit,tracking,margin=.04,interval=.25):
    import cv2
    if not 0<=margin<.5 or interval<=0:raise ValueError('Invalid crop-safety margin/interval')
    count=math.floor(edit['duration']*30);times=[to_source(i/30,edit['segments']) for i in range(count)]
    words=[{**w,'start':w.get('source_start',w['start']),'end':w.get('source_end',w['end'])} for w in edit['words']]
    centers=fill_missing_centers(crop_centers(tracking,words,times),tracking,times)
    cap=cv2.VideoCapture(str(source));width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if width<=0 or height<=0:cap.release();raise ValueError('Cannot probe crop-safety source')
    # plan_camera's unanchored decoder expects the edited timeline. Automated
    # safety cannot invent animated identity evidence; require reviewed anchors.
    missing=[i for i,t in enumerate(tracking.get('visual_targets',[])) if not t.get('box_keyframes')]
    if missing:cap.release();return {'passed':False,'violations':[{'scene':i,'reason':'Missing reviewed target anchors'} for i in missing]}
    try:camera,_,_=plan_camera(cap,tracking,centers,times,30)
    finally:cap.release()
    points={min(count-1,round(k*interval*30)) for k in range(math.ceil(edit['duration']/interval))}
    points.update([0,count-1])
    for target in tracking.get('visual_targets',[]):
        for stamp in [target['start'],target['end']-1/30,*[k['t'] for key in ('box_keyframes','action_box_keyframes','camera_center_keyframes') for k in target.get(key,[])]]:
            if times:points.add(min(range(count),key=lambda i:abs(times[i]-stamp)))
    violations=[];action_warnings=[]
    for i in sorted(points):
        t=times[i]
        bounds={k:v for k,v in margin_violation([0,0,0,0],camera[i],width,height,0).items() if k.startswith('source_')}
        if bounds:violations.append({'scene':0,'source_seconds':t,'output_seconds':i/30,'amount_pixels':bounds,'reason':'Crop outside source'})
        for scene,target in enumerate(tracking.get('visual_targets',[]),1):
            if target['start']<=t<target['end']:
                key='safety_box_keyframes' if target.get('safety_box_keyframes') else 'box_keyframes'
                box=box_at(target,t,key);amounts=margin_violation(box,camera[i],width,height,margin)
                if amounts:
                    usable=camera[i][2]*height*9/16*(1-2*margin)
                    violations.append({'scene':scene,'source_seconds':t,'output_seconds':i/30,'amount_pixels':amounts,'reason':target['reason'],'target_width_pixels':box[2]*width,'usable_crop_width_pixels':usable,'impossible_full_subject_fit':box[2]*width>usable+1e-6})
                if target.get('action_box_keyframes'):
                    assessment=assess_subject_action(box,box_at(target,t,'action_box_keyframes'),camera[i],width,height,margin)
                    if assessment['action_status']:
                        action_warnings.append({'scene':scene,'source_seconds':t,'output_seconds':i/30,'status':assessment['action_status'],'amount_pixels':assessment['action_overflow_pixels'],'action_excess_width_pixels':assessment['action_excess_width_pixels'],'subject_passed':assessment['subject_passed']})
    return {'passed':not violations,'margin_fraction_of_crop_width':margin,'sample_interval_seconds':interval,'samples':len(points),'violations':violations,'action_warnings':action_warnings,'action_summary':summarize_actions(action_warnings),'flagged_scenes':sorted(set(v['scene'] for v in violations)),'note':'Subject (full reviewed face/head/main focus) must fit with margin. Reviewed gesture/prop/secondary action may overflow, with a persistent warning; it never excuses unsafe subject framing.'}


def summarize_actions(rows):
    result=[]
    for scene in sorted({r['scene'] for r in rows}):
        items=[r for r in rows if r['scene']==scene];worst=max(items,key=lambda r:max(r['amount_pixels'].values(),default=0))
        result.append({'scene':scene,'start':min(r['source_seconds'] for r in items),'end':max(r['source_seconds'] for r in items),'status':'wide action, accepted' if all(r['subject_passed'] for r in items) else 'wide action, subject unsafe','worst_source_seconds':worst['source_seconds'],'maximum_overflow_pixels':max(worst['amount_pixels'].values()),'maximum_excess_width_pixels':max(r['action_excess_width_pixels'] for r in items),'worst_edge_overflow_pixels':worst['amount_pixels']})
    return result

def approved_boundary_rows(spec,source_sha256,rows):
    """A human may retain an exact source-bound shot change to preserve a word."""
    decisions=spec.get('boundary_review',[])
    accepted=[];remaining=[]
    for row in rows:
        match=next((d for d in decisions if d.get('choice')=='keep-flash'
            and d.get('approved_by')=='human' and d.get('evidence')
            and d.get('source_sha256')==source_sha256
            and d.get('candidate_start')==spec['candidate']['start']
            and d.get('candidate_end')==spec['candidate']['end']
            and d.get('edge') in (row.get('edge'), 'start' if row.get('edge')=='opening' else 'end' if row.get('edge')=='ending' else None)
            and abs(d.get('time',-100)-row['time'])<.002),None)
        (accepted if match else remaining).append(row)
    return remaining,accepted


def preflight(source,spec,edit,tracking,root,margin=.04):
    cuts=detect_boundary_cuts(source,spec['candidate']['start'],spec['candidate']['end'],root)
    _,snaps,flags=snap_boundaries(spec['candidate'],spec['words'],cuts)
    flashes=boundary_flashes(spec['candidate']['start'],spec['candidate']['end'],cuts)
    source_sha256=file_hash(source)
    flags,accepted_flags=approved_boundary_rows(spec,source_sha256,flags)
    flashes,accepted_flashes=approved_boundary_rows(spec,source_sha256,flashes)
    safety=crop_safety(source,edit,tracking,margin)
    from .motion_check import for_job
    motion=for_job(spec,root)
    from .timeline import to_output
    motion['flagged_output_seconds']=[mapped for t in motion.get('flagged_source_seconds',[]) if (mapped:=to_output(t,edit['segments'])) is not None]
    report={'source_sha256':source_sha256,'spec_sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest(),'boundary_cuts':cuts,'suggested_snaps':snaps,'boundary_flags':flags,'boundary_flashes':flashes,'accepted_boundary_flags':accepted_flags,'accepted_boundary_flashes':accepted_flashes,'crop_safety':safety,'motion_check':motion,'editorial_warnings':action_warning_messages(safety)+[f"Human approved retaining {r['edge']} shot change at {r['time']:.3f}s to preserve the spoken ending." for r in accepted_flashes],'passed':not flashes and not flags and safety['passed']}
    atomic_json(Path(root)/'preflight.json',report);return report


def action_warning_messages(safety):
    return [f"Scene {r['scene']} {r['start']:.3f}-{r['end']:.3f}s: {r['status']}; up to {r['maximum_overflow_pixels']:.2f}px overflow." for r in safety.get('action_summary',[])]


def crop_review_flags(checks):
    """Log all violations, inspect the worst witness per violating scene."""
    worst={}
    safety=checks.get('crop_safety',{})
    for kind,rows in [('subject',safety.get('violations',[])),('action',safety.get('action_warnings',[]))]:
        for row in rows:
            if 'output_seconds' not in row:continue
            key=(row['scene'],kind);severity=max(row.get('amount_pixels',{}).values(),default=0)
            if key not in worst or severity>worst[key][0]:worst[key]=(severity,row['output_seconds'])
    output=[item[1] for _,item in sorted(worst.items())]
    # Source-to-edit mapping is supplied by the caller; never reuse source seconds as output.
    output.extend(checks.get('motion_check',{}).get('flagged_output_seconds',[]))
    return sorted(set(output))

def snap_spec(source,spec,root):
    cuts=detect_boundary_cuts(source,spec['candidate']['start'],spec['candidate']['end'],root)
    candidate,snaps,flags=snap_boundaries(spec['candidate'],spec['words'],cuts)
    result=copy.deepcopy(spec)
    if snaps:
        result['candidate']=candidate;a,b=candidate['start'],candidate['end']
        candidate['preserve_pauses']=[[max(a,x),min(b,y)] for x,y in candidate.get('preserve_pauses',[]) if max(a,x)<min(b,y)]
        targets=[]
        for target in result['tracking'].get('visual_targets',[]):
            target.setdefault('scene_start',target['start']);target.setdefault('scene_end',target['end'])
            s,e=max(a,target['start']),min(b,target['end'])
            if s>=e:continue
            for key in ('box_keyframes','safety_box_keyframes','action_box_keyframes'):
                if target.get(key):
                    start_box=box_at(target,s,key);end_box=box_at(target,e,key)
                    target[key]=[{'t':s,'box':start_box},*[k for k in target[key] if s<k['t']<e],{'t':e,'box':end_box}]
            if target.get('camera_center_keyframes'):
                points=target['camera_center_keyframes'];times=[p['t'] for p in points];centers=[p['center'] for p in points]
                target['camera_center_keyframes']=[{'t':s,'center':float(np.interp(s,times,centers))},*[p for p in points if s<p['t']<e],{'t':e,'center':float(np.interp(e,times,centers))}]
            target['start']=s;target['end']=e;targets.append(target)
        result['tracking']['visual_targets']=targets
        result['tracking']['camera_cuts']=[c for c in result['tracking'].get('camera_cuts',[]) if a<c<b]
        log=Path(root)/'boundary-snaps.json';old=json.loads(log.read_text(encoding='utf-8')) if log.exists() else []
        old.extend(snaps);atomic_json(log,old)
    atomic_json(Path(root)/'boundary-snap-check.json',{'cuts':cuts,'snaps':snaps,'flags':flags})
    return result


def choose_word_boundary(spec,root,choice):
    """Explicit human choice only. Never remove a verified word automatically."""
    result=copy.deepcopy(spec);candidate=result['candidate'];words=sorted(result['words'],key=lambda w:w['start'])
    selected=[w for w in words if candidate['start']<=w['start']<w['end']<=candidate['end']]
    if choice not in ('start-next-word','keep-flash') or len(selected)<2:raise ValueError('Boundary choice needs two verified words and an explicit supported choice')
    first,second=selected[:2]
    if choice=='start-next-word':
        a=max(first['end'],second['start'])
        if not 30<=candidate['end']-a<=60:raise ValueError('Starting one word later would violate story duration')
        candidate['start']=a;result['words']=[w for w in result['words'] if w['start']>=a]
        for target in result['tracking'].get('visual_targets',[]):
            target.setdefault('scene_start',target['start']);target.setdefault('scene_end',target['end'])
            if target['start']<a<target['end']:
                for key in ('box_keyframes','safety_box_keyframes','action_box_keyframes'):
                    if target.get(key):target[key]=[{'t':a,'box':box_at(target,a,key)},*[p for p in target[key] if p['t']>a]]
                target['start']=a
                if target.get('camera_center_keyframes'):
                    camera=target['camera_center_keyframes'];center=float(np.interp(a,[p['t'] for p in camera],[p['center'] for p in camera]))
                    target['camera_center_keyframes']=[{'t':a,'center':center},*[p for p in camera if p['t']>a]]
        candidate['preserve_pauses']=[[max(a,x),y] for x,y in candidate.get('preserve_pauses',[]) if y>a]
    atomic_json(Path(root)/'word-boundary-choice.json',{'choice':choice,'options':'Start one word later, or keep the flash.','before':spec['candidate']['start'],'after':candidate['start'],'removed_word':first if choice=='start-next-word' else None,'next_word':second,'editorial_note':'Human chose omission of the first word; independently understandable opening still requires review. No wording was invented.'})
    return result
