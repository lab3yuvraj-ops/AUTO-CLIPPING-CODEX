"""Transcript selection before any video transfer; audio is never render footage."""
import json
import uuid
import time
from pathlib import Path
from . import youtube
from .config import settings
from .fast_download import _check_info
from .render import probe, file_hash
from .selection_draft import fetch_selection_captions, transcribe_selection_draft
from .youtube_transcript import atomic_json
from .timing import stage, mark


def download_audio(info, root):
    """Complete audio-only reference for ASR and source/section anchor checks."""
    _check_info(info)
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    receipt=root/'audio-reference.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        if saved['video_id']==info['id'] and file_hash(saved['source'])==saved['source_sha256']:
            return {**saved,'cached':True}
        raise ValueError('Audio reference changed; preserve it and use a fresh job.')
    youtube.ytdlp([*youtube.transfer_options(root),'-f','bestaudio','--retries','0',
        '--fragment-retries','0','--extractor-retries','0','--continue','-o',str(root/'audio.%(ext)s')],
        timeout=900,info=info,progress_root=root)
    files=[p for p in root.glob('audio.*') if p.suffix in ('.m4a','.webm','.ogg','.opus','.mp3','.mkv')]
    if len(files)!=1:raise ValueError('Audio-only transfer did not produce one accepted file.')
    data=probe(files[0]);duration=float(data['format']['duration'])
    if any(s.get('codec_type')=='video' for s in data['streams']) or not any(s.get('codec_type')=='audio' for s in data['streams']) or abs(duration-float(info['duration']))>2:
        raise ValueError('Audio reference failed stream/duration validation.')
    result={'source':str(files[0].resolve()),'source_sha256':file_hash(files[0]),'duration':duration,
        'video_id':info['id'],'kind':'audio-reference','render_eligible':False,'cached':False}
    atomic_json(receipt,result);return result


def analyze(state,url,clips,*,fresh=False,fresh_captions=False,fast=False):
    if not isinstance(clips,int) or isinstance(clips,bool) or clips<1:raise ValueError('Clip count must be positive.')
    if settings.local_device!='cpu' or settings.local_compute_type!='int8' or settings.whisper_model!='small':
        raise ValueError('Use the existing Whisper small CPU/int8 configuration for selected-word verification.')
    state=Path(state);video=youtube.video_id(url)
    ident=video+'-transcript'+('-'+uuid.uuid4().hex[:8] if fresh else '')
    root=state/'jobs'/ident;root.mkdir(parents=True,exist_ok=True);path=root/'job.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('transcript') and Path(old['transcript']).exists():
            return {**old,'preparation_reused':True}
        raise ValueError('Incomplete transcript job exists. Resume its saved work or use --fresh.')
    run=uuid.uuid4().hex
    job={'id':ident,'video_id':video,'created':time.time(),'requested_clips':clips,'run_id':run,
        'fast':fast,'careful_sections':not fast,'transcript_first':True,'benchmark_fresh':fresh,
        'review_mode':'single-pass' if settings.single_pass_review else 'careful',
        'status':'Retrieving selection transcript','config':{'auto_publish':False}}
    atomic_json(path,job);mark(state,ident,'workflow','start',run_id=run)
    try:
        with stage(state,ident,'metadata',run_id=run):
            info=json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',url]))
            _check_info(info)
            if float(info['duration'])>settings.max_source_seconds:raise ValueError('Source exceeds duration limit.')
        job['metadata']={k:info.get(k) for k in ('id','title','duration','channel_id','upload_date','width','height','fps','language')}
        job['highest_height']=max((f.get('height') or 0 for f in info.get('formats',[]) if f.get('vcodec') not in (None,'none')),default=0)
        try:
            with stage(state,ident,'caption_draft',run_id=run) as interval:
                data=fetch_selection_captions(video,root/'caption-fetch',float(info['duration']),info,
                    fresh_captions=fresh_captions,max_attempts=1)
                interval['cached']=bool(data.get('caption_cached'))
            route={'route':'captions','kind':data.get('caption_kind'),'cached':bool(data.get('caption_cached'))}
        except Exception as exc:
            reason=getattr(exc,'diagnostic',{'message':str(exc)})
            with stage(state,ident,'audio_only_download',run_id=run) as interval:
                audio=download_audio(info,root/'audio-reference');interval['cached']=audio['cached']
            job['audio_reference']=audio
            with stage(state,ident,'selection_draft_asr',run_id=run) as interval:
                result=transcribe_selection_draft(audio['source'],root/'selection-asr',info.get('language'))
                interval['cached']=bool(result['transcription_timings'].get('checkpoint_reused'))
                data=json.loads(Path(result['transcript']).read_text(encoding='utf-8'))
            route={'route':'local audio-only ASR','reason':reason,'cached':interval['cached']}
        atomic_json(root/'transcript.json',data);atomic_json(root/'transcript-route.json',route)
        job.update(transcript=str((root/'transcript.json').resolve()),transcript_route=route,
            status='Transcript ready; select moments before downloading video',
            download_policy={'strategy':'selected-sections','full_video_download':False,
                'full_fallback':False,'padding_seconds':3},
            next='Read the transcript once, save candidates, then run fast-prepare JOB --selection SELECTION.json. Review selected footage once; do not call fast-details/fast-gate first.')
        atomic_json(path,job);return job
    except Exception as exc:
        job.update(status='Transcript preparation failed',error=str(exc));atomic_json(path,job)
        mark(state,ident,'workflow','end',run_id=run,outcome='failed');raise


def prepare(state,job,selection_path):
    """Reuse the existing verified-section engine with an audio-only reference.

    Visual identity is deliberately undecided until the selected footage exists.
    No audio label establishes a crop target. The single visual pass happens on
    the child clips, after speech verification and before rendering.
    """
    from .fast import prepare_selected
    root=Path(state)/'jobs'/job['id'];run=job['run_id']
    if not job.get('audio_reference'):
        with stage(state,job['id'],'audio_reference_metadata',run_id=run):
            info=json.loads(youtube.ytdlp(['--dump-single-json','--skip-download',f"https://www.youtube.com/watch?v={job['video_id']}"]))
        with stage(state,job['id'],'audio_only_download',run_id=run):
            job['audio_reference']=download_audio(info,root/'audio-reference')
        atomic_json(root/'job.json',job)
    return prepare_selected(state,job,selection_path)
