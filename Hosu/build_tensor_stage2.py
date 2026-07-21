"""
텐서 2단계 v3: 피처 추가 (평균 도망 해결 시도)
=================================================
추가 노드 피처 (모두 과거만 참조 -> 누수 없음):
  1) flow 이동평균 (최근 4회차)  - 추세
  2) 같은 요일·회차 과거 평균     - 주기 베이스라인 (핵심)
  3) 총 거래량(inflow+outflow) 이동평균 - 활성도

기존: flow_z + 요일7 + 회차4 = 12
신규: + flow_ma + dow_round_base + volume_ma = 15
표준화는 대여소별 유지.
"""
import pandas as pd, numpy as np, json

OUT_DIR="processed"
ROUND_COLS=['A','B','C','D']
PRECIP_BANDS=['none','light','heavy']
MA_WINDOW=4   # 이동평균 창 (회차)

def main():
    flow=np.load(f'{OUT_DIR}/flow.npy')      # [T,N]
    mask=np.load(f'{OUT_DIR}/mask.npy')
    timeline=pd.read_csv(f'{OUT_DIR}/timeline.csv',parse_dates=['service_date'])
    weather=pd.read_parquet(f'{OUT_DIR}/weather_rounds.parquet')
    T,N=flow.shape
    train_ts=(timeline['period']=='train').values
    dow=timeline['service_date'].dt.dayofweek.values
    ridx=timeline['round_id'].map({c:i for i,c in enumerate(ROUND_COLS)}).values

    # 총 거래량 격자 (inflow+outflow) 복원 위해 netflow parquet 재사용
    nf=pd.read_parquet(f'{OUT_DIR}/netflow.parquet')
    node_index=pd.read_csv(f'{OUT_DIR}/node_index.csv')
    sid2col={s:i for i,s in enumerate(node_index['station_id'])}
    ts2row={}
    tl_sorted=timeline.copy()
    tl_sorted['round_ord']=ridx
    # (service_date, round_id) -> row idx
    for i,r in timeline.iterrows():
        ts2row[(pd.Timestamp(r['service_date']),r['round_id'])]=i
    volume=np.zeros((T,N),dtype=np.float32)
    for _,r in nf.iterrows():
        key=(pd.Timestamp(r['service_date']),r['round_id'])
        if key in ts2row and r['station_id'] in sid2col:
            volume[ts2row[key],sid2col[r['station_id']]]=r['inflow']+r['outflow']

    # ── 피처1: flow 이동평균 (과거 MA_WINDOW, 현재 제외) ──
    flow_ma=np.zeros((T,N),dtype=np.float32)
    for t in range(T):
        lo=max(0,t-MA_WINDOW)
        if t>0: flow_ma[t]=flow[lo:t].mean(axis=0)
    # ── 피처3: volume 이동평균 ──
    vol_ma=np.zeros((T,N),dtype=np.float32)
    for t in range(T):
        lo=max(0,t-MA_WINDOW)
        if t>0: vol_ma[t]=volume[lo:t].mean(axis=0)

    # ── 피처2: 같은 요일·회차 과거 평균 (누적, 현재 이전만) ──
    dow_round_base=np.zeros((T,N),dtype=np.float32)
    # (dow, round)별로 시간순 누적 평균
    from collections import defaultdict
    acc_sum=defaultdict(lambda:np.zeros(N)); acc_cnt=defaultdict(lambda:np.zeros(N))
    for t in range(T):
        key=(dow[t],ridx[t])
        # 현재 시점 이전까지의 평균을 피처로
        cnt=acc_cnt[key]
        dow_round_base[t]=np.where(cnt>0, acc_sum[key]/np.maximum(cnt,1), 0)
        # 그 다음 현재값 누적 (유효한 것만)
        m=mask[t]==1
        acc_sum[key]+=np.where(m,flow[t],0)
        acc_cnt[key]+=m.astype(float)

    # ── 대여소별 표준화 (flow, flow_ma, base, vol_ma 각각) ──
    def per_station_z(arr):
        z=np.zeros_like(arr); means=np.zeros(N); stds=np.ones(N)
        for j in range(N):
            v=arr[train_ts,j][mask[train_ts,j]==1]
            if len(v)>1:
                means[j]=v.mean(); stds[j]=v.std()+1e-6
            z[:,j]=(arr[:,j]-means[j])/stds[j]
        return z.astype(np.float32),means,stds
    flow_z,fmn,fsn=per_station_z(flow)
    flow_ma_z,_,_=per_station_z(flow_ma)
    base_z,_,_=per_station_z(dow_round_base)
    vol_ma_z,_,_=per_station_z(vol_ma)

    # 시간·날씨 피처
    dow_oh=np.eye(7,dtype=np.float32)[dow]
    round_oh=np.eye(4,dtype=np.float32)[ridx]
    tlw=timeline.merge(weather,on=['service_date','round_id'],how='left')
    temp=tlw['temp_mean'].values.astype(np.float32)
    band=tlw['precip_band'].fillna('none').values
    tv=train_ts&~np.isnan(temp)
    tm=float(temp[tv].mean()); tsd=float(temp[tv].std()+1e-8)
    temp=np.where(np.isnan(temp),tm,temp); temp_z=(temp-tm)/tsd
    band_oh=np.zeros((T,3),dtype=np.float32)
    for i,b in enumerate(band): band_oh[i,PRECIP_BANDS.index(b) if b in PRECIP_BANDS else 0]=1.0

    # 조립: flow_z(1)+ma(1)+base(1)+vol(1)+요일7+회차4 = 15
    F_node=1+1+1+1+7+4
    X_node=np.zeros((T,N,F_node),dtype=np.float32)
    X_node[:,:,0]=flow_z
    X_node[:,:,1]=flow_ma_z
    X_node[:,:,2]=base_z
    X_node[:,:,3]=vol_ma_z
    X_node[:,:,4:11]=dow_oh[:,None,:]
    X_node[:,:,11:15]=round_oh[:,None,:]
    X_global=np.concatenate([temp_z[:,None],band_oh],axis=1).astype(np.float32)

    np.save(f'{OUT_DIR}/X_node.npy',X_node)
    np.save(f'{OUT_DIR}/X_global.npy',X_global)
    np.save(f'{OUT_DIR}/flow_mean_n.npy',fmn.astype(np.float32))
    np.save(f'{OUT_DIR}/flow_std_n.npy',fsn.astype(np.float32))
    json.dump({'per_station':True,'F_node':int(F_node),'F_global':4,'ma_window':MA_WINDOW,
               'feat':['flow_z','flow_ma','dowround_base','vol_ma','dow*7','round*4']},
              open(f'{OUT_DIR}/norm_stats.json','w'),ensure_ascii=False,indent=2)
    print(f"[v3] X_node {X_node.shape} (피처 {F_node}개: flow+ma+base+vol+요일+회차)")
    print(f"[v3] 추가피처 3종: flow이동평균, 요일회차베이스라인, 거래량이동평균")
    print(f"[v3] 저장 완료")

if __name__=='__main__':
    main()