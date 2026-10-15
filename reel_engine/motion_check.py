"""CPU proxy motion triage before image review, not semantic identity proof."""
import json,time,math,hashlib
from pathlib import Path
import cv2
import numpy as np
from .youtube_transcript import atomic_json


def motion_flags(rows,start,end,easing=1.2,margin=.04):
    """Rows contain measured subject centers/widths and planned camera centers."""
    flags=[]
    initial=rows[0] if rows else {}
    initial_slack=max(0,initial.get('crop_width',0)*(.5-margin)-initial.get('width',0)/2)
    initial_overflow=max(0,abs(initial.get('center',0)-initial.get('camera_center',0))-initial_slack)
    for previous,row in zip(rows,rows[1:]):
        dt=row['t']-previous['t']
        if dt<=0:continue
        crop_width=row['crop_width'];slack=max(0,crop_width*(.5-margin)-row['width']/2)
        speed=abs(row['center']-previous['center'])/dt
        overflow=max(0,abs(row['center']-row['camera_center'])-slack)
        reasons=[]
        if speed*easing>slack and abs(row['center']-previous['center'])>.015:reasons.append('subject_motion_exceeds_eased_camera_slack')
        # Static geometry already belongs to crop_safety. Flag new motion drift.
        if overflow>initial_overflow+.015:reasons.append('measured_subject_outside_planned_crop')
        if row.get('confidence',1)<.45:reasons.append('motion_tracking_low_confidence')
        if reasons:flags.append({'source_seconds':row['t'],'reasons':reasons,'overflow_source_fraction':overflow,'speed_source_widths_per_second':speed,'near_boundary':min(abs(row['t']-start),abs(end-row['t']))<=.5})
    return flags


