import copy
from reel_engine.semantic_frames import select_frames,estimate,MANDATORY
from reel_engine.gemini_free import generation_config,MODEL


def frame(t,reasons):return {'source_seconds':t,'sha256':str(t),'sampling_reasons':reasons}


def test_compaction_preserves_every_cut_motion_and_identity_witness():
    frames=[frame(0,['opening']),frame(.5,['static-coverage'])]
    frames += [frame(i+1,[reason]) for i,reason in enumerate(sorted(MANDATORY))]
    frames += [frame(30,['static-coverage']),frame(31,['ending'])]
    details={'frames':frames};old=copy.deepcopy(details)
    result,report=select_frames(details,'evidence-preserving')
    assert all(f in result['frames'] for f in frames if set(f['sampling_reasons'])&MANDATORY)
    assert frames[1] not in result['frames'] and frames[-2] in result['frames']
    assert report['removed'][0]['sha256']=='0.5'
    assert details==old and report['identity_verified'] is False
    assert select_frames(details,'baseline')[0]['frames']==frames


def test_unknown_reason_or_missing_sampling_evidence_is_not_dropped():
    frames=[frame(0,[]),frame(.1,['new-detector-witness']),frame(.2,[]),frame(.3,['ending'])]
    assert select_frames({'frames':frames},'evidence-preserving')[0]['frames']==frames


def test_local_estimates_label_not_actual_and_preserve_baseline():
    details={'frames':[frame(0,['opening']),frame(.5,['static-coverage']),frame(1,['ending'])]}
    c=generation_config(MODEL,8192)
    baseline=estimate(details,{},c);compact=estimate(details,{},c,'evidence-preserving')
    assert baseline['selected_count']==3 and compact['selected_count']==2
    assert baseline['estimated_total_reservation_tokens']-compact['estimated_total_reservation_tokens']==1600
    assert 'not provider' in compact['token_estimate_kind']
