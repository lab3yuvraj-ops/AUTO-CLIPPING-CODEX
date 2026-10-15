import importlib.util
import json
import math
import os
import hashlib
import time
import httpx
import subprocess
from contextlib import nullcontext
from functools import lru_cache
from pathlib import Path
from .config import settings
from .errors import StageError

_DLL_HANDLES=[]


def ensure_recheck_audio(job,root):
    """Careful and fast section children share final-media-bound recheck audio."""
    from .render import file_hash,run
    from .youtube_transcript import atomic_json
    root=Path(root);source=Path(job['source']);audio=root/'local-audio.wav';receipt=root/'recheck-audio-binding.json'
    source_hash=file_hash(source)
    if source_hash!=job['source_sha256']:raise ValueError('Final source changed before speech recheck.')
    if audio.exists() and receipt.exists():
        old=json.loads(receipt.read_text(encoding='utf8'))
        if old.get('source_sha256')==source_hash and old.get('audio_sha256')==file_hash(audio):return audio
    temporary=root/'recheck-audio.tmp.wav'
    run(['ffmpeg','-v','error','-y','-hwaccel','none','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(temporary)])
    temporary.replace(audio)
    atomic_json(receipt,{'source_sha256':source_hash,'audio_sha256':file_hash(audio),'device':'cpu','sample_rate':16000,'channels':1})
    return audio

@lru_cache(maxsize=2)
def load_whisper(allow_download=False,cpu_threads=0,num_workers=1):
    os.environ['HF_HUB_OFFLINE']='0' if allow_download else '1'
    if settings.local_device=='cuda':
        import torch
        if not torch.cuda.is_available():raise StageError('GPU speech runtime is unavailable; use the saved CPU environment.',False)
        if os.name=='nt':
            libs=Path(torch.__file__).parent/'lib'
            _DLL_HANDLES.append(os.add_dll_directory(str(libs)))
            os.environ['PATH']=str(libs)+os.pathsep+os.environ.get('PATH','')
    from faster_whisper import WhisperModel
    return WhisperModel(settings.whisper_model,device=settings.local_device,compute_type=settings.local_compute_type,
        download_root=str(settings.local_model_dir/'whisper'),local_files_only=not allow_download,cpu_threads=cpu_threads,num_workers=num_workers)


def speech_language(root):
    """Reuse detected source language; never force English speech into Hindi."""
    for name in ('transcript.json','local-asr.json'):
        path=Path(root)/name
        if path.exists():
            language=(json.loads(path.read_text(encoding='utf-8')).get('language') or '').split('-')[0]
            if language and language not in ('original','auto'):return language
    return None


def recheck_local(root,ranges,force=False):
    """Check uncertain passages with one model load; leave full transcript intact."""
    import soundfile
    root=Path(root);audio=root/'local-audio.wav'
    samples,rate=soundfile.read(str(audio),dtype='float32')
    if rate!=16000 or samples.ndim!=1:raise ValueError('Recheck requires the extracted mono 16kHz audio.')
    if any(not math.isfinite(a+b) or not 0<=a<b<=len(samples)/rate for a,b in ranges):raise ValueError('Recheck range is outside the audio.')
    out=root/'rechecks';out.mkdir(exist_ok=True);results=[];model=None
    fingerprint=hashlib.sha256(audio.read_bytes()).hexdigest();language=speech_language(root)
    # Count previous overlapping attempts, even if slightly different boundaries
    # were used. Cache hits remain free; force is an explicit recovery override.
    history=[json.loads(p.read_text(encoding='utf-8')) for p in out.glob('*.json')]
    for a,b in ranges:
        signature=hashlib.sha256(json.dumps([fingerprint,a,b,settings.whisper_model,settings.local_device,settings.local_compute_type,language,5,2]).encode()).hexdigest()
        path=out/(signature+'.json')
        if path.exists():results.append(json.loads(path.read_text(encoding='utf-8')) | {'cache_reused':True});continue
        attempts=sum(h.get('audio_sha256')==fingerprint and h.get('language')==language and
                     min(b,h['range'][1])-max(a,h['range'][0])>=.5*min(b-a,h['range'][1]-h['range'][0]) for h in history)
        if attempts>=2 and not force:
            results.append({'range':[a,b],'status':'needs_human_review','words':[],
                            'reason':'Two overlapping local rechecks already completed. Retain original audio; do not invent captions.',
                            'seconds':0,'cache_reused':False});continue
        if model is None:model=load_whisper()
        started=time.perf_counter()
        segments,_=model.transcribe(samples[round(a*rate):round(b*rate)],language=language,task='transcribe',word_timestamps=True,vad_filter=False,beam_size=5,condition_on_previous_text=False)
        words=[{'start':float(w.start+a),'end':float(w.end+a),'text':w.word.strip(),'confidence':float(w.probability)} for s in segments for w in s.words or [] if w.word.strip()]
        result={'range':[a,b],'words':words,'seconds':time.perf_counter()-started,'model':settings.whisper_model,'device':settings.local_device,'cache_reused':False,'audio_sha256':fingerprint,'language':language}
        temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path);results.append(result);history.append(result)
    return {'rechecks':results,'note':'Alternate ASR evidence; results do not silently replace approved wording.'}


def readiness():
    missing=[name for name in ('faster_whisper','pyannote.audio','torch','soundfile') if not module_available(name)]
    return {'ready':not missing and (bool(settings.hf_token) or Path(settings.diarization_model).exists()),'missing_packages':missing,'model_access_configured':bool(settings.hf_token) or Path(settings.diarization_model).exists(),'provider':'local','device':settings.local_device,'whisper_model':settings.whisper_model}


def module_available(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ModuleNotFoundError,ValueError):
        return False


@lru_cache(maxsize=2)
def load_models(allow_download=False):
    return (load_whisper(True) if allow_download else load_whisper(),load_diarization(allow_download))


@lru_cache(maxsize=2)
def load_diarization(allow_download=False):
    status=readiness()
    if status['missing_packages']:
        raise StageError('Install requirements-local.txt in the worker environment. Missing local speech packages: '+', '.join(status['missing_packages']),False)
    if not status['model_access_configured']:
        raise StageError('Set HF_TOKEN after accepting pyannote Community-1 model terms, or configure DIARIZATION_MODEL to an approved downloaded local model directory.',False)
    if allow_download and settings.diarization_model=='pyannote/speaker-diarization-community-1':
        try:
            with httpx.Client(timeout=30) as client:
                response=client.head('https://huggingface.co/pyannote/speaker-diarization-community-1/resolve/main/config.yaml',headers={'Authorization':'Bearer '+settings.hf_token})
            if response.status_code in (401,403):
                raise StageError(f'Hugging Face refused speaker-model access (HTTP {response.status_code}). Accept Community-1 access conditions on your Hugging Face account and ensure HF_TOKEN has read access to the approved gated repository.',False)
            if response.status_code>=400:
                raise StageError(f'Speaker-model access check returned HTTP {response.status_code}. Try model preparation again after resolving provider access.',False)
        except httpx.TransportError as error:
            raise StageError('Could not verify speaker-model download access. Check HTTPS trust and network connectivity.',False) from error
    os.environ['PYANNOTE_METRICS_ENABLED']='false'
    if settings.hf_token:
        os.environ['HF_TOKEN']=settings.hf_token
    os.environ['HF_HUB_OFFLINE']='0' if allow_download else '1'
    os.environ['HF_HUB_DISABLE_XET']='1'
    os.environ['HF_HUB_DOWNLOAD_TIMEOUT']='120'
    os.environ['HF_HUB_ETAG_TIMEOUT']='30'
    from huggingface_hub import constants
    constants.HF_HUB_OFFLINE=not allow_download
    constants.HF_HUB_DISABLE_XET=True
    from pyannote.audio import Pipeline
    import torch
    if settings.local_device=='cuda' and not torch.cuda.is_available():
        raise StageError('LOCAL_DEVICE=cuda requires a supported NVIDIA GPU and matching CUDA runtime. Use cpu/int8 otherwise.',False)
    settings.local_model_dir.mkdir(parents=True,exist_ok=True)
    try:
        pipeline=Pipeline.from_pretrained(settings.diarization_model,token=settings.hf_token or None,cache_dir=str(settings.local_model_dir/'pyannote'))
        pipeline.to(torch.device(settings.local_device))
    except Exception as error:
        raise StageError('Local speech models could not load. Run reel.py prepare-models --download after accepting model terms and setting HF_TOKEN. Later runs use cached models offline. Check disk space and CPU/CUDA compatibility.',False) from error
    return pipeline


def assign_words(words,turns):
    output=[]
    for word in words:
        start,end=float(word['start']),float(word['end'])
        if not math.isfinite(start) or not math.isfinite(end) or end<=start:
            continue
        scores={}
        for turn in turns:
            overlap=max(0,min(end,turn['end'])-max(start,turn['start']))
            if overlap:
                scores[turn['speaker']]=scores.get(turn['speaker'],0)+overlap
        ranked=sorted(scores.items(),key=lambda item:item[1],reverse=True)
        best=ranked[0] if ranked else ('UNKNOWN',0)
        uncertain=best[1]/(end-start)<.5 or (len(ranked)>1 and ranked[1][1]>.25*(end-start))
        output.append({**word,'id':len(output),'speaker':best[0] if not uncertain else 'UNKNOWN','speaker_uncertain':uncertain,'overlapping_speech':len(ranked)>1,'speaker_coverage':min(1,best[1]/(end-start))})
    return output


def verify_passages(source,root,ranges,skip_diarization=False,timing_hook=None,beam_size=None,worker=None):
    """Batch selected ASR/diarization locally; retain global source times and cache."""
    from .youtube_transcript import atomic_json
    from .render import probe
    import soundfile
    import torch
    beam_size=settings.whisper_beam_size if beam_size is None else beam_size
    if not isinstance(beam_size,int) or isinstance(beam_size,bool) or not 1<=beam_size<=10:raise ValueError('Whisper beam size must be an integer from 1 to 10')
    root=Path(root);duration=float(probe(source)['format']['duration'])
    worker_loaded_before=getattr(worker,'model_load_seconds',0)
    skip_flags=skip_diarization if isinstance(skip_diarization,list) else [skip_diarization]*len(ranges)
    if len(skip_flags)!=len(ranges) or any(not isinstance(flag,bool) for flag in skip_flags):raise ValueError('Each selected passage needs one diarization policy.')
    if not ranges or any(not math.isfinite(a+b) or not 0<=a<b<=duration or b-a>180 for a,b in ranges):
        raise ValueError('Verify finite START:END passages within the source, at most 180 seconds each. Include context around each selected story.')
    h=hashlib.sha256()
    with Path(source).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    fingerprint=h.hexdigest();path=root/'verified-passages.json'
    source_job=root/'job.json'
    if source_job.exists() and json.loads(source_job.read_text(encoding='utf-8')).get('source_sha256')!=fingerprint:
        raise ValueError('Source hash differs from the saved job; restore the original media before verification.')
    evidence=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'source_sha256':fingerprint,'passages':[]}
    if evidence['source_sha256']!=fingerprint:raise ValueError('Source changed; existing verification belongs to different media.')
    full=root/'transcript.json'
    cached=json.loads(full.read_text(encoding='utf-8')) if full.exists() else {}
    results=[];models=None;samples=None;started=time.perf_counter();cache_hits=0
    language=speech_language(root)
    reusable_asr=(cached.get('provider')=='local-asr-draft' and cached.get('source_sha256')==fingerprint
                  and cached.get('models',{}).get('transcription')==settings.whisper_model
                  and cached.get('beam_size')==beam_size)
    parallel_fresh={}
    if worker and worker.workers>1 and not reusable_asr and cached.get('provider')!='local':
        import concurrent.futures
        audio=root/'local-audio.wav'
        if not audio.exists():
            decoded=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(audio)],capture_output=True,timeout=7200)
            if decoded.returncode:raise StageError('Could not extract proxy audio for batched verification.',False)
        samples,rate=soundfile.read(str(audio),dtype='float32')
        if rate!=16000 or samples.ndim!=1:raise ValueError('Verification audio must be mono 16kHz.')
        whisper=worker.whisper()
        def transcribe_one(item):
            index,a,b,signature,checkpoint=item;clock=time.perf_counter()
            with timing_hook(f'selected_words_{index}') if timing_hook else nullcontext():
                segments,_=whisper.transcribe(samples[round(a*rate):round(b*rate)],language=language,task='transcribe',word_timestamps=True,vad_filter=False,beam_size=beam_size,condition_on_previous_text=False)
                raw=[{'start':float(w.start+a),'end':float(w.end+a),'text':w.word.strip(),'confidence':float(w.probability)} for s in segments for w in s.words or [] if w.word.strip()]
            checkpoint.parent.mkdir(exist_ok=True)
            atomic_json(checkpoint,{'source_sha256':fingerprint,'signature':signature,'range':[a,b],'words':raw})
            return signature,time.perf_counter()-clock
        pending=[]
        for index,(a,b) in enumerate(ranges,1):
            signature=hashlib.sha256(json.dumps([fingerprint,a,b,settings.whisper_model,settings.local_device,settings.local_compute_type,settings.diarization_model,beam_size,language,bool(reusable_asr),2]+(['eligible-single-speaker'] if skip_flags[index-1] else [])).encode()).hexdigest()
            checkpoint=root/'verification-asr'/f'{signature}.json'
            if not checkpoint.exists() and not any(p['signature']==signature for p in evidence['passages']):pending.append((index,a,b,signature,checkpoint))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker.workers) as pool:
            parallel_fresh=dict(pool.map(transcribe_one,pending))
    for passage_index,(a,b) in enumerate(ranges,1):
        skip_this=skip_flags[passage_index-1]
        signature=hashlib.sha256(json.dumps([fingerprint,a,b,settings.whisper_model,settings.local_device,settings.local_compute_type,settings.diarization_model,beam_size,language,bool(reusable_asr),2]+(['eligible-single-speaker'] if skip_this else [])).encode()).hexdigest()
        old=next((p for p in evidence['passages'] if p['signature']==signature),None)
        if old:results.append(old);cache_hits+=1;continue
        clock=time.perf_counter()
        timings={}
        if cached.get('provider')=='local':
            words=[dict(w) for w in cached['words'] if a<=w['start']<w['end']<=b]
            turns=[dict(t) for t in cached['speaker_turns'] if t['start']<b and t['end']>a]
            reused=True
        else:
            if samples is None:
                audio=root/'local-audio.wav'
                if not audio.exists():
                    result=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(audio)],capture_output=True,timeout=7200)
                    if result.returncode:raise StageError('Could not extract source audio for verification.',False)
                samples,rate=soundfile.read(str(audio),dtype='float32')
                if rate!=16000 or samples.ndim!=1:raise ValueError('Verification audio must be mono 16kHz.')
            stage=time.perf_counter()
            if models is None:
                models=(None if reusable_asr else (worker.whisper() if worker else load_whisper()),None) if skip_this else (None,load_diarization()) if reusable_asr else ((worker.whisper(),load_diarization()) if worker else load_models())
            elif not skip_this and models[1] is None:models=(models[0],load_diarization())
            timings['model_load_seconds']=time.perf_counter()-stage
            whisper,pipeline=models;portion=samples[round(a*16000):round(b*16000)]
            checkpoint=root/'verification-asr'/f'{signature}.json'
            stage=time.perf_counter()
            if reusable_asr:
                with timing_hook(f'selected_words_reused_{passage_index}') if timing_hook else nullcontext() as reused_timing:
                    if reused_timing is not None:reused_timing['cached']=True
                    raw=[{k:w[k] for k in ('start','end','text','confidence')} for w in cached['words'] if a<=w['start']<w['end']<=b]
                timings['full_source_asr_reused']=True
                timings['asr_checkpoint_reused']=True
            elif checkpoint.exists():
                saved=json.loads(checkpoint.read_text(encoding='utf-8'))
                if saved.get('source_sha256')!=fingerprint or saved.get('signature')!=signature or saved.get('range')!=[a,b]:
                    raise ValueError('ASR checkpoint does not match this source and passage.')
                raw=saved['words']
                timings['asr_checkpoint_reused']=signature not in parallel_fresh
            else:
                with timing_hook(f'selected_words_{passage_index}') if timing_hook else nullcontext():
                    segments,_=whisper.transcribe(portion,language=language,task='transcribe',word_timestamps=True,vad_filter=False,beam_size=beam_size,condition_on_previous_text=False)
                    raw=[{'start':float(w.start+a),'end':float(w.end+a),'text':w.word.strip(),'confidence':float(w.probability)} for s in segments for w in s.words or [] if w.word.strip()]
                checkpoint.parent.mkdir(exist_ok=True)
                atomic_json(checkpoint,{'source_sha256':fingerprint,'signature':signature,'range':[a,b],'words':raw})
                timings['asr_checkpoint_reused']=False
            timings['asr_seconds']=time.perf_counter()-stage
            if signature in parallel_fresh:timings['asr_seconds']=parallel_fresh[signature];timings['parallel_batch']=True
            stage=time.perf_counter()
            if skip_this:
                turns=[{'start':a,'end':b,'speaker':'DOMINANT_SPEAKER'}]
                timings['diarization_seconds']=0;timings['diarization_skipped']='Eligible fast-mode dominant speaker; not a visual identity assertion'
            else:
                with timing_hook(f'selected_diarization_{passage_index}') if timing_hook else nullcontext():
                    result=pipeline({'waveform':torch.from_numpy(portion.copy()).unsqueeze(0),'sample_rate':16000})
                timings['diarization_seconds']=time.perf_counter()-stage
                annotation=getattr(result,'speaker_diarization',result)
                turns=[{'start':float(t.start+a),'end':float(t.end+a),'speaker':f'{signature[:12]}_{speaker}'} for t,_,speaker in annotation.itertracks(yield_label=True)]
            words=assign_words(raw,turns)
            # IDs remain stable across cache hits and distinct between ranges.
            for word in words:word['id']=int(signature[:8],16)*10000+word['id']
            reused=False
        if not words:raise StageError('No valid speech in this passage; choose another passage or recheck its boundaries.',False)
        passage={'signature':signature,'range':[a,b],'words':words,'speaker_turns':turns,
                 'seconds':time.perf_counter()-clock,'full_local_checkpoint_reused':reused,
                 'speaker_scope':'full source' if reused else 'this verified passage; identities require visual anchors',
                 'model':settings.whisper_model,'beam_size':beam_size,'device':settings.local_device,'timings':timings}
        evidence['passages'].append(passage);atomic_json(path,evidence);results.append(passage)
    return {'verified_passages':str(path.resolve()),'ranges':[p['range'] for p in results],
            'worker_model_load_seconds':max(0,getattr(worker,'model_load_seconds',0)-worker_loaded_before),
            'worker_model_reused':bool(worker_loaded_before),'whisper_beam_size':beam_size,
            'seconds_this_run':time.perf_counter()-started,'cache_hits':cache_hits,'note':'Use these source-time word IDs for final Roman captions; inspect source frames for character identity. Full editorial transcript is unchanged.'}


