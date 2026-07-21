"""
텐서 2단계 v4: 반등 피처 추가 (음의 자기상관 신호 활용)
=================================================
quick_compare에서 발견: net_flow에 음의 자기상관(-0.24) = 반등 패턴.
"직전에 빠졌으면 다음엔 채워진다"는 신호를 명시적 피처로.

v3(15채널)에 추가:
  16) prev_flow_z: 직전 회차 net_flow (반등의 직접 신호)
  17) rebound_signal: 최근 2회차 flow 차이 (반등 방향/강도)
= 17채널. 모두 과거만 참조(누수 없음). 대여소별 표준화.
"""
import pandas as pd, numpy as np, json
from collections import defaultdict

OUT_DIR="processed"
ROUND_COLS=['A','B','C','D']; PRECIP_BANDS=['none','light','heavy']; MA_WINDOW=4

def main():
    flow=np.load(f'{OUT_DIR}/flow.npy'); mask=np.load(f'{OUT_DIR}/mask.npy')
    timeline=pd.read_csv(f'{OUT_DIR}/timeline.csv',parse_dates=['service_date'])
    weather=pd.read_parquet(f'{OUT_DIR}/weather_rounds.parquet')
    T,N=flow.shape
    train_ts=(timeline['period']=='train').values
    dow=timeline['service_date'].dt.dayofweek.values
    ridx=timeline['round_id'].map({c:i for i,c in enumerate(ROUND_COLS)}).values

    # 거래량 (v3와 동일)
    nf=pd.read_parquet(f'{OUT_DIR}/netflow.parquet')
    node_index=pd.read_csv(f'{OUT_DIR}/node_index.csv')
    sid2col={s:i for i,s in enumerate(node_index['station_id'])}
    ts2row={}
    for i,r in timeline.iterrows(): ts2row[(pd.Timestamp(r['service_date']),r['round_id'])]=i
    volume=np.zeros((T,N),dtype=np.float32)
    for _,r in nf.iterrows():
        key=(pd.Timestamp(r['service_date']),r['round_id'])
        if key in ts2row and r['station_id'] in sid2col:
            volume[ts2row[key],sid2col[r['station_id']]]=r['inflow']+r['outflow']

    # v3 피처들
    flow_ma=np.zeros((T,N),dtype=np.float32); vol_ma=np.zeros((T,N),dtype=np.float32)
    for t in range(T):
        lo=max(0,t-MA_WINDOW)
        if t>0: flow_ma[t]=flow[lo:t].mean(0); vol_ma[t]=volume[lo:t].mean(0)
    dow_round_base=np.zeros((T,N),dtype=np.float32)
    acc_s=defaultdict(lambda:np.zeros(N)); acc_c=defaultdict(lambda:np.zeros(N))
    for t in range(T):
        key=(dow[t],ridx[t]); c=acc_c[key]
        dow_round_base[t]=np.where(c>0,acc_s[key]/np.maximum(c,1),0)
        m=mask[t]==1; acc_s[key]+=np.where(m,flow[t],0); acc_c[key]+=m.astype(float)

    # ── NEW: 반등 피처 ──
    prev_flow=np.zeros((T,N),dtype=np.float32)      # 직전 회차 flow
    rebound=np.zeros((T,N),dtype=np.float32)        # 반등 방향 (직전-그전)
    for t in range(T):
        if t>=1: prev_flow[t]=flow[t-1]
        if t>=2: rebound[t]=flow[t-1]-flow[t-2]

    # 대여소별 표준화
    def psz(arr):
        z=np.zeros_like(arr)
        for j in range(N):
            v=arr[train_ts,j][mask[train_ts,j]==1]
            m_,s_=(v.mean(),v.std()+1e-6) if len(v)>1 else (0,1)
            z[:,j]=(arr[:,j]-m_)/s_
        return z.astype(np.float32)
    flow_z=psz(flow); flow_ma_z=psz(flow_ma); base_z=psz(dow_round_base)
    vol_ma_z=psz(vol_ma); prev_z=psz(prev_flow); rebound_z=psz(rebound)
    # flow 대여소별 mean/std 저장 (역변환용, v3와 동일)
    fmn=np.zeros(N,dtype=np.float32); fsn=np.ones(N,dtype=np.float32)
    for j in range(N):
        v=flow[train_ts,j][mask[train_ts,j]==1]
        if len(v)>1: fmn[j]=v.mean(); fsn[j]=v.std()+1e-6

    dow_oh=np.eye(7,dtype=np.float32)[dow]; round_oh=np.eye(4,dtype=np.float32)[ridx]
    tlw=timeline.merge(weather,on=['service_date','round_id'],how='left')
    temp=tlw['temp_mean'].values.astype(np.float32); band=tlw['precip_band'].fillna('none').values
    tv=train_ts&~np.isnan(temp); tm=float(temp[tv].mean()); tsd=float(temp[tv].std()+1e-8)
    temp=np.where(np.isnan(temp),tm,temp); temp_z=(temp-tm)/tsd
    band_oh=np.zeros((T,3),dtype=np.float32)
    for i,b in enumerate(band): band_oh[i,PRECIP_BANDS.index(b) if b in PRECIP_BANDS else 0]=1.0

    # 조립: flow+ma+base+vol+prev+rebound(6) + 요일7 + 회차4 = 17
    F=6+7+4
    X=np.zeros((T,N,F),dtype=np.float32)
    X[:,:,0]=flow_z; X[:,:,1]=flow_ma_z; X[:,:,2]=base_z; X[:,:,3]=vol_ma_z
    X[:,:,4]=prev_z; X[:,:,5]=rebound_z          # NEW
    X[:,:,6:13]=dow_oh[:,None,:]; X[:,:,13:17]=round_oh[:,None,:]
    Xg=np.concatenate([temp_z[:,None],band_oh],axis=1).astype(np.float32)

    np.save(f'{OUT_DIR}/X_node.npy',X); np.save(f'{OUT_DIR}/X_global.npy',Xg)
    np.save(f'{OUT_DIR}/flow_mean_n.npy',fmn); np.save(f'{OUT_DIR}/flow_std_n.npy',fsn)
    json.dump({'per_station':True,'F_node':int(F),'F_global':4,
               'feat':['flow','ma','base','vol','prev','rebound','dow7','round4']},
              open(f'{OUT_DIR}/norm_stats.json','w'),ensure_ascii=False,indent=2)
    print(f"[v4] X_node {X.shape} (17채널: v3 15 + 반등2)")
    print(f"[v4] 추가: prev_flow(직전회차), rebound(반등방향)")

if __name__=='__main__':
    main()