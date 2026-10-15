"""Pixel-bound inspection carry-over and a persistent two-correction cap."""
import hashlib,json
from pathlib import Path
from .render import file_hash
from .youtube_transcript import atomic_json

def pixel_hash(path):
    from PIL import Image
    with Image.open(path) as im:
        im=im.convert('RGB');return hashlib.sha256(str(im.size).encode()+im.tobytes()).hexdigest()

def inspection_plan(root,phase,pages,flagged=()):
    ledger=Path(root)/'inspection-ledger.json'
    old=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
    records=old.get(phase,{})
    hashes={str(Path(p).resolve()):pixel_hash(p) for p in pages}
    inspected=set(records.values());flags=set(str(Path(p).resolve()) for p in flagged)
    required=[p for p,h in hashes.items() if h not in inspected or p in flags]
    return {'pixel_hashes':hashes,'required_pages':required,'carried_pages':[p for p in hashes if p not in required], 'flagged_pages':list(flags)}

def record_inspection(root,phase,pages):
    path=Path(root)/'inspection-ledger.json';data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    data.setdefault(phase,{}).update({str(Path(p).resolve()):pixel_hash(p) for p in pages})
    atomic_json(path,data);return data

def spec_hash(spec):return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()


def single_pass(job):
    return job.get('review_mode')=='single-pass'


def choose_policy(job,spec,checks):
    """Conservative source-scoped review; narration alone never removes identity review."""
    tracking=spec.get('tracking',{})
    if single_pass(job):
        return {'policy':'single-pass','reason':'User requested one compact pre-render visual pass, accepting minor visual defects without correction/review loops.',
            'full_first_pass':False,'pre_render_zero_flags':bool(checks.get('passed')),
            'baseline_required':True,'later_rounds':'none; explicit user revision only','correction_cap':0,
            'spec_sha256':spec_hash(spec),'source_sha256':job.get('source_sha256'),
            'final_review':'No post-render screenshot inspection. Technical checks and exact-preview publication approval retained.'}
    evidence=spec.get('candidate',{}).get('passage_evidence') or job.get('original_candidate',{}).get('passage_evidence',{})
    classification=job.get('passage_classification',{})
    kind=evidence.get('classification') or classification.get('classification')
    original=job.get('original_candidate',{}).get('passage_evidence',{})
    identity=(any(e.get('animated') is True or e.get('screen_identity_matters') is True
                  or (e.get('multi_character') is True and e.get('screen_identity_matters') is not False)
                  for e in (evidence,original))
              or classification.get('careful_identity_review_required') is True
              or kind in ('careful character tracking','multi-speaker dialogue','animated/multi-character'))
    motion=checks.get('motion_check',{});safety=checks.get('crop_safety',{})
    flags=bool(not checks.get('passed') or safety.get('passed') is not True or not motion.get('proxy_sha256')
               or checks.get('boundary_flags') or checks.get('boundary_flashes')
               or checks.get('suggested_snaps') or motion.get('unavailable') or motion.get('flagged_scenes')
               or motion.get('flagged_source_seconds') or tracking.get('flagged_output_seconds')
               or safety.get('violations') or safety.get('action_warnings')
               or classification.get('eligible') is False or evidence.get('identity_confident') is False
               or classification.get('editorial_warnings') or tracking.get('editorial_warnings'))
    stable=(kind in ('single/dominant-presenter','single-narrator-with-stable-framing','single-narrator')
            and tracking.get('stable_framing') is True and bool(tracking.get('stable_framing_evidence'))
            and tracking.get('confirmed') is True and tracking.get('unresolved') is False
            and not classification.get('requires_stable_context')
            and job.get('crop_strategy',classification.get('crop_strategy')) in ('fixed','face-tracked'))
    reduced=stable and evidence.get('animated') is False and not identity and not flags
    reason=('Source-reviewed stable presenter/narrator; crop, motion and boundary checks passed with zero flags.' if reduced
            else 'Animated/multi-character or dialogue identity requires full first-pass scene inspection.' if identity
            else 'Flags, uncertain identity, or missing stable-framing evidence require full first-pass scene inspection.')
    return {'policy':'stable-baseline-exceptions' if reduced else 'identity-full-first-pass' if identity else 'full-first-pass',
            'reason':reason,'classification':kind,'full_first_pass':not reduced,'pre_render_zero_flags':not flags,
            'baseline_required':True,'later_rounds':'changed-or-flagged-pages-only','correction_cap':2,
            'spec_sha256':spec_hash(spec),'source_sha256':job.get('source_sha256'),
            'final_review':'opening, ending, CTA join, required scene cuts and flagged frames; exact-preview approval remains mandatory'}


def save_policy(root,job,spec,checks):
    policy=choose_policy(job,spec,checks)
    atomic_json(Path(root)/'review-policy.json',policy)
    return policy

def register_round(root,spec,cap=2):
    path=Path(root)/'correction-rounds.json';digest=spec_hash(spec)
    old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'versions':[]}
    if digest not in old['versions']:
        if len(old['versions'])>=cap+1:
            raise ValueError('Two correction rounds exhausted. Stop and show the remaining issue; no additional correction render.')
        old['versions'].append(digest);atomic_json(path,old)
    return {'correction_round':old['versions'].index(digest),'maximum':cap}
