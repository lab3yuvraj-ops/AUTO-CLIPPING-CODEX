"""Scene-bound speaker camera from reviewed visual/audio associations only.

This module does not identify faces, infer left/right from voices, or establish
who spoke. It converts selected local speech evidence and reviewed identity
tracks into crop keys consumed by both renderers' existing camera easing.
"""
import bisect
import math


def _finite(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)


def _text(value):
    return isinstance(value,str) and bool(value.strip())


def build_speaker_camera(turns,scenes,associations,*,start=None,end=None,
                         min_hold_seconds=1.2,confidence_threshold=.8,fps=30):
    """Return compatible tracking and deduplicated editorial warnings.

    ``turns``: start/end/speaker, optional confidence/speaker_uncertain.
    ``scenes``: id/start/end/stable_center/evidence, actual source shots.
    ``associations``: scene/speaker/confidence, visual_evidence,
    speech_mouth_evidence, and center_keyframes[{t,center}]. All time values
    are local to the same selected media. Associations never cross scene cuts.
    """
    if not _finite(min_hold_seconds) or not 1.2<=min_hold_seconds<=10:
        raise ValueError('Speaker camera minimum hold must be 1.2–10 seconds.')
    if not _finite(confidence_threshold) or not .8<=confidence_threshold<=1:
        raise ValueError('Speaker visual confidence threshold must be at least 80%.')
    if fps!=30:raise ValueError('Speaker camera uses the approved 30 fps timeline.')
    if not isinstance(scenes,list) or not scenes:raise ValueError('Reviewed chronological scenes are required.')
    scenes=sorted(scenes,key=lambda s:s['start']);seen=set();previous=-math.inf
    for scene in scenes:
        if scene.get('id') in seen or not isinstance(scene.get('id'),(int,str)):
            raise ValueError('Scene identities must be unique strings or integers.')
        seen.add(scene['id'])
        a,b=scene.get('start'),scene.get('end');center=scene.get('stable_center')
        if not _finite(a) or not _finite(b) or not 0<=a<b or a<previous:
            raise ValueError('Scene bounds must be chronological, finite and non-overlapping.')
        if not _finite(center) or not 0<=center<=1 or not _text(scene.get('evidence')):
            raise ValueError('Each scene needs its reviewed stable center and cut/identity evidence.')
        previous=b
    start=scenes[0]['start'] if start is None else start
    end=scenes[-1]['end'] if end is None else end
    if not _finite(start) or not _finite(end) or not scenes[0]['start']<=start<end<=scenes[-1]['end']:
        raise ValueError('Camera passage must be inside the reviewed scene timeline.')
    if end-start>180:raise ValueError('Speaker camera accepts selected passages at most 180 seconds.')
    scene_by_id={s['id']:s for s in scenes};lookup={}
    for item in associations:
        scene=scene_by_id.get(item.get('scene'));speaker=item.get('speaker');confidence=item.get('confidence')
        if scene is None or not _text(speaker) or not _finite(confidence) or not 0<=confidence<=1:
            raise ValueError('Speaker associations need an existing scene, label and finite confidence.')
        if not _text(item.get('visual_evidence')) or not _text(item.get('speech_mouth_evidence')):
            raise ValueError('Voice labels alone cannot establish visible speaker identity: visual and mouth/speech evidence are required.')
        key=(scene['id'],speaker)
        if key in lookup:raise ValueError('Duplicate speaker association in a scene.')
        anchors=item.get('center_keyframes');last=-math.inf
        if not isinstance(anchors,list) or not anchors:raise ValueError('Reviewed visible center anchors are required.')
        for anchor in anchors:
            t,center=anchor.get('t'),anchor.get('center')
            if not _finite(t) or not scene['start']<=t<=scene['end'] or t<=last or not _finite(center) or not 0<=center<=1:
                raise ValueError('Speaker identity anchors must increase within their scene and image.')
            last=t
        lookup[key]=item
    filtered=[];ignored=[]
    for turn in turns:
        a,b=turn.get('start'),turn.get('end');confidence=turn.get('confidence',1.)
        if not _finite(a) or not _finite(b) or not 0<=a<b or not _text(turn.get('speaker')) or not _finite(confidence) or not 0<=confidence<=1:
            raise ValueError('Selected speaker turns need finite intervals, labels and confidence.')
        if b<=start or a>=end:continue
        if b-a<.4:
            ignored.append({'start':a,'end':b,'speaker':turn['speaker'],'reason':'Brief interjection under 0.4 seconds; no camera switch.'})
        else:filtered.append(turn)
    def center_at(item,t):
        keys=item['center_keyframes'];stamps=[k['t'] for k in keys];i=max(0,bisect.bisect_right(stamps,t)-1)
        if i==len(keys)-1:return keys[i]['center']
        a,b=keys[i],keys[i+1];u=max(0,min(1,(t-a['t'])/(b['t']-a['t'])))
        return a['center']+(b['center']-a['center'])*u
    keys=[];warnings=[];warning_keys=set();switches=[];scene=None;held=None;held_center=.5;last_switch=-math.inf
    count=math.ceil((end-start)*fps)
    for n in range(count):
        t=start+n/fps
        current=next((s for s in scenes if s['start']<=t<s['end']),None)
        if current is None:raise ValueError('Reviewed scenes must cover every selected camera frame.')
        cut=scene is None or current['id']!=scene['id']
        if cut:
            scene=current;held=None;held_center=scene['stable_center'];last_switch=-math.inf
        active=[turn for turn in filtered if turn['start']<=t<turn['end']]
        speakers={turn['speaker'] for turn in active};reason=None;requested=None
        if len(speakers)>1 or any(turn.get('overlapping_speech') for turn in active):reason='overlapping_speakers'
        elif speakers:
            requested=next(iter(speakers));item=lookup.get((scene['id'],requested))
            uncertain=any(turn.get('speaker_uncertain') or turn['speaker'].upper() in ('UNKNOWN','UNK','NONE') or turn.get('confidence',1)<confidence_threshold for turn in active)
            if uncertain:reason='uncertain_audio_speaker'
            elif item is None:reason='missing_scene_bound_visual_identity'
            elif item['confidence']<confidence_threshold:reason='low_visual_identity_confidence'
            else:
                if requested!=held and t-last_switch>=min_hold_seconds-1e-9:
                    switches.append({'t':t,'scene':scene['id'],'from':held,'to':requested,'evidence':item['speech_mouth_evidence']})
                    held=requested;last_switch=t
                if held is not None:
                    old=lookup[(scene['id'],held)];held_center=center_at(old,t)
        if reason:
            signature=(scene['id'],reason,tuple(sorted(speakers)))
            if signature not in warning_keys:
                warning_keys.add(signature);warnings.append({'t':t,'scene':scene['id'],'speaker_labels':sorted(speakers),
                    'reason':reason,'action':'Held last confident horizontal crop; reset to reviewed stable center at actual cuts.','requires_editorial_review':True})
        # Incoming cut=True makes crop_centers hold the previous value until
        # this point. Existing ease_camera supplies all 1.2s easing and resets
        # only at camera_cuts, not at speaker changes.
        if cut or not keys or abs(held_center-keys[-1]['center'])>1e-9:
            keys.append({'t':t,'center':held_center,'cut':True})
    cuts=[s['start'] for s in scenes if start<s['start']<end]
    return {'mode':'auto','composition':'fill','crop_policy':'full_source_height_horizontal_only',
            'camera_smoothing':True,'camera_easing_seconds':1.2,'camera_cuts':cuts,
            'crop_keyframes':keys,'editorial_warnings':warnings,'speaker_switches':switches,
            'ignored_interjections':ignored,'min_hold_seconds':min_hold_seconds,
            'speaker_confidence_threshold':confidence_threshold,'speaker_camera_version':1,
            'unresolved':bool(warnings),'note':'Reviewed identity evidence only; no automatic audio-label-to-screen-side inference. Existing camera easing supplies horizontal movement, with full source height and no zoom.'}
