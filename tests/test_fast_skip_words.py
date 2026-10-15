import json
import pytest
from types import SimpleNamespace
from reel_engine.fast_captions import filter_words,apply_policy,require_no_speech_retry
from reel_engine.captions import make_ass


def word(i,text,confidence):
    return dict(id=i,text=text,start=i,end=i+.4,confidence=confidence,speaker='S',roman=text)


def test_low_confidence_disagreement_never_replaced():
    words,report=filter_words([word(0,'no',.1),word(1,'Yes',.95)],dict(start=0,end=2),[dict(start=0,end=1,text='Mom')])
    assert [w['text'] for w in words]==['Yes']
    assert report['skipped_words'][0]['original_caption_text']=='Mom'
    assert report['skipped_words'][0]['asr_word']=='no'


def test_high_confidence_disagreement_uses_asr():
    kept,report=filter_words([word(0,'served',.91)],dict(start=0,end=1),[dict(start=0,end=1,text='serve')])
    assert kept[0]['text']=='served' and report['skipped_count']==0


def test_group_only_remaining_words_without_empty_events(tmp_path):
    kept,_=filter_words([word(0,'a',.99),word(1,'bad',.1),word(2,'b',.99),word(3,'c',.99),word(4,'d',.99)],dict(start=0,end=5))
    events=make_ass(kept,tmp_path/'captions.ass')
    assert {e['display_text'] for e in events}=={'A B','C D'}
    assert all(e['display_text'] and 1 not in e['active_ids'] for e in events)


def test_all_skipped_renders_empty_caption_events(tmp_path):
    kept,report=filter_words([word(0,'bad',.1)],dict(start=0,end=1))
    assert kept==[] and report['caption_coverage_low']
    assert make_ass(kept,tmp_path/'captions.ass')==[]


def test_policy_writes_coverage_and_reuses_saved_evidence(tmp_path):
    root=tmp_path/'clip';root.mkdir()
    evidence=dict(source_sha256='hash',passages=[dict(range=[0,2],words=[word(0,'no',.1),word(1,'served',.99)])])
    (root/'verified-passages.json').write_text(json.dumps(evidence))
    (tmp_path/'parent').mkdir();(tmp_path/'parent'/'transcript.json').write_text(json.dumps(dict(language='en',cues=[dict(start=0,end=1,text='Mom')])) )
    spec=dict(candidate=dict(start=0,end=2),words=[{**word(1,'served',.99),'roman':'serve'}])
    settings=SimpleNamespace(fast_word_confidence_threshold=.8,fast_caption_skip_warning_fraction=.15)
    result,report=apply_policy(dict(id='clip',source_job_id='parent'),spec,root,settings)
    assert result['words'][0]['roman']=='served'
    assert report['caption_coverage_low'] and report['skipped_percentage']==50
    assert json.loads((root/'skipped-words.json').read_text())['skipped_words'][0]['source_start']==0
    assert json.loads((root/'verified-passages.json').read_text())==evidence


def test_fast_disallows_retry_normal_keeps_behavior():
    with pytest.raises(ValueError,match='never rechecks or aligns'):require_no_speech_retry({'fast':True})
    require_no_speech_retry({'fast':False})


def test_normal_phrase_boundaries_unchanged(tmp_path):
    events=make_ass([word(0,'a',.99),word(2,'b',.99)],tmp_path/'normal.ass')
    assert {e['display_text'] for e in events}=={'A','B'}


def test_configurable_skip_threshold():
    kept,report=filter_words([word(0,'a',.79),word(1,'b',.81)],dict(start=0,end=2),confidence_threshold=.7,skip_warning_fraction=.5)
    assert len(kept)==2 and not report['caption_coverage_low']


