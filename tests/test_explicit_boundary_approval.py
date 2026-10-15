from reel_engine.preflight import approved_boundary_rows


def test_only_exact_human_approved_boundary_is_accepted():
    row={'time':40.333,'edge':'ending'}
    spec={'candidate':{'start':0.,'end':40.5},'boundary_review':[{'choice':'keep-flash','approved_by':'human','evidence':'Human selected keep shot change','source_sha256':'source','candidate_start':0.,'candidate_end':40.5,'time':40.333,'edge':'end'}]}
    assert approved_boundary_rows(spec,'source',[row])==([],[row])
    assert approved_boundary_rows(spec,'other',[row])==([row],[])
    spec['candidate']['end']=40.6
    assert approved_boundary_rows(spec,'source',[row])==([row],[])


def test_other_cut_or_unapproved_choice_is_never_accepted():
    spec={'candidate':{'start':0.,'end':40.5},'boundary_review':[]}
    row={'time':40.333,'edge':'ending'}
    assert approved_boundary_rows(spec,'source',[row])==([row],[])
