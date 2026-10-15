"""Cheap, explicitly unverified selection drafts; never final caption words."""
import hashlib,json,time
from pathlib import Path
from .config import settings
from .youtube_transcript import atomic_json,parse_json3
from . import youtube


def native_auto_language(info):
    native=(info.get('language') or '').split('-')[0]
    tracks=info.get('automatic_captions',{})
    # Never silently pick a translated/dubbed language in a multilingual video.
    key=native+'-orig'
    if native and key in tracks:return key
    if native in tracks and any('tlang=' not in t.get('url','') for t in tracks[native]):return native
    return None


def fetch_selection_captions(ident,root,duration,info,**kwargs):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if info.get('subtitles'):
        from .original_captions import fetch_uploaded_captions,uploaded_language
        from .caption_errors import CaptionFetchError
        try: uploaded_language(info)
        except CaptionFetchError: pass  # Translation-only tracks are not a native draft.
        else: return fetch_uploaded_captions(ident,root,duration,info,**kwargs)
    language=native_auto_language(info)
    if not language:raise ValueError('No uploaded or native auto-generated selection caption track exists.')
    cache=settings.caption_cache_dir/ident/'selection-auto';record=cache/'record.json';payload=cache/'auto.json3'
    receipt=root/'selection-auto-request.json';draft=root/'selection-auto-draft.json'
    if receipt.exists():
        saved=json.loads(receipt.read_text(encoding='utf-8'))
        if saved.get('failure'):raise ValueError(saved['failure'])
        return json.loads(draft.read_text(encoding='utf-8'))
    if not kwargs.get('fresh_captions') and record.exists() and payload.exists():
        meta=json.loads(record.read_text(encoding='utf-8'));raw=payload.read_bytes()
        if meta.get('video_id')==ident and meta.get('language')==language and meta.get('duration')==duration and meta.get('sha256')==hashlib.sha256(raw).hexdigest():
            body=json.loads(raw);body['language']=language;data=parse_json3(body,duration)
            data.update(caption_kind='auto-generated-selection-only',caption_cached=True,video_id=ident,selection_only=True)
            atomic_json(draft,data);atomic_json(receipt,{'cached':True});return data
    try:
        # One endpoint pass, same extractor metadata; no caption endpoint retries.
        youtube.ytdlp(['--skip-download','--write-auto-subs','--no-write-subs','--sub-langs',language,'--sub-format','json3','--retries','0','--extractor-retries','0','-o',str(root/'selection-auto.%(ext)s')],metadata_input=info)
        raw=(root/f'selection-auto.{language}.json3').read_bytes();body=json.loads(raw);body['language']=language
        data=parse_json3(body,duration);data.update(caption_kind='auto-generated-selection-only',caption_cached=False,video_id=ident,selection_only=True)
        cache.mkdir(parents=True,exist_ok=True);payload.write_bytes(raw)
        atomic_json(record,{'video_id':ident,'language':language,'format':'json3','duration':duration,'fetched_at':time.time(),'sha256':hashlib.sha256(raw).hexdigest()})
        atomic_json(draft,data);atomic_json(receipt,{'cached':False});return data
    except Exception as exc:
        from .caption_errors import classify_caption_failure,CaptionFetchError
        diagnostic=classify_caption_failure(str(exc),language=language)
        atomic_json(receipt,{'failure':diagnostic['yt_dlp_message'],'diagnostic':diagnostic})
        # No blocking backoff: preserve Retry-After and recovery time in diagnostics.
        raise CaptionFetchError(diagnostic) from exc


def draft_model(language):
    model=settings.selection_draft_model
    return model+'.en' if (language or '').split('-')[0]=='en' else model


def transcribe_selection_draft(source,root,language=None):
    from faster_whisper import WhisperModel
    from .render import file_hash,run
    root=Path(root);root.mkdir(parents=True,exist_ok=True);started=time.perf_counter();model_name=draft_model(language)
    signature={'source_sha256':file_hash(source),'model':model_name,'beam':1,'device':'cpu','compute':'int8'}
    path=root/'transcript.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf-8'))
        if old.get('draft_signature')==signature:return {'transcript':str(path),'transcription_timings':{'checkpoint_reused':True,'seconds_this_run':time.perf_counter()-started}}
    model_root=settings.local_model_dir/'selection-whisper'
    # First provisioning is explicit in the report; later runs stay offline.
    cached=any(model_root.glob(f'models--Systran--faster-whisper-{model_name}/snapshots/*/model.bin'))
    import os
    os.environ['HF_HUB_OFFLINE']='1' if cached else '0'
    import huggingface_hub.constants
    huggingface_hub.constants.HF_HUB_OFFLINE=cached
    load=time.perf_counter();model=WhisperModel(model_name,device='cpu',compute_type='int8',cpu_threads=min(8,os.cpu_count() or 1),download_root=str(model_root),local_files_only=cached)
    load_seconds=time.perf_counter()-load
    audio=root/'local-audio.wav';run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-ar','16000','-ac','1',str(audio)])
    clock=time.perf_counter();segments,info=model.transcribe(str(audio),language=(language or '').split('-')[0] or None,beam_size=1,word_timestamps=False,vad_filter=True)
    cues=[{'id':i,'start':s.start,'end':s.end,'text':s.text.strip(),'timing_precision':'unverified ASR segment'} for i,s in enumerate(segments)]
    data={'provider':'local-selection-draft','language':info.language,'cues':cues,'words':[],'text':' '.join(c['text'] for c in cues),'selection_only':True,'requires_selected_verification':True,'source_sha256':signature['source_sha256'],'draft_signature':signature}
    data['timings']={'draft_asr_seconds':time.perf_counter()-clock,'model_load_or_provision_seconds':load_seconds,'model_provisioning_cached':cached,'seconds_this_run':time.perf_counter()-started}
    atomic_json(path,data);return {'transcript':str(path),'transcription_timings':data['timings']}