def test_corroborated_threshold_recovers_asr_but_conflict_remains_skipped():
    kept,report=filter_words([word(0,'Ludwig',.69),word(1,'sworn',.64)],dict(start=0,end=2),
        [dict(start=0,end=.4,text='Ludwig'),dict(start=1,end=1.4,text='swarmed')],confidence_threshold=.6,disagreement_threshold=.8)
    assert [w['text'] for w in kept]==['Ludwig']
    assert report['reason_counts']==dict(low_asr_confidence=0,caption_asr_disagreement=1,timing_flag=0)
    assert report['skipped_words'][0]['asr_word']=='sworn'


def test_flagged_timing_skips_even_high_confidence():
    w=word(0,'great',.99);w['timing_needs_review']=True
    kept,report=filter_words([w],dict(start=0,end=1))
    assert not kept and report['reason_counts']['timing_flag']==1


def test_partial_cues_are_audit_only_normal_parser_keeps_coverage_gate():
    from reel_engine.youtube_transcript import parse_json3
    body={'language':'en','events':[{'tStartMs':0,'dDurationMs':1000,'segs':[{'utf8':'Mom'}]}]}
    with pytest.raises(ValueError,match='coverage'):parse_json3(body,60)
    draft=parse_json3(body,60,require_coverage=False)
    assert draft['words']==[] and draft['cues'][0]['text']=='Mom'
    kept,report=filter_words([word(0,'no',.1)],dict(start=0,end=1),draft['cues'])
    assert not kept and report['skipped_words'][0]['original_caption_text']=='Mom'


def test_render_completes_with_skips_and_summary(tmp_path,monkeypatch):
    from reel_engine import final_review
    # Caption omission unit: baseline enforcement is exercised in source-review-policy tests.
    monkeypatch.setattr(__import__('reel'),'_pre_render_review_guard',lambda job,*a:job.update(review_policy={'policy':'full-first-pass'}))
    monkeypatch.setattr(final_review,'sample_final',lambda *a:{'cache_reused':False})
    import reel
    from reel_engine import fast_render,outro
    root=tmp_path/'jobs'/'clip_test_fast';root.mkdir(parents=True)
    source=root/'source';source.write_bytes(b'source')
    transcript=root/'transcript.json';transcript.write_text(json.dumps(dict(provider='youtube-captions',language='en')))
    evidence=dict(source_sha256=reel.digest(source),passages=[dict(range=[0,35],words=[word(0,'bad',.1),word(1,'good',.99)])])
    (root/'verified-passages.json').write_text(json.dumps(evidence));(root/'silences.json').write_text('[]')
    job=dict(id='clip_test_fast',fast=True,fast_eligible=True,verification_route='proxy_verified_anchor_matched',source=str(source),source_sha256=reel.digest(source),transcript=str(transcript),passage_classification=dict(requires_stable_context=True))
    (root/'job.json').write_text(json.dumps(job))
    spec=dict(candidate=dict(start=0,end=35),words=[],tracking=dict(context_scenes=[dict(id='one',start=0,end=35,stable_center=.5,evidence='Reviewed live action')]))
    spec_path=root/'spec.json';spec_path.write_text(json.dumps(spec))
    monkeypatch.setattr(reel,'STATE',tmp_path)
    monkeypatch.setattr(reel,'probe',lambda _:dict(format=dict(duration=35)))
    monkeypatch.setattr(outro,'resolve_outro',lambda *a:None)
    def render(source,edit,tracking,path,config,**kwargs):
        assert [w['text'] for w in edit['words']]==['good']
        assert 'caption coverage low' in tracking['editorial_warnings']
        path.write_bytes(b'render');return dict(caption_events=[],timings={})
    monkeypatch.setattr(fast_render,'fast_render_clip',render)
    monkeypatch.setattr(reel,'validate_render',lambda *a,**kw:[dict(status='pass')])
    result=reel.render('clip_test_fast',spec_path)
    assert result['status']=='Needs approval'
    assert result['caption_coverage']['skipped_count']==1
    assert result['caption_coverage']['skipped_words'][0]['asr_word']=='bad'
    assert (root/'skipped-words.json').is_file()

