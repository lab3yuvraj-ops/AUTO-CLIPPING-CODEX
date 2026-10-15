"""Passage-scoped editorial classification, never voice-to-screen inference."""
def classify_passage(evidence,source_hash):
    if not isinstance(evidence,dict) or evidence.get('reviewed_by')!='Codex' or evidence.get('source_sha256')!=source_hash or not evidence.get('reason'):
        return {'eligible':False,'fallback':'full','reason':'Passage review is missing, unbound or cannot decide.'}
    if evidence.get('animated') is True:
        return {'eligible':False,'fallback':'full','reason':'Animated/cartoon passage needs character identity tracking.'}
    kind=evidence.get('classification')
    if evidence.get('animated') is not False or kind not in ('single/dominant-presenter','multi-speaker dialogue'):
        return {'eligible':False,'fallback':'full','reason':'Passage identity-tracking eligibility cannot be decided.'}
    strategy='speaker-switching' if kind=='multi-speaker dialogue' else evidence.get('chosen_strategy','face-tracked')
    if strategy not in ('fixed','face-tracked','speaker-switching'):
        return {'eligible':False,'fallback':'full','reason':'Passage crop strategy cannot be decided.'}
    warnings=[]
    if evidence.get('identity_confident') is not True or evidence.get('speakers_too_far_apart'):
        warnings.append('Use a reviewed stable context crop; speaker identity or separation needs human review. A dominant-presenter moment may give a cleaner result.')
    from .preparation_speed import diarization_needed
    return {'eligible':True,'classification':kind,'crop_strategy':strategy,'diarization_required':diarization_needed(evidence),'reason':evidence['reason'],'editorial_warnings':warnings,'prefer_alternative':bool(warnings),'requires_stable_context':bool(warnings)}


def classify_selection(selection,source_hash):
    return [{**classify_passage(c.get('passage_evidence'),source_hash),'range':[c['start'],c['end']]} for c in selection['candidates']]


def require_selected_review(root,selection,source_hash):
    import json
    from pathlib import Path
    from .render import file_hash
    report=Path(root)/'selected-details.json'
    if not report.exists():raise ValueError('Run fast-details and inspect selected passage frames before classifying them.')
    details=json.loads(report.read_text(encoding='utf-8'))
    for candidate in selection['candidates']:
        passage=next((p for p in details['passages'] if p['range']==[candidate['start'],candidate['end']] and p['source_sha256']==source_hash),None)
        pages={p['file']:p['sha256'] for p in passage.get('page_files',[])} if passage else {}
        if not pages or candidate.get('passage_evidence',{}).get('reviewed_page_hashes')!=pages or any(not Path(p).exists() or file_hash(p)!=h for p,h in pages.items()):
            raise ValueError('Selected passage classification needs inspected, unchanged source-bound detail pages.')
