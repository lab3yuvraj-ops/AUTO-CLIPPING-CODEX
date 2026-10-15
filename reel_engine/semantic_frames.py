"""Optional semantic input compaction; mandatory visual evidence is never dropped."""
import math
from .editing_plan import fingerprint

MANDATORY={'opening','ending','scene-transition','motion-witness','motion',
           'transcript-transition','critical-subject-change','identity-anchor','flagged'}


def select_frames(details, strategy='baseline'):
    if strategy not in ('baseline','evidence-preserving'):raise ValueError('Unknown Gemini frame strategy')
    frames=details['frames'];keep=[];last=-math.inf;removed=[]
    for i,f in enumerate(frames):
        # Unknown sampling metadata is never evidence of static/unimportant content.
        reasons=set(f.get('sampling_reasons',[]))
        mandatory=(i in (0,len(frames)-1) or not reasons or bool(reasons&MANDATORY)
                   or bool(reasons-{'static-coverage'}) or (f.get('scene_score') or 0)>.18)
        selected=(strategy=='baseline' or mandatory or f['source_seconds']-last>=4)
        if selected:keep.append(f);last=f['source_seconds']
        else:removed.append({'source_seconds':f['source_seconds'],'sha256':f['sha256'],'reason':'redundant static-only coverage within4seconds'})
    report={'strategy':strategy,'baseline_count':len(frames),'selected_count':len(keep),
            'mandatory_count':sum(f in keep for f in frames if set(f.get('sampling_reasons',[]))&MANDATORY),
            'removed':removed,'baseline_frame_hash':fingerprint(frames),'selected_frame_hash':fingerprint(keep),
            'identity_verified':False,'note':'All cuts/motion/context/identity/unknown witnesses retained. Compaction is optional and not semantic approval.'}
    return {**details,'frames':keep},report


def estimate(details, transcript, config, strategy='baseline', *, prompt=None):
    selected,coverage=select_frames(details,strategy)
    # Admission bound calibrated conservatively above measured94,561/72 input
    # tokens. Not Google countTokens or a promise of actual consumption.
    text=math.ceil(len(__import__('json').dumps(prompt if prompt is not None else transcript).encode())/3)
    schema=math.ceil(len(__import__('json').dumps(config).encode())/3)
    overhead=2048 if prompt is None else 0
    return {**coverage,'estimated_input_admission_tokens':1600*len(selected['frames'])+text+schema+overhead,
            'estimated_total_reservation_tokens':1600*len(selected['frames'])+text+schema+overhead+config['maxOutputTokens'],
            'token_estimate_kind':'conservative local admission bound; not provider measurement'}
