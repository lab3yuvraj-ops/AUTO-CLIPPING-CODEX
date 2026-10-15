"""Private proposal evidence. Public callers expose categories, never payloads."""
import hashlib
import json
import time
import uuid
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from .scene_table import Scene
from .youtube_transcript import atomic_json


class GroundingError(ValueError):
    def __init__(self, category, path, expected=None, received=None):
        public={'unknown_frame':'Missing valid frame evidence (unknown_frame)',
                'no_subjects':'No grounded subjects (no_subjects)'}
        super().__init__(public.get(category,category))
        self.diagnostic={'category':category,'path':path,'expected':expected,'received':received}


class ProposalScene(Scene):
    evidence_frames:list[str]=Field(min_length=1)


class Proposal(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    source_sha256:str
    model_version:str
    scenes:list[ProposalScene]=Field(min_length=1,max_length=500)
    uncertainty:list[str]=Field(default_factory=list)


def response_schema():
    """Inline small shared definitions for Gemini's JSON Schema subset."""
    schema=Proposal.model_json_schema();defs=schema.pop('$defs',{})
    def inline(value):
        if isinstance(value,list):return [inline(v) for v in value]
        if not isinstance(value,dict):return value
        if '$ref' in value:return inline(defs[value['$ref'].split('/')[-1]])
        result={k:inline(v) for k,v in value.items()
                if k not in ('title','default','const','minLength','exclusiveMinimum','exclusiveMaximum')}
        if 'const' in value:result['enum']=[value['const']]
        # Inclusive wire bounds are guidance only. The unchanged strict local
        # Pydantic model enforces exclusive bounds and nonempty strings.
        if 'exclusiveMinimum' in value:result['minimum']=value['exclusiveMinimum']
        if 'exclusiveMaximum' in value:result['maximum']=value['exclusiveMaximum']
        return result
    schema=inline(schema)
    # The wire contract can express an unresolved refusal; local acceptance
    # still requires nonempty grounded scenes and >=0.8 confidence.
    schema['properties']['scenes']['minItems']=0
    schema['properties']['scenes']['items']['properties']['kind']={'type':'string','enum':['character','action','object','text','reaction']}
    anchors=schema['properties']['scenes']['items']['properties']['subject_boxes']['items']
    anchors['required']=list(dict.fromkeys(anchors.get('required',[])+['visible_subject_box','bounds_evidence']))
    return schema


def strict_json(text):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    def constant(value):raise ValueError('Non-finite JSON number')
    return json.loads(text,object_pairs_hook=pairs,parse_constant=constant)


def decode_response(content, base, details, model, validate):
    """Returns private diagnostic even for invalid wire JSON; never repairs meaning."""
    diagnostic={'finish_reason':None,'complete_json':False,'json_error':None,
                'schema_errors':[],'grounding_error':None,'normalization':None}
    body=None;proposal=None;spec=None;warnings=[]
    try:
        if len(content)>2_000_000:
            diagnostic['category']='response_size';return spec,warnings,body,proposal,diagnostic
        try:body=strict_json(content.decode('utf-8'))
        except (ValueError,UnicodeError) as exc:
            diagnostic.update(category='response_json',json_error=str(exc));return spec,warnings,body,proposal,diagnostic
        candidate=(body.get('candidates') or [None])[0] if isinstance(body,dict) else None
        if not isinstance(candidate,dict):
            diagnostic['category']='missing_candidate';return spec,warnings,body,proposal,diagnostic
        diagnostic['finish_reason']=candidate.get('finishReason')
        parts=candidate.get('content',{}).get('parts',[])
        text=''.join(p.get('text','') for p in parts if not p.get('thought'))
        # Only UTF-8 BOM and outer whitespace removal. No fences, numeric casts,
        # sorting, timestamp shifts, box shrinking or identity reassignment.
        normalized=text.lstrip('\ufeff').strip()
        if normalized!=text:
            diagnostic['normalization']={'operation':'outer_whitespace_and_bom_only',
                'before_sha256':hashlib.sha256(text.encode()).hexdigest(),
                'after_sha256':hashlib.sha256(normalized.encode()).hexdigest()}
        try:proposal=strict_json(normalized);diagnostic['complete_json']=True
        except ValueError as exc:diagnostic['json_error']=str(exc)
        if diagnostic['finish_reason']!='STOP':diagnostic['category']='finish_reason'
        elif not diagnostic['complete_json']:diagnostic['category']='proposal_json'
        else:
            # Preserve exact source/model/grounding checks; do not apply coercions.
            Proposal.model_validate(proposal,strict=True)
            spec,warnings=validate(base,proposal,details,model)
            diagnostic['category']='accepted_unreviewed'
    except ValidationError as exc:
        errors=json.loads(json.dumps(exc.errors(include_url=False),default=str))
        for error in errors:
            error['path']=error['loc'];error['received']=error.pop('input',None)
            error['expected']={'constraint':error['type'],'context':error.get('ctx',{})}
        diagnostic.update(category='schema',schema_errors=errors)
    except GroundingError as exc:
        diagnostic.update(category='grounding',grounding_error=exc.diagnostic)
    except (ValueError,KeyError,TypeError,IndexError,AttributeError) as exc:
        diagnostic.update(category='local_validation',local_error={'type':type(exc).__name__,'message':str(exc)})
    if diagnostic.get('category')!='accepted_unreviewed':spec=None
    return spec,warnings,body,proposal,diagnostic


def save_private(root, content, diagnostic, context, secrets=()):
    folder=Path(root)/'private-gemini'/f'{time.time_ns()}-{uuid.uuid4().hex[:8]}'
    folder.mkdir(parents=True,exist_ok=False)
    # Defense in depth for custom/test job roots. Nothing here is exportable.
    (folder.parent/'.gitignore').write_text('*\n',encoding='utf-8')
    def redact(text):
        for secret in secrets:
            if secret:text=text.replace(secret,'[REDACTED]')
        return text
    record={**diagnostic,**context,'response_sha256':hashlib.sha256(content).hexdigest(),
            'response_bytes':len(content),'raw_saved':len(content)<=2_000_000,
            'publication_approved':False}
    atomic_json(folder/'diagnostic.json',json.loads(redact(json.dumps(record))))
    if record['raw_saved']:
        (folder/'response.private.txt').write_text(redact(content.decode('utf-8',errors='replace')),encoding='utf-8')
    return folder
