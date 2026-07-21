"""
타슈 - 통합 스냅샷 엔진 (님 파트 최종 산출물)
=================================================
시점을 받아 그 시점의 JSON을 '반환'. 파일 저장 X, API가 감싸서 서빙.
데모/실시간 모드 공유 - 기준시점(ref_time)만 다름.

백엔드 사용 예:
  from snapshot_engine import compute_snapshot
  data = compute_snapshot(date='2026-03-17', round_id='C')   # 데모
  data = compute_snapshot(mode='realtime')                    # 실시간(현재→가까운 과거회차)

미리 로드(서버 起動시 1회): load_artifacts() -> 이후 요청마다 재사용 (빠름)
"""
import pandas as pd, numpy as np, json, torch
from model import A3TGCN_Dir as A3TGCN

OUT_DIR="processed"
ROUND_TIME={'A':'07:00','B':'11:30','C':'16:00','D':'03:00'}
_ART=None  # 캐시된 아티팩트 (서버 起動시 1회 로드)

def band_to_status(b):
    return {'none':'맑음','light':'약한 비','heavy':'우천'}.get(b,'맑음')

def load_artifacts():
    """서버 起動시 1회 호출. 모델·데이터를 메모리에 로드해 이후 요청서 재사용."""
    global _ART
    if _ART is not None: return _ART
    from model_mtgnn import MTGNN
    A=torch.tensor(np.load(f'{OUT_DIR}/adjacency_directed.npy')).float()
    stats=json.load(open(f'{OUT_DIR}/norm_stats.json'))
    # MTGNN: 학습 인접행렬 + 정적 방향 그래프 결합
    node_index=pd.read_csv(f'{OUT_DIR}/node_index.csv')
    model=MTGNN(f_node=stats['F_node'], f_global=4, n_nodes=len(node_index),
                hidden=48, emb_dim=16, use_static=True)
    model.load_state_dict(torch.load(f'{OUT_DIR}/mtgnn.pt',map_location='cpu')['state'])
    model.eval()
    _ART=dict(
        X_node=np.load(f'{OUT_DIR}/X_node.npy'),
        X_global=np.load(f'{OUT_DIR}/X_global.npy'),
        A=A, model=model, stats=stats,
        fmn=np.load(f'{OUT_DIR}/flow_mean_n.npy'),
        fsn=np.load(f'{OUT_DIR}/flow_std_n.npy'),
        node_index=pd.read_csv(f'{OUT_DIR}/node_index.csv'),
        sm=pd.read_csv(f'{OUT_DIR}/station_master.csv'),
        timeline=pd.read_csv(f'{OUT_DIR}/timeline.csv',parse_dates=['service_date']),
        weather=pd.read_parquet(f'{OUT_DIR}/weather_rounds.parquet'),
        bikes=pd.read_parquet(f'{OUT_DIR}/bike_features.parquet'),
        flow=np.load(f'{OUT_DIR}/flow.npy'),
    )
    return _ART

def _reconstruct_availability(flow, timeline, target_idx, baseline=8):
    """
    선택 B: 순유출입 누적으로 상대 재고 재구성.
    해당 회차가 속한 서비스일의 시작(baseline)부터 그 회차 '시작 시점'까지 flow 누적.
    절대값은 baseline 가정이나 증감은 실제 flow 기반. 하루 단위 리셋으로 drift 방지.
    반환: [N] 그 회차 시작 시점의 대여소별 가용대수(>=0)
    """
    row=timeline.iloc[target_idx]
    sd=row['service_date']
    # 같은 서비스일의 회차들을 시간순으로
    day_rows=timeline[timeline['service_date']==sd].sort_values('round_ord')
    day_idx=day_rows.index.tolist()
    # target까지(미포함) 누적 = 그 회차 시작 시점 재고
    avail=np.full(flow.shape[1], float(baseline))
    for ti in day_idx:
        if ti==target_idx:
            break
        avail=avail+flow[ti]   # 이전 회차들의 flow 반영
    return np.clip(avail,0,None)

