"""One-decision caption coverage policy. Never fetch, transcribe or repair speech."""
import math
import re
from pathlib import Path
from .youtube_transcript import atomic_json


def require_no_speech_retry(job):
    if job.get('fast'):
        raise ValueError('Fast mode never rechecks or aligns speech. Reuse saved verified words and skip uncertain words; only changed passage bounds authorize new verification.')


def token(text):
    return ''.join(re.findall(r'\w+',text.casefold().replace('’',"'")))


def filter_words(words, candidate, cues=(), *, confidence_threshold=.8, disagreement_threshold=None, skip_warning_fraction=.15,
                 source_offset=0., source_sha256=None):
    disagreement_threshold=confidence_threshold if disagreement_threshold is None else disagreement_threshold
    if not 0<=confidence_threshold<=disagreement_threshold<=1 or not 0<=skip_warning_fraction<=1:
        raise ValueError('Fast caption thresholds must be fractions between zero and one.')
    selected=[w for w in words if candidate['start']<=w['start'] and w['end']<=candidate['end']]
    kept=[];skipped=[]
    for word in selected:
        confidence=word.get('confidence',0)
        text=word.get('text','').strip()
        original_start=word.get('original_source_start',word['start']+source_offset)
        original_end=word.get('original_source_end',word['end']+source_offset)
        matches=[cue for cue in cues if cue['start']<original_end+.6 and cue.get('end',cue['start']+cue.get('duration',0))>original_start-.6]
        corroborated=any(token(text) in {token(t) for t in re.findall(r"[\w’'$-]+",c['text'])} for c in matches)
        disagreement=bool(matches) and not corroborated
        threshold=disagreement_threshold if disagreement else confidence_threshold
        timing_flag=(word['end']<=word['start'] or word['end']-word['start']>1.5 or word.get('timing_needs_review',False))
        valid=(isinstance(confidence,(float,int)) and math.isfinite(confidence) and confidence>=threshold
               and not timing_flag and bool(re.search(r'\w',text)))
        if valid:
            kept.append({**word,'fast_verified':True})
            continue
        reason_code='timing_flag' if timing_flag else 'caption_asr_disagreement' if disagreement else 'low_asr_confidence'
        skipped.append({'word_id':word['id'],'source_start':original_start,'source_end':original_end,
                        'local_start':word['start'],'local_end':word['end'],'asr_word':text,
                        'asr_confidence':confidence,'original_caption_text':' '.join(c['text'] for c in matches) or None,
                        'reason_code':reason_code,'required_confidence':threshold,'caption_corroborated':corroborated,
                        'caption_asr_disagreement':disagreement,'timing_flag':bool(timing_flag),
                        'original_caption_timing':'cue-level; original uploaded captions have no verified per-word times',
                        'reason':reason_code+'; saved local ASR does not clear this rule. Uploaded wording is never substituted.'})
    fraction=len(skipped)/len(selected) if selected else 1.
    report={'policy':'fast-skip-once-v2','source_sha256':source_sha256,'passage_bounds':candidate,
            'confidence_threshold':confidence_threshold,'skip_warning_fraction':skip_warning_fraction,
            'disagreement_threshold':disagreement_threshold,
            'reason_counts':{reason:sum(w['reason_code']==reason for w in skipped) for reason in ('low_asr_confidence','caption_asr_disagreement','timing_flag')},
            'corroboration_note':'Lexical match against nearby native uploaded cues with 600ms tolerance is supporting text evidence, not per-word alignment or proof of correctness. Output wording/IDs/intervals still come solely from saved local ASR.',
            'total_asr_words':len(selected),'verified_words':len(kept),'skipped_count':len(skipped),
            'skipped_fraction':fraction,'skipped_percentage':fraction*100,
            'caption_coverage_low':fraction>skip_warning_fraction,'skipped_words':skipped,
            'denominator':'Selected local-ASR word records; cue-only words have no verified interval and are never rendered.',
            'caption_events_only':True,'speech_retries':0,'alignment_passes':0}
    return kept,report


def apply_policy(job,spec,root,settings):
    import json
    root=Path(root)
    evidence=json.loads((root/'verified-passages.json').read_text(encoding='utf-8'))
    a,b=spec['candidate']['start'],spec['candidate']['end']
    passage=next(p for p in evidence['passages'] if p['range'][0]<=a<b<=p['range'][1])
    parent=root.parent/job.get('source_job_id',job['id'])/'transcript.json'
    transcript=json.loads(parent.read_text(encoding='utf-8')) if parent.is_file() else {}
    partial=parent.with_name('partial-uploaded-captions.json')
    # Automatic/base drafts are selection-only, never lexical corroboration.
    cues=[] if transcript.get('selection_only') else transcript.get('cues',[])
    if not cues and not transcript.get('selection_only') and partial.is_file():cues=json.loads(partial.read_text(encoding='utf-8')).get('cues',[])
    kept,report=filter_words(passage['words'],{'start':a,'end':b},cues,
        confidence_threshold=settings.fast_word_confidence_threshold,
        disagreement_threshold=getattr(settings,'fast_disagreement_confidence_threshold',settings.fast_word_confidence_threshold),
        skip_warning_fraction=settings.fast_caption_skip_warning_fraction,
        source_offset=job.get('source_time_offset') or 0.,source_sha256=evidence['source_sha256'])
    if transcript.get('caption_kind')=='auto-generated-selection-only':
        # Keep draft text visible for auditing, without treating it as corroboration.
        for word in report['skipped_words']:
            matches=[c for c in transcript.get('cues',[]) if c['start']<word['source_end']+.6 and c['end']>word['source_start']-.6]
            word['original_caption_text']=' '.join(c['text'] for c in matches) or None
            word['original_caption_timing']='Auto-caption cue only; unverified selection draft, not lexical corroboration or word timing.'
    # Roman text may transliterate the selected ASR, but its IDs/times come only
    # from saved evidence. English always uses local ASR rather than cue wording.
    supplied={w['id']:w for w in spec.get('words',[])}
    english=(transcript.get('language') or '').split('-')[0]=='en'
    words=[]
    for word in kept:
        roman=word['text'] if english else supplied.get(word['id'],{}).get('roman')
        if not roman:raise ValueError('Supply Roman transliteration of the confident local-ASR words.')
        words.append({**word,'roman':roman})
    atomic_json(root/'skipped-words.json',report)
    return {**spec,'words':words},report
