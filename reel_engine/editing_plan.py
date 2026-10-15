"""One validated pre-render contract over the existing scene/caption system.

This is not a second editor or an identity detector. Semantic proposals must
contain real source-bound visual evidence before the existing review guards run.
"""
import hashlib
import json
import math
from pathlib import Path
from .youtube_transcript import atomic_json
from .visual_focus import validate_targets
from .scene_table import SceneTable, build_spec


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def compile_plan(job,spec,*,backend='legacy',preset='fast'):
    if backend not in ('legacy','direct') or preset not in ('fast','veryfast'):
        raise ValueError('Unsupported render configuration')
    candidate=spec['candidate'];a,b=candidate['start'],candidate['end']
    if not all(math.isfinite(t) for t in (a,b)) or not 0<=a<b or not 30<=b-a<=60:
        raise ValueError('Story bounds must be finite, complete and 30–60s')
    if not job.get('source_sha256'):raise ValueError('Plan requires final source binding')
    tracking=spec['tracking'];targets=validate_targets(tracking.get('visual_targets',[]),a,b)
    if not targets:raise ValueError('Plan requires evidenced visual subjects')
    cursor=a
    for target in targets:
        if abs(target['start']-cursor)>.001:raise ValueError('Missing or overlapping visual segment')
        if target.get('layout','smart_crop')!='smart_crop':raise ValueError('Unsupported layout; full-height crop contract remains')
        if not target.get('full_subject_bounds_confirmed') or not target.get('safety_box_keyframes'):
            raise ValueError('Independent full subject bounds are required')
        cursor=target['end']
    if abs(cursor-b)>.001:raise ValueError('Visual segments must cover story ending')
    words=spec['words'];ids=[w['id'] for w in words]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate caption word ID')
    for word in words:
        if not word.get('roman') or not all(math.isfinite(word[k]) for k in ('start','end')) or not a<=word['start']<word['end']<=b:
            raise ValueError('Caption word missing or outside passage')
    # Style remains owned by the existing caption module, never a VLM response.
    root=Path(__file__).resolve().parents[1]
    style={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
           (root/'reel_engine/captions.py',root/'reel_engine/style.py',root/'assets/Creepster-Regular.ttf')}
    cuts=tracking.get('camera_cuts',[])
    if any(not math.isfinite(t) or not a<t<b for t in cuts) or cuts!=sorted(set(cuts)):
        raise ValueError('Invalid transition/cut timeline')
    if tracking.get('camera_easing_seconds',1.2)!=1.2:raise ValueError('Camera easing must remain1.2s')
    content={'version':1,'source_sha256':job['source_sha256'],'candidate':candidate,
             'visual_segments':targets,'camera':{'easing_seconds':1.2,'cuts':cuts,'full_height':True,'horizontal_only':True},
             'caption':{'word_ids':ids,'source_intervals':[[w['start'],w['end']] for w in words],
                        'wording_hash':fingerprint(words),'style_hashes':style,'position':[500,1420]},
             'output':{'width':1080,'height':1920,'fps':30,'video_codec':'libx264','crf':18,'preset':preset,'backend':backend,'audio_codec':'aac'},
             'spec_hash':fingerprint(spec),'inspection_approved':False,'publication_approved':False}
    return {**content,'plan_hash':fingerprint(content)}


def save_plan(root,job,spec,**options):
    plan=compile_plan(job,spec,**options);path=Path(root)/'editing-plan.json'
    old=json.loads(path.read_text(encoding='utf8')) if path.exists() else {}
    atomic_json(path,plan)
    return {**plan,'cache_reused':old.get('plan_hash')==plan['plan_hash']}


def grounded_scene_proposal(base,proposal,details):
    """Validate semantic output against actual sampled source frames.

    Confidence alone never proves a visible identity. Unknown coordinates remain
    unresolved and no default center/face is invented to satisfy the schema.
    """
    from .semantic_diagnostics import GroundingError
    if not isinstance(proposal,dict):raise GroundingError('proposal_type',[], 'object',type(proposal).__name__)
    if proposal.get('source_sha256')!=details['source_sha256']:
        raise GroundingError('source_binding',['source_sha256'],details['source_sha256'],proposal.get('source_sha256'))
    if not proposal.get('model_version'):raise GroundingError('model_binding',['model_version'],'nonempty model',proposal.get('model_version'))
    frames={f['sha256']:f for f in details['frames']}
    rows=proposal.get('scenes',[])
    if not rows:raise GroundingError('no_subjects',['scenes'],'nonempty grounded scenes',rows)
    cleaned=[]
    for index,row in enumerate(rows):
        row=dict(row);evidence=row.pop('evidence_frames',[])
        if not evidence or any(h not in frames for h in evidence):raise GroundingError('unknown_frame',['scenes',index,'evidence_frames'],list(frames),evidence)
        if not any(row['start']<=frames[h]['source_seconds']<=row['end'] for h in evidence):
            raise GroundingError('frame_outside_scene',['scenes',index,'evidence_frames'],[row['start'],row['end']],[frames[h]['source_seconds'] for h in evidence])
        if row.get('confidence',0)<.8:raise GroundingError('low_confidence',['scenes',index,'confidence'],'>=0.8',row.get('confidence'))
        for ai,anchor in enumerate(row.get('subject_boxes',[])):
            if not any(abs(frames[h]['source_seconds']-anchor['t'])<=.51 for h in evidence):
                raise GroundingError('anchor_without_witness',['scenes',index,'subject_boxes',ai,'t'],'within0.51s of evidence frame',anchor['t'])
        cleaned.append(row)
    table=SceneTable.model_validate({'scenes':cleaned})
    for index,scene in enumerate(table.scenes):
        for ai,anchor in enumerate(scene.subject_boxes):
            ref=anchor.visible_subject_box
            if ref is None or not anchor.bounds_evidence:
                raise GroundingError('missing_full_subject_bounds',['scenes',index,'subject_boxes',ai],'independent full visible bounds and evidence',anchor.model_dump())
            x,y,w,h=anchor.box;rx,ry,rw,rh=ref
            if x>rx+1e-6 or x+w<rx+rw-1e-6 or y>ry+1e-6 or y+h<ry+rh-1e-6:
                raise GroundingError('incomplete_subject_bounds',['scenes',index,'subject_boxes',ai,'box'],ref,anchor.box)
    cursor=base['candidate']['start']
    for index,scene in enumerate(table.scenes):
        if abs(scene.start-cursor)>.001 or scene.end>base['candidate']['end']+.001:
            raise GroundingError('scene_coverage',['scenes',index],{'start':cursor,'maximum_end':base['candidate']['end']},{'start':scene.start,'end':scene.end})
        cursor=scene.end
    if abs(cursor-base['candidate']['end'])>.001:
        raise GroundingError('scene_coverage',['scenes',len(table.scenes)-1,'end'],base['candidate']['end'],cursor)
    result=build_spec(base,table)
    # A valid proposal is not actual first-pass inspection, nor publication approval.
    result['tracking'].update(confirmed=False,unresolved=True)
    return result
