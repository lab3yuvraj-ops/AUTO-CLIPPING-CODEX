"""Compact scene JSON/CSV validated with an explicit Pydantic JSON schema."""
import csv,json,math,copy
from typing import Literal
from pathlib import Path
from pydantic import BaseModel,ConfigDict,Field,model_validator
from .youtube_transcript import atomic_json

class Position(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    t:float=Field(ge=0)
    center:float=Field(ge=0,le=1)

class BoxAnchor(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    t:float=Field(ge=0)
    bound_type:Literal['subject']='subject'
    box:list[float]=Field(min_length=4,max_length=4)
    visible_subject_box:list[float]|None=None
    bounds_evidence:str|None=None
    @model_validator(mode='after')
    def valid(self):
        x,y,w,h=self.box
        if not all(math.isfinite(v) for v in self.box) or min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:raise ValueError('Invalid reviewed subject box')
        if self.visible_subject_box is not None:
            if len(self.visible_subject_box)!=4:raise ValueError('Visible subject reference needs four coordinates')
            x,y,w,h=self.visible_subject_box
            if not all(math.isfinite(v) for v in self.visible_subject_box) or min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:raise ValueError('Invalid visible subject reference')
        return self

class ActionAnchor(BoxAnchor):
    bound_type:Literal['action']='action'

class Scene(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    id:str
    start:float=Field(ge=0)
    end:float=Field(gt=0)
    center:float=Field(ge=0,le=1)
    kind:str='character'
    evidence:str=Field(min_length=1)
    confidence:float=Field(ge=.8,le=1)
    positions:list[Position]=Field(default_factory=list)
    subject_boxes:list[BoxAnchor]=Field(min_length=1)
    action_boxes:list[ActionAnchor]=Field(default_factory=list)
    @model_validator(mode='after')
    def valid(self):
        if self.start>=self.end or self.kind not in ('character','action','object','text','reaction'):raise ValueError('Invalid scene bounds/kind')
        for rows in (self.positions,self.subject_boxes,self.action_boxes):
            stamps=[r.t for r in rows]
            if stamps!=sorted(set(stamps)) or any(not self.start<=t<=self.end for t in stamps):raise ValueError('Scene anchors must be ordered and inside scene')
        return self

class SceneTable(BaseModel):
    model_config=ConfigDict(extra='forbid')
    scenes:list[Scene]=Field(min_length=1,max_length=500)

def load_table(path):
    path=Path(path)
    if path.suffix.lower()=='.csv':
        with path.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        for row in rows:
            for key in ('positions','subject_boxes','action_boxes'):row[key]=json.loads(row[key]) if row.get(key) else []
        data={'scenes':rows}
    else:data=json.loads(path.read_text(encoding='utf-8'))
    return SceneTable.model_validate(data)

def build_spec(base,table,pan_threshold=.08,min_subject_width_fraction=1.,bounds_policy='reject'):
    if not 0<=pan_threshold<=1:raise ValueError('Invalid scene pan threshold')
    if not 0<min_subject_width_fraction<=1 or bounds_policy not in ('reject','warn'):raise ValueError('Invalid subject-width fraction or policy')
    spec=copy.deepcopy(base);a,b=spec['candidate']['start'],spec['candidate']['end'];targets=[];points=[];previous=a
    warnings=[]
    for scene in table.scenes:
        prior_warning_count=len(warnings)
        for anchor in scene.subject_boxes:
            reference=anchor.visible_subject_box
            problem=None
            if reference is None or not anchor.bounds_evidence:problem='Missing independently reviewed full visible subject bounds/evidence'
            elif anchor.box[2]+1e-6<reference[2]*min_subject_width_fraction:problem='Target box narrower than configured full visible subject width'
            elif anchor.box[0]>reference[0]+1e-6 or anchor.box[0]+anchor.box[2]<reference[0]+reference[2]-1e-6 or anchor.box[1]>reference[1]+1e-6 or anchor.box[1]+anchor.box[3]<reference[1]+reference[3]-1e-6:problem='Target box does not contain full visible subject bounds'
            if problem:
                message=f'{scene.id} at {anchor.t}: {problem}'
                if bounds_policy=='reject':raise ValueError(message)
                warnings.append(message)
        if abs(scene.start-previous)>.001 or scene.end>b+.001:raise ValueError('Scene table must contiguously cover selected story')
        # Optional positions override camera composition; otherwise follow the
        # measured subject centres while retaining the scene's framing offset.
        first_center=scene.subject_boxes[0].box[0]+scene.subject_boxes[0].box[2]/2
        offset=scene.center-first_center
        samples=scene.positions or [Position(t=p.t,center=max(0,min(1,p.box[0]+p.box[2]/2+offset))) for p in scene.subject_boxes]
        pan=max(p.center for p in samples)-min(p.center for p in samples)>pan_threshold
        if pan:
            camera=[p.model_dump() for p in samples]
            if camera[0]['t']>scene.start:camera.insert(0,{'t':scene.start,'center':scene.center})
        else:camera=[{'t':scene.start,'center':scene.center}]
        # Independent subject boxes audit the position, not the centre that chose it.
        full=[{'t':p.t,'box':p.visible_subject_box or p.box,'bound_type':'subject'} for p in scene.subject_boxes]
        action=[p.model_dump(exclude_none=True) for p in scene.action_boxes]
        if any(not p.bounds_evidence for p in scene.action_boxes):raise ValueError('Action bounds need reviewed evidence')
        targets.append({'start':scene.start,'end':scene.end,'scene_start':scene.start,'scene_end':scene.end,'kind':scene.kind,'bound_type':'subject','box':full[0]['box'],'confidence':scene.confidence,'reason':scene.id,'evidence':scene.evidence,'box_keyframes':full,'safety_box_keyframes':full,'action_box_keyframes':action,'camera_center_keyframes':camera,'full_subject_bounds_confirmed':len(warnings)==prior_warning_count})
        points.extend(dict(p,cut=i==0) for i,p in enumerate(camera));previous=scene.end
    if abs(previous-b)>.001:raise ValueError('Scene table must cover story ending')
    spec['tracking']={**spec.get('tracking',{}),'visual_targets':targets,'crop_keyframes':points,'camera_cuts':[s.start for s in table.scenes[1:]],'scene_pan_threshold':pan_threshold,'camera_easing_seconds':1.2,'crop_policy':'full_source_height_horizontal_only','subject_bounds_warnings':warnings,'min_subject_width_fraction':min_subject_width_fraction}
    return spec