def check_motion(proxy,spec,root,source_offset=0.,interval=.1):
    from .render import file_hash,plan_camera
    from .timeline import build_edit
    from .tracking import crop_centers,fill_missing_centers
    root=Path(root);root.mkdir(parents=True,exist_ok=True);clock=time.perf_counter()
    proxy_hash=file_hash(proxy);spec_hash=hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()
    signature={'proxy_sha256':proxy_hash,'spec_sha256':spec_hash,'source_offset':source_offset,'interval':interval,'implementation':file_hash(__file__)}
    saved=root/'motion-check.json'
    if saved.exists():
        old=json.loads(saved.read_text(encoding='utf-8'))
        if old.get('signature')==signature:return old | {'cache_reused':True,'seconds_this_run':time.perf_counter()-clock}
    cap=cv2.VideoCapture(str(proxy));native_fps=cap.get(cv2.CAP_PROP_FPS) or 30; width=cap.get(cv2.CAP_PROP_FRAME_WIDTH);height=cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    if not width or not height:raise ValueError('Motion triage needs a validated decoded proxy.')
    # Camera evaluation uses the existing easing implementation and exact spec.
    edit=build_edit(spec['candidate'],spec['words'],[]);fps=30;times=[spec['candidate']['start']+n/fps for n in range(math.ceil(edit['duration']*fps))]
    tracking=spec['tracking'];centers=fill_missing_centers(crop_centers(tracking,spec['words'],times),tracking,times)
    camera,_,_=plan_camera(cap,tracking,centers,times,fps);scenes=[]
    for index,target in enumerate(tracking.get('visual_targets',[]),1):
        a,b=target['start'],target['end'];cap.set(cv2.CAP_PROP_POS_MSEC,(a+source_offset)*1000)
        ok,frame=cap.read()
        if not ok:raise ValueError('Proxy motion frame missing.')
        old=cv2.cvtColor(cv2.resize(frame,(640,round(640*height/width))),cv2.COLOR_BGR2GRAY);h,w=old.shape
        box=(target.get('safety_box_keyframes') or target.get('box_keyframes') or [{'box':target['box']}])[0]['box'];x,y,bw,bh=box
        rows=[];lost=False;step=max(1,round(interval*native_fps));count=math.ceil((b-a)*native_fps)
        def row(t,confidence):
            n=min(len(camera)-1,max(0,round((t-times[0])*fps)))
            return {'t':t,'center':x+bw/2,'width':bw,'camera_center':camera[n][0],'crop_width':height/width*9/16,'confidence':confidence}
        rows.append(row(a,1))
        for k in range(1,count):
            ok,frame=cap.read()
            if not ok:break
            if k%step:continue
            gray=cv2.cvtColor(cv2.resize(frame,(w,h)),cv2.COLOR_BGR2GRAY);mask=np.zeros_like(old)
            mask[max(0,int(y*h)):min(h,int((y+bh)*h)),max(0,int(x*w)):min(w,int((x+bw)*w))]=255
            points=cv2.goodFeaturesToTrack(old,80,.01,3,mask=mask)
            confidence=0.
            if points is not None and len(points)>=4:
                nxt,status,error=cv2.calcOpticalFlowPyrLK(old,gray,points,None,winSize=(31,31),maxLevel=3)
                back,backstatus,_=cv2.calcOpticalFlowPyrLK(gray,old,nxt,None,winSize=(31,31),maxLevel=3) if nxt is not None else (None,None,None)
                if back is not None:
                    valid=(status.ravel()>0)&(backstatus.ravel()>0)&(np.linalg.norm(back-points,axis=2).ravel()<2.)
                    confidence=float(valid.mean())
                    if valid.sum()>=4:
                        delta=np.median((nxt-points).reshape(-1,2)[valid],axis=0);x=float(np.clip(x+delta[0]/w,0,1-bw));y=float(np.clip(y+delta[1]/h,0,1-bh))
                    else:lost=True
            if confidence<.45:lost=True
            rows.append(row(a+k/native_fps,confidence));old=gray
        flags=motion_flags(rows,spec['candidate']['start'],spec['candidate']['end'])
        if lost and not flags:flags=[{'source_seconds':a,'reasons':['motion_tracking_low_confidence'],'near_boundary':a-spec['candidate']['start']<=.5,'overflow_source_fraction':0}]
        if flags:
            worst=max(flags,key=lambda f:f.get('overflow_source_fraction',0));scenes.append({'scene':index,'scene_start':a,'scene_end':b,'reason':target['reason'],'witness':worst,'flags':flags,'tracking_lost':lost})
    cap.release()
    report={'signature':signature,'cache_reused':False,'proxy_sha256':file_hash(proxy),'spec_sha256':hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest(),'source_offset':source_offset,'interval':interval,'easing_seconds':1.2,'flagged_scenes':scenes,'flagged_source_seconds':sorted({s['witness']['source_seconds'] for s in scenes}), 'boundary_flags':[f for s in scenes for f in s['flags'] if f.get('near_boundary')],'seconds':time.perf_counter()-clock,'note':'Measured CPU optical flow triage on reviewed subject regions. Flags require image review; low confidence is not a claim of correct identity. No captions, cuts or source pixels are changed.'}
    atomic_json(root/'motion-check.json',report);return report


def for_job(spec,root):
    root=Path(root);jobpath=root/'job.json'
    def unavailable(reason):
        # Missing motion evidence cannot silently reduce review coverage.
        return {'flagged_source_seconds':[(t['start']+t['end'])/2 for t in spec['tracking'].get('visual_targets',[])],
                'unavailable':reason,'review_fallback':'Inspect each scene because proxy motion triage is unavailable.'}
    if not jobpath.exists():return unavailable('No proxy job record')
    job=json.loads(jobpath.read_text(encoding='utf-8'));parent=root.parent/job.get('source_job_id','')/'job.json'
    if job.get('source_job_id') and job.get('source_time_offset') is None:
        return unavailable('Proxy-to-final offset is unverified; inspect final-source scene frames')
    if not parent.is_file():return unavailable('No source proxy record; geometric preflight still applies')
    source=json.loads(parent.read_text(encoding='utf-8'));proxy=source.get('proxy',{})
    if not proxy.get('source'):return unavailable('No accepted proxy; inspect every scene')
    from .config import settings
    return check_motion(proxy['source'],spec,root,job.get('source_time_offset') or 0,settings.motion_check_interval)
