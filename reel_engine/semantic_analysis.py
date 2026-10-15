"""Optional, explicitly configured vision-language endpoint; no default API calls.

Compatible with local CPU VLM servers that accept chat-completion image inputs.
Coordinates are proposals, never silently promoted to inspected identity evidence.
"""
import base64
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse
import httpx
from .editing_plan import fingerprint,grounded_scene_proposal
from .youtube_transcript import atomic_json


def analyze(base,details,transcript,root,*,endpoint='',model='',key='',allow_remote=False):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if not endpoint:
        result={'status':'needs_review','reason':'No semantic vision endpoint configured. Keep the saved stable framing; do not guess object locations.',
                'api_calls':0,'estimated_api_cost':0,'publication_approved':False}
        atomic_json(root/'semantic-analysis-status.json',result);return result
    parsed=urlparse(endpoint)
    if parsed.scheme not in ('http','https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use an explicit HTTP(S) endpoint without credentials/query in its URL')
    local=parsed.hostname in ('localhost','127.0.0.1','::1')
    if not local and (not allow_remote or parsed.scheme!='https'):
        raise ValueError('Remote vision requires explicit opt-in and HTTPS')
    if not model:raise ValueError('Set the semantic model/version explicitly')
    images=[]
    for frame in details['frames']:
        data=Path(frame['file']).read_bytes()
        if hashlib.sha256(data).hexdigest()!=frame['sha256']:raise ValueError('Semantic input frame changed')
        images.append((frame,data))
    signature=fingerprint({'version':1,'source':details['source_sha256'],'frames':[(f['source_seconds'],f['sha256']) for f,_ in images],
                           'base':base,'transcript':transcript,'model':model,'endpoint_hash':hashlib.sha256(endpoint.encode()).hexdigest()})
    path=root/'semantic-analysis.json'
    if path.exists():
        old=json.loads(path.read_text(encoding='utf8'));unsigned={k:v for k,v in old.items() if k!='content_hash'}
        if old.get('signature')==signature and old.get('content_hash')==fingerprint(unsigned):
            grounded_scene_proposal(base,old['proposal'],details)
            return {**old,'cache_reused':True,'api_calls_this_run':0}
    content=[{'type':'text','text':json.dumps({'task':'Propose contiguous full-height horizontal crop scenes grounded in these actual frames and transcript. Prioritize relevant objects/text/actions as well as people. Do not infer screen side from audio labels. Do not invent coordinates. Return empty scenes if uncertain. No zoom, vertical move, fit, backgrounds or split-screen.',
                 'candidate':base['candidate'],'transcript':transcript,'source_sha256':details['source_sha256'],
                 'required_output':{'source_sha256':details['source_sha256'],'model_version':model,'scenes':'SceneTable scenes with id,start,end,center,kind,confidence,evidence,subject_boxes(t,box,visible_subject_box,bounds_evidence), optional positions, evidence_frames=[sha256]. Coordinates normalized. Full required visible subject bounds; confidence >=0.8 otherwise omit.'}})}]
    for frame,data in images:
        content.extend([{'type':'text','text':json.dumps({'source_seconds':frame['source_seconds'],'frame_sha256':frame['sha256']})},
                        {'type':'image_url','image_url':{'url':'data:image/jpeg;base64,'+base64.b64encode(data).decode()}}])
    headers={'Authorization':'Bearer '+key} if key else {}
    try:
        response=httpx.post(endpoint,headers=headers,json={'model':model,'temperature':0,'messages':[{'role':'user','content':content}],
                            'response_format':{'type':'json_object'}},timeout=120)
        if response.status_code!=200:raise ValueError('Vision endpoint returned HTTP '+str(response.status_code))
        if len(response.content)>2_000_000:raise ValueError('Vision response exceeds size limit')
        body=response.json();proposal=json.loads(body['choices'][0]['message']['content'])
        spec=grounded_scene_proposal(base,proposal,details)
    except (httpx.HTTPError,ValueError,KeyError,IndexError,TypeError):
        # No retries, provider bodies, keys or automatic unsafe center fallbacks.
        result={'status':'needs_review','reason':'Vision unavailable or proposal failed grounding/schema validation; keep stable reviewed framing.',
                'api_calls':1,'estimated_api_cost':None,'publication_approved':False}
        atomic_json(root/'semantic-analysis-status.json',result);return result
    result={'signature':signature,'proposal':proposal,'status':'proposal_needs_inspection','cache_reused':False,
            'api_calls_this_run':1,'estimated_api_cost':None,'provider_usage':body.get('usage',{}),
            'model_version':model,'publication_approved':False}
    result['content_hash']=fingerprint(result);atomic_json(path,result);atomic_json(root/'semantic-proposed-spec.json',spec)
    return result