def _broken_counts(bikes, ref_time, target_ids, top_pct=0.20):
    """ref_time 기준 idle_days 재계산 -> station별 고장 의심 카운트 + bike Top."""
    b=bikes.copy()
    b['idle_days']=(pd.Timestamp(ref_time)-b['last_used']).dt.total_seconds()/86400
    b=b[b['idle_days']>=0]  # 미래 이력 제외 (해당 시점에 아직 없던 것)
    def norm(s,cap): return np.clip(s/cap,0,1)
    b['broken_score']=(0.40*norm(b['idle_days'],30)+0.30*b['zero_dist_ratio']
                       +0.15*b['short_trip_ratio']+0.15*(1-norm(b['total_trips'],20)))
    cnt={}
    for sid,grp in b.groupby('last_station'):
        thr=grp['broken_score'].quantile(1-top_pct)
        cnt[sid]=int((grp['broken_score']>=thr).sum())
    top=b.nlargest(10,'broken_score')[['자전거번호','last_station','idle_days','broken_score']]
    return cnt, top

def compute_snapshot(date=None, round_id=None, mode='demo', demo_mode=True):
    """
    시점의 JSON 반환.
    - mode='demo': date+round_id 지정
    - mode='realtime': 현재시각 기준 가장 가까운 과거 회차 (API 없으면 폴백)
    """
    A=load_artifacts()
    tl=A['timeline']

    # 시점 -> 타임라인 인덱스
    if mode=='realtime':
        now=pd.Timestamp.now()
        # 현재 이전의 가장 최근 회차 (실제 API 붙기 전 폴백)
        cand=tl.copy()
        # round_start 근사: service_date + 회차 시작시각
        target=tl.index[-1]  # 폴백: 마지막
    else:
        m=(tl['service_date']==pd.Timestamp(date))&(tl['round_id']==round_id)
        if not m.any():
            raise ValueError(f"해당 시점 없음: {date} {round_id}")
        target=tl[m].index[0]

    if target<8:
        raise ValueError("입력 윈도우(8회차) 부족한 시점")
    row=tl.iloc[target]
    ref_time=pd.Timestamp(row['service_date'])+pd.Timedelta(hours=float(ROUND_TIME[row['round_id']].split(':')[0]))

    # STGNN 분류 추론: 부족/정상/과잉 확률
    W=8
    xn=torch.tensor(A['X_node'][target-W:target][None]).float()
    xg=torch.tensor(A['X_global'][target-W:target][None]).float()
    with torch.no_grad():
        logits=A['model'](xn,xg,A['A'])[0]          # [N,3]
        probs=torch.softmax(logits,dim=-1).numpy()   # [N,3] 클래스 확률
    cls=probs.argmax(-1)                             # [N] 0=부족 1=정상 2=과잉
    CLS_NAMES=['shortage','normal','surplus']

    # 고장 (ref_time 기준 재계산)
    target_ids=set(A['node_index']['station_id'])
    bcnt, btop=_broken_counts(A['bikes'], ref_time, target_ids)

    # 날씨
    w=A['weather']
    wrow=w[(w['service_date']==row['service_date'])&(w['round_id']==row['round_id'])]
    if len(wrow):
        temp=float(wrow['temp_mean'].iloc[0]); band=wrow['precip_band'].iloc[0]; precip=float(wrow['precip_sum'].iloc[0])
    else: temp,band,precip=15.0,'none',0.0

    # 가용대수: 선택 B (순유출입 누적 재구성). demo_mode에서만.
    avail_arr = _reconstruct_availability(A['flow'], tl, target) if demo_mode else None

    stations=[]
    for i,r in A['node_index'].iterrows():
        sid=r['station_id']; info=A['sm'][A['sm']['station_id']==sid]
        if len(info)==0: continue
        info=info.iloc[0]; broken=int(bcnt.get(sid,0))
        api=int(avail_arr[i]) if avail_arr is not None else None
        real=max(0,api-broken) if api is not None else None
        p_short,p_norm,p_surp=float(probs[i,0]),float(probs[i,1]),float(probs[i,2])
        # recommendation: 관제팀용 재배치 힌트
        # 예측 방향(class)과 재구성 재고(api) 둘 다 고려 -> 모순 상황 회피
        cls_name=CLS_NAMES[cls[i]]
        avail=api if api is not None else 8   # 재고 없으면 baseline 가정
        if cls_name=='surplus' and avail>=2:
            # 과잉 예측 + 실제 재고 있음 -> 걷어감
            action='collect'
            amount_hint=int(round(avail*p_surp*0.4))
        elif cls_name=='shortage':
            # 부족 예측 -> 채움. 재고 0에 가까울수록 급함
            action='supply'
            urgency=1.0+(1.0 if avail<=1 else 0.0)   # 재고 0~1이면 긴급 가중
            amount_hint=int(round(p_short*6*urgency))
        else:
            # normal 이거나, surplus인데 재고 부족(곧 채워질 곳) -> 지켜봄
            action='hold'; amount_hint=0
        confidence=round(max(p_short,p_norm,p_surp),2)
        stations.append({"station_id":sid,"station_name":info['name'],
            "location":{"lat":float(info['lat']),"lng":float(info['lng'])},
            "current_weather":{"status":band_to_status(band),"precipitation_mm":round(precip,1),"temperature_c":round(temp,1)},
            "ml_correction":{"api_available":api,"broken_suspected":broken,"real_available":real},
            "stgnn_prediction":{
                "class":cls_name,                                 # shortage/normal/surplus (히트맵 3색)
                "probs":{"shortage":round(p_short,3),"normal":round(p_norm,3),"surplus":round(p_surp,3)},
                "shortage_pressure":round(p_short,2),             # 부족 확률 (기존 프론트 호환)
                "recommendation":{                                # 관제팀용 재배치 힌트
                    "action":action,                              # collect / supply / hold
                    "amount_hint":amount_hint,                    # 대략 대수 (확실한 정답 아님, 규모 감)
                    "confidence":confidence}}})                   # 예측 확률 최대값

    return {"meta":{"date":str(row['service_date'].date()),"round_id":row['round_id'],
                    "time":ROUND_TIME[row['round_id']],"mode":mode,"demo_mode":demo_mode,
                    "note":"class는 다음 회차 수급 예측(부족/정상/과잉). 확률 기반 보조지표이며 최종 판단은 관제팀."},
            "priority_bikes":[{"bike_id":r['자전거번호'],"station_id":r['last_station'],
                               "idle_days":round(r['idle_days'],1),"broken_score":round(r['broken_score'],3)}
                              for _,r in btop.iterrows()],
            "stations":stations}

