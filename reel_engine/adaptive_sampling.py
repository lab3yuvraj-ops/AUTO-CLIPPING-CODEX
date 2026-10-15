"""CPU-only review triage; image differences never establish semantic identity."""
import math
import numpy as np
from PIL import Image


PROFILES = {
    'fast': {'moving_interval': 1.0, 'static_interval': 3.0, 'motion_threshold': .035},
    'smart': {'moving_interval': .5, 'static_interval': 2.0, 'motion_threshold': .02},
}


def representative_frames(frames, mode='smart', context_times=()):
    if mode not in PROFILES:
        raise ValueError('Unknown processing mode')
    if not frames:
        return [], {'decoded_candidates': 0, 'analyzed_frames': 0}
    cfg=PROFILES[mode]; times=[f['source_seconds'] for f in frames]
    if any(not math.isfinite(t) for t in times) or times!=sorted(set(times)):
        raise ValueError('Frame timestamps must be finite and strictly ordered')
    selected={0:['opening'],len(frames)-1:['ending']}
    def keep(i,reason):
        if 0<=i<len(frames):selected.setdefault(i,[]).append(reason)
    for i,f in enumerate(frames):
        if (f.get('scene_score') or 0)>.18:
            for n in (i-1,i,i+1):keep(n,'scene-transition')
    for t in context_times:
        if times[0]<=t<=times[-1]:keep(min(range(len(times)),key=lambda i:abs(times[i]-t)),'transcript-transition')
    last=0;previous=None
    for i,f in enumerate(frames):
        with Image.open(f['file']) as im:
            pixels=np.asarray(im.convert('L').resize((96,54)),dtype=np.float32)/255
        difference=0. if previous is None else float(np.mean(np.abs(pixels-previous)))
        previous=pixels
        moving=difference>cfg['motion_threshold']
        interval=cfg['moving_interval'] if moving else cfg['static_interval']
        if times[i]-times[last]>=interval-1e-6:
            keep(i,'motion' if moving else 'static-coverage');last=i
        if moving:
            # Moving witnesses in smart mode and actual cuts are not sacrificed
            # to meet a frame budget. Both policies preserve their reasons.
            if mode=='smart':keep(i,'motion-witness')
    result=[dict(frames[i],sampling_reasons=sorted(set(selected[i]))) for i in sorted(selected)]
    return result, {'mode':mode,'decoded_candidates':len(frames),'analyzed_frames':len(result),
                    'soft_budget_exceeded':len(result)>50,'identity_established':False,
                    'note':'Cuts, motion and transcript changes retained; no hard cap drops witnesses.'}
