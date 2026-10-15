"""Local audio alignment of editorially evidenced wording, never cue timing."""
import hashlib
import json
import math
import time
from pathlib import Path
from .local_transcription import load_whisper, speech_language
from .youtube_transcript import atomic_json


def validate_requests(items, duration):
    if not isinstance(items, list) or not items:
        raise ValueError('Provide a nonempty list of alignment passages.')
    for item in items:
        a, b = item['range']
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b)) or not 0 <= a < b <= duration or b-a > 30:
            raise ValueError('Alignment passages must be finite, inside the source and at most 30 seconds.')
        if not str(item.get('text', '')).strip() or not str(item.get('evidence', '')).strip():
            raise ValueError('Alignment needs exact reviewed wording and its evidence. It cannot verify invented text.')


def align_passages(root, manifest):
    import soundfile
    from faster_whisper.tokenizer import Tokenizer
    from faster_whisper.audio import pad_or_trim
    from .config import settings
    root = Path(root)
    audio = root/'local-audio.wav'
    samples, rate = soundfile.read(audio, dtype='float32')
    if rate != 16000 or samples.ndim != 1:
        raise ValueError('Alignment requires the saved mono 16kHz source audio.')
    items = json.loads(Path(manifest).read_text(encoding='utf-8'))
    validate_requests(items, len(samples)/rate)
    fingerprint = hashlib.sha256(audio.read_bytes()).hexdigest()
    language = speech_language(root)
    if not language:
        raise ValueError('Resolve the source speech language before aligning text.')
    folder = root/'alignments'; folder.mkdir(exist_ok=True)
    model = None; results = []; started = time.perf_counter()
    for item in items:
        a, b = item['range']
        signature = hashlib.sha256(json.dumps([fingerprint, item, language, settings.whisper_model, settings.local_device, 1], sort_keys=True).encode()).hexdigest()
        path = folder/(signature+'.json')
        if path.exists():
            results.append(json.loads(path.read_text(encoding='utf-8')) | {'cache_reused':True}); continue
        if model is None:
            model = load_whisper()
        tokenizer = Tokenizer(model.hf_tokenizer, model.model.is_multilingual, task='transcribe', language=language)
        portion = samples[round(a*rate):round(b*rate)]
        features = model.feature_extractor(portion)
        frames = min(features.shape[-1], model.feature_extractor.nb_max_frames)
        encoded = model.encode(pad_or_trim(features))
        aligned = model.find_alignment(tokenizer, [tokenizer.encode(' '+item['text'].strip())], encoded, frames)[0]
        words = []
        for row in aligned:
            text = row['word'].strip()
            if not text: continue
            x, y = float(a+row['start']), float(a+row['end'])
            words.append({'text':text,'start':x,'end':y,'confidence':float(row['probability']),
                'timing_needs_review':not (a <= x < y <= b+.02) or y-x > 1.5})
        if not words:
            raise ValueError('Local alignment returned no words; preserve the saved speech evidence.')
        result = {'range':[a,b],'words':words,'text':item['text'],'evidence':item['evidence'],
            'audio_sha256':fingerprint,'language':language,'model':settings.whisper_model,
            'method':'cached Whisper attention alignment of reviewed source wording',
            'requires_editorial_review':True,'signature':signature,'cache_reused':False,
            'note':'Forced alignment does not prove text was spoken. Inspect wording evidence and timing flags before adding to a clip.'}
        atomic_json(path,result); results.append(result)
    report = {'passages':results,'seconds_this_run':time.perf_counter()-started,'device':settings.local_device,
        'note':'Original ASR and verified passages are unchanged. Alignment remains editorial evidence until reviewed.'}
    atomic_json(root/'alignment-report.json',report)
    return {'alignment_report':str((root/'alignment-report.json').resolve()),'passage_count':len(results),
        'timing_flags':sum(w['timing_needs_review'] for p in results for w in p['words']),
        'seconds_this_run':report['seconds_this_run']}
