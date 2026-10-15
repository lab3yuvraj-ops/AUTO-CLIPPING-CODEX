"""Replay archived camera values with independently reviewed full subject bounds.

Requires private source/history. Does not render, inspect images or approve pages.
"""
import copy,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reel import prepare_edit
from reel_engine.render import file_hash
from reel_engine.preflight import preflight,crop_review_flags,choose_word_boundary
from reel_engine.review import make_review
from reel_engine.review_policy import pixel_hash
from reel_engine.youtube_transcript import atomic_json

def main():
    original=Path('workflow/jobs/-ZjLRVNAFKk');prior=original/'review-exception-replay';out=original/'review-check-v2';out.mkdir(exist_ok=True)
    job=json.loads((original/'job.json').read_text(encoding='utf-8'))
    # Manually measured from four actual source frames inspected in this turn.
    # Rounded outward to contain hair, torso, arms/hands, source-visible bottom.
    pixels=[(452.5,[585,160,515,920]),(455.5,[740,130,735,950]),(456.8,[670,130,825,950]),(457.5,[650,125,985,955])]
    anchors=[]
    for stamp,box in pixels:
        image=prior/'full-subject-audit'/f'source-{stamp}.png'
        anchors.append({'t':stamp,'box':[box[0]/1920,box[1]/1080,box[2]/1920,box[3]/1080],
            'reviewed_source_frame':str(image.resolve()),'frame_sha256':file_hash(image),'reviewed_by':'Codex',
            'evidence':'Actual source image inspected: full visible Dale including hair, torso and both arms/hands. Manual outward-rounded bounds, not inferred from crop centre.'})
    atomic_json(out/'scene5-subject-bounds.json',{'source_sha256':file_hash(job['source']),'source_size':[1920,1080],'anchors':anchors,'images_actually_inspected':4,'limitation':'Four reviewed source anchors with interpolated bounds; not perfect per-frame automatic segmentation.'})
    rows=[]
    for n in (1,2):
        base=json.loads((prior/f'clip{n}'/'pre-correction-spec.json').read_text(encoding='utf-8'))
        corrected=json.loads(Path(f'workflow/jobs/-ZjLRVNAFKk-clip{n}/spec.json').read_text(encoding='utf-8'))
        for spec in (base,corrected):
            for i,target in enumerate(spec['tracking']['visual_targets']):
                reference=base['tracking']['visual_targets'][i]
                target['scene_start']=reference['start'];target['scene_end']=reference['end']
            if n==1:
                target=spec['tracking']['visual_targets'][4]
                target['camera_center_keyframes']=[{'t':p['t'],'center':p['box'][0]+p['box'][2]/2} for p in target['box_keyframes']]
                full=[{'t':a['t'],'box':a['box']} for a in anchors]
                target.update(box=full[0]['box'],box_keyframes=full,safety_box_keyframes=copy.deepcopy(full),full_subject_bounds_confirmed=True,
                    evidence='Four actual full-subject source frames reviewed; see scene5-subject-bounds.json. Camera centres retained independently.')
        if n==1:
            corrected=choose_word_boundary(corrected,out,'start-next-word')
            atomic_json(Path('workflow/jobs/-ZjLRVNAFKk-clip1/spec.boundary-revision.json'),corrected)
        pair={}
        for label,spec in (('before',base),('after',corrected)):
            root=out/f'clip{n}'/label;root.mkdir(parents=True,exist_ok=True);atomic_json(root/'spec.json',spec)
            edit,tracking=prepare_edit(job,spec,root);checks=preflight(job['source'],spec,edit,tracking,root)
            tracking['flagged_output_seconds']=crop_review_flags(checks)
            review=make_review(job['source'],edit,tracking,root)
            pair[label]={'sheets':len(review['pages']),'samples':review['sample_count'],'page_pixels':{p:pixel_hash(p) for p in review['pages']},'checks':checks}
        before=set(pair['before']['page_pixels'].values())
        changed=[p for p,h in pair['after']['page_pixels'].items() if h not in before]
        rows.append({'clip':n,'first_pass_sheets':pair['before']['sheets'],'first_pass_samples':pair['before']['samples'],'correction_sheets_changed_or_flagged':len(set(changed)|set(review.get('flagged_pages',[]))),'pixel_changed_sheets':len(changed),'unchanged_sheets':pair['after']['sheets']-len(changed),'after_samples':pair['after']['samples'],'before_checks':pair['before']['checks'],'after_checks':pair['after']['checks'],'changed_pages':changed})
    atomic_json(out/'replay-report.json',{'clips':rows,'source_images_actually_viewed':4,'review_sheets_actually_viewed':0,'counterfactual_counts_only':True,'rendered':False,'published':False,'note':'No inspection hashes were manufactured. Counts assume a genuinely inspected first pass. Clip 1 word-removal may legitimately change caption phrase grouping on later pages. Existing final MP4s do not represent the new boundary revision.'})
    print(json.dumps([{k:v for k,v in r.items() if k not in ('before_checks','after_checks','changed_pages')} for r in rows],indent=2))
if __name__=='__main__':main()
