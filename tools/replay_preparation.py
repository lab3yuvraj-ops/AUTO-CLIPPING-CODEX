"""Measured preparation replay; saved inputs are explicitly cached, no render."""
import sys,json,time,concurrent.futures,shutil,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reel_engine.youtube_transcript import atomic_json
from reel_engine.render import run,probe,file_hash
from reel_engine.detail import make_details
from reel_engine.fast_download import confirm_section_audio
from reel_engine.speech_worker import request
from reel_engine.timing import stage,mark,report

def main():
    state=Path('workflow');out=state/'benchmarks'/'preparation-20261015';results=[]
    for ident in ('krsBRQbOPQ4-fast-1527c559','-ZjLRVNAFKk'):
        original=state/'jobs'/ident;job=json.loads((original/'job.json').read_text(encoding='utf-8'))
        root=out/(ident+'-'+uuid.uuid4().hex[:6]);root.mkdir(parents=True)
        runid=uuid.uuid4().hex;timingjob=ident+'-prep-replay';mark(state,timingjob,'workflow','start',run_id=runid)
        saved=json.loads((original/'verified-passages.json').read_text(encoding='utf-8'));ranges=[p['range'] for p in saved['passages']]
        shutil.copyfile(original/'transcript.json',root/'transcript.json')
        if job.get('proxy'):
            proxy=job['proxy']['source'];proxy_cached=True;proxy_seconds=None
        elif '--reuse-proxy' in sys.argv and list(out.glob(ident+'-*/proxy.mkv')):
            proxy=next(out.glob(ident+'-*/proxy.mkv'));proxy_cached=True;proxy_seconds=None
        else:
            proxy=root/'proxy.mkv';start=time.perf_counter()
            with stage(state,timingjob,'proxy_encode_from_cached_source',run_id=runid):
                run(['ffmpeg','-v','error','-y','-hwaccel','none','-i',job['source'],'-vf','scale=-2:480','-c:v','libx264','-preset','ultrafast','-crf','28','-c:a','copy',str(proxy)],timeout=600)
            proxy_seconds=time.perf_counter()-start;proxy_cached=False
        # Final media is cached, not a simulated section download.
        full_fallback=original/'full-fallback'/'source.mkv'
        final=str(full_fallback) if full_fallback.exists() else job['source'];start=time.perf_counter()
        def verify():
            with stage(state,timingjob,'selected_speech_verification',run_id=runid):
                return request(root,runid,'verify',{'source':str(proxy),'root':str(root),'ranges':ranges,'skip_diarization':True},timing={'state':str(state),'job':timingjob})
        def dense():
            with stage(state,timingjob,'dense_frame_extraction',run_id=runid):return make_details(proxy,root,ranges)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            vf=pool.submit(verify);df=pool.submit(dense);verification=vf.result();details=df.result()
        passages=json.loads(Path(verification['verified_passages']).read_text(encoding='utf-8'))['passages'];anchors=[]
        for index,p in enumerate(passages,1):
            with stage(state,timingjob,f'anchor_offset_{index}',run_id=runid):
                check=confirm_section_audio(proxy,final,[0,float(probe(final)['format']['duration'])],p['words'])
            anchors.append(check)
            if not check['offset_verified']:
                fallback=root/f'final-audio-{index}';fallback.mkdir();shutil.copyfile(root/'transcript.json',fallback/'transcript.json')
                with stage(state,timingjob,f'anchor_fallback_verification_{index}',run_id=runid):
                    request(root,runid,'verify',{'source':final,'root':str(fallback),'ranges':[p['range']],'skip_diarization':True},timing={'state':str(state),'job':timingjob})
        request(root,runid,'stop');mark(state,timingjob,'workflow','end',run_id=runid)
        measured=report(state,timingjob,runid);atomic_json(root/'timing-report.json',measured)
        skip_reason='Saved multi-speaker passage evidence has identity_confident=false: audio-to-person mappings are unverified; stable context crop and identity warnings remain.' if job.get('fast') else 'Careful source uses narration/character targets without established voice-to-screen associations; skip audio diarization, retain full visual identity review.'
        result={'job':ident,'range_basis':'Saved verified passages, unchanged (not tighter than saved reference for this comparison).','ranges':ranges,'proxy_cached':proxy_cached,'proxy_encode_seconds':proxy_seconds,'proxy_height':next(s['height'] for s in probe(proxy)['streams'] if s['codec_type']=='video'),'verification':verification,'diarization_seconds':0,'diarization_skip_evidence':skip_reason,'dense_seconds':details['seconds_this_run'],'anchors':anchors,'timing_report':measured,'preparation_after_proxy_wall_seconds':time.perf_counter()-start,'input_cache':'Metadata, caption draft, selection, final/full media and model files reused; not a fresh run from YouTube. Proxy is identified separately. ASR and dense extraction are fresh.'}
        atomic_json(root/'replay.json',result);results.append(result);print(json.dumps({'job':ident,'wall_seconds':measured['wall_seconds'],'dense_seconds':details['seconds_this_run'],'anchors':[a['offset_verified'] for a in anchors]}),flush=True)
    atomic_json(out/'preparation-replay.json',{'results':results,'fresh_end_to_end_target_proven':False,'no_render_or_publish':True})
if __name__=='__main__':main()