def save_snapshot(date, round_id, out_path=None):
    """한 회차 스냅샷을 JSON 파일로 저장."""
    d=compute_snapshot(date=date, round_id=round_id)
    if out_path is None:
        out_path=f'{OUT_DIR}/snapshot_{date}_{round_id}.json'
    with open(out_path,'w',encoding='utf-8') as f:
        json.dump(d,f,ensure_ascii=False,indent=2)
    print(f"[저장] {out_path} ({len(d['stations'])}개 대여소)")
    return out_path

def save_scenario(date, out_path=None):
    """하루 전체 회차(A/B/C/D)를 한 파일에 프레임 시퀀스로 저장 (시연용)."""
    frames=[]
    for rid in ['A','B','C','D']:
        try:
            frames.append(compute_snapshot(date=date, round_id=rid))
        except ValueError:
            continue   # 윈도우 부족 등으로 없는 회차는 건너뜀
    out={"meta":{"scenario_date":date,"n_frames":len(frames),
                 "note":"과거 재생 시연. class는 수급 예측(확률 기반 보조지표)."},
         "frames":frames}
    if out_path is None:
        out_path=f'{OUT_DIR}/scenario_{date}.json'
    with open(out_path,'w',encoding='utf-8') as f:
        json.dump(out,f,ensure_ascii=False,indent=2)
    print(f"[저장] {out_path} ({len(frames)}개 회차 프레임)")
    return out_path

if __name__=='__main__':
    import sys
    # 사용법:
    #   python snapshot_engine.py                       -> 기본 테스트 출력
    #   python snapshot_engine.py 2026-03-17 C          -> 단일 회차 저장
    #   python snapshot_engine.py 2026-03-17            -> 하루 전체(시나리오) 저장
    if len(sys.argv)==3:
        save_snapshot(sys.argv[1], sys.argv[2])
    elif len(sys.argv)==2:
        save_scenario(sys.argv[1])
    else:
        d=compute_snapshot(date='2026-03-17', round_id='C')
        print(f"[스냅샷] {d['meta']['date']} {d['meta']['round_id']}회차, "
              f"{len(d['stations'])}개 대여소, 고장Top {len(d['priority_bikes'])}대")
        print("저장하려면: python snapshot_engine.py 2026-03-17 C  (단일)")
        print("           python snapshot_engine.py 2026-03-17    (하루 전체)")