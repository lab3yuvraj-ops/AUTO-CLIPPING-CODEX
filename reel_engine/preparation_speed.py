"""Measured CPU preparation policies; no editorial decisions or publication."""
import difflib
import os
from .fast_captions import token,filter_words

def diarization_needed(evidence):
    return (evidence.get('classification')=='multi-speaker dialogue'
            and evidence.get('single_narrator') is not True
            and evidence.get('identity_confident') is True
            and evidence.get('screen_identity_mappable',True) is True)

def cpu_budget(cores=None,profile=None):
    cores=cores or os.cpu_count() or 1
    measured=bool(profile and profile.get('logical_cores')==cores and profile.get('parallel_seconds',float('inf'))<profile.get('sequential_seconds',0))
    workers=2 if cores>=4 and measured else 1
    return {'workers':workers,'threads':max(1,min(12,cores//workers)),
            'cores':cores,'parallel_measured_beneficial':measured}

def beam_agreement(reference,candidate,cues=()):
    a=[token(w['text']) for w in reference];b=[token(w['text']) for w in candidate]
    # Edit distance rather than set overlap: deletions/reordering count.
    previous=list(range(len(b)+1))
    for i,x in enumerate(a,1):
        current=[i]
        for j,y in enumerate(b,1):current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(x!=y)))
        previous=current
    agreement=max(0,1-previous[-1]/max(1,len(a)))
    def coverage(words):
        _,r=filter_words(words,{'start':0,'end':float('inf')},cues,confidence_threshold=.6,disagreement_threshold=.8)
        return r['skipped_percentage']
    before,after=coverage(reference),coverage(candidate)
    return {'reference_words':len(a),'candidate_words':len(b),'token_edit_distance':previous[-1],
            'word_agreement_percentage':agreement*100,'beam5_skip_percentage':before,
            'beam1_skip_percentage':after,'extra_skipped_percentage_points':after-before,
            'eligible_for_default':agreement>=.98 and after-before<=2,
            'note':'Agreement with saved beam-5 ASR, not a ground-truth semantic accuracy measurement.'}