def transcribe_local(source,root,cancel_event=None,worker=None,beam_size=None):
    beam_size=settings.whisper_beam_size if beam_size is None else beam_size
    root=Path(root)
    started=time.perf_counter();timings={}
    transcript=root/'transcript.json'
    if transcript.exists():
        return {'transcript':str(transcript.resolve()),'transcription_timings':{'checkpoint_reused':True,'seconds_this_run':time.perf_counter()-started}}
    # Whole-source editorial ASR needs no whole-source speaker pipeline. Speaker
    # analysis is deferred to verified selected passages, never guessed here.
    whisper=worker.whisper() if worker else load_whisper()
    timings['model_load_seconds']=time.perf_counter()-started
    stage_started=time.perf_counter()
    audio=root/'local-audio.wav'
    if not audio.exists():
        result=subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-vn','-ar','16000','-ac','1','-c:a','pcm_s16le',str(audio)],capture_output=True,timeout=7200)
        if result.returncode:
            raise StageError('Could not extract source audio for local transcription.',False)
    timings['audio_extract_seconds']=time.perf_counter()-stage_started
    from .render import file_hash
    fingerprint=file_hash(source)
    stage_started=time.perf_counter();asr_path=root/'local-asr-v2.json'
    signature=hashlib.sha256(json.dumps([fingerprint,settings.whisper_model,settings.local_device,settings.local_compute_type,beam_size,'auto',True]).encode()).hexdigest()
    if asr_path.exists() and json.loads(asr_path.read_text(encoding='utf-8')).get('signature')==signature:
        asr=json.loads(asr_path.read_text(encoding='utf-8'))
    else:
        segments,info=whisper.transcribe(str(audio),language=None,task='transcribe',word_timestamps=True,vad_filter=True,beam_size=beam_size,condition_on_previous_text=True)
        words=[]
        for segment in segments:
            if cancel_event and cancel_event.is_set():raise StageError('Uploaded captions became available; unnecessary proxy ASR stopped.',False)
            for word in segment.words or []:
                if word.word.strip():
                    words.append({'start':word.start,'end':word.end,'text':word.word.strip(),'confidence':word.probability})
        asr={'words':words,'language':info.language,'signature':signature,'source_sha256':fingerprint}
        from .youtube_transcript import atomic_json
        atomic_json(asr_path,asr)
    timings['asr_seconds']=time.perf_counter()-stage_started
    if not asr['words']:
        raise StageError('Local transcription detected no speech. Verify the source audio.',False)
    turns=[]
    timings['diarization_deferred_to_selection']=True
    timings['seconds_this_run']=time.perf_counter()-started
    words=assign_words(asr['words'],turns)
    data={'words':words,'text':' '.join(word['text'] for word in words),'language':asr['language'],'provider':'local-asr-draft','models':{'transcription':settings.whisper_model,'compute_type':settings.local_compute_type},'beam_size':beam_size,'source_sha256':fingerprint,'requires_selected_verification':True,'speaker_turns':turns,'uncertain_words':sum(word['speaker_uncertain'] for word in words)}
    data['timings']=timings;data['device']=settings.local_device
    transcript.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    return {'transcript':str(transcript.resolve()),'transcription_timings':timings}
