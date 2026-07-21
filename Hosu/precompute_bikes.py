"""
전처리 확장: 자전거 단위 집계 미리 저장 (broken_score 속도 최적화)
=================================================
원본 CSV를 매번 읽지 않도록, 자전거별 집계를 한 번만 계산해 저장.
idle_days는 시점(ref_time)마다 달라지므로 last_used만 저장 -> 나중에 계산.

출력: processed/bike_features.parquet
  bike_id, last_used, total_trips, zero_dist_ratio, short_trip_ratio, last_station
"""
import pandas as pd, numpy as np, glob

OUT_DIR="processed"
ZERO_DIST_KM=0.1; SHORT_MIN=2.0

def _smart_read(path):
    for enc in ('utf-8-sig','cp949','euc-kr'):
        try:
            with open(path,'r',encoding=enc) as f: head=f.read(4096)
            break
        except UnicodeDecodeError: continue
    else:
        enc='cp949'
        with open(path,'r',encoding=enc,errors='replace') as f: head=f.read(4096)
    first=head.splitlines()[0] if head else ''
    sep='\t' if first.count('\t')>first.count(',') else ','
    return pd.read_csv(path,sep=sep,encoding=enc)

def main(data_glob):
    node_index=pd.read_csv(f'{OUT_DIR}/node_index.csv')
    target_ids=set(node_index['station_id'])
    files=sorted(glob.glob(data_glob))
    if not files: raise FileNotFoundError(f"'{data_glob}' 없음")
    frames=[]
    for f in files:
        df=_smart_read(f)
        df['대여일시']=pd.to_datetime(df['대여일시'],errors='coerce')
        df['반납일시']=pd.to_datetime(df['반납일시'],errors='coerce')
        df=df.dropna(subset=['대여일시','반납일시'])
        # 대상 40개 관련 이력만 (메모리 절약)
        df=df[df['대여_대여소ID'].isin(target_ids)|df['반납_대여소ID'].isin(target_ids)]
        frames.append(df)
    df=pd.concat(frames,ignore_index=True)
    print(f"[집계] 대상 관련 이력 {len(df)}행")

    g=df.groupby('자전거번호')
    feat=pd.DataFrame({
        'last_used':g['반납일시'].max(),
        'total_trips':g.size(),
        'zero_dist_ratio':g.apply(lambda x:(x['이용거리(km)']<ZERO_DIST_KM).mean(),include_groups=False),
        'short_trip_ratio':g.apply(lambda x:(x['이용시간(분)']<SHORT_MIN).mean(),include_groups=False),
    }).reset_index()
    last_station=df.sort_values('반납일시').groupby('자전거번호')['반납_대여소ID'].last()
    feat=feat.merge(last_station.rename('last_station'),on='자전거번호')
    feat=feat[feat['last_station'].isin(target_ids)].reset_index(drop=True)

    feat.to_parquet(f'{OUT_DIR}/bike_features.parquet',index=False)
    print(f"[저장] bike_features.parquet ({len(feat)}대) - idle_days는 시점마다 재계산")

if __name__=='__main__':
    main('./data/대전시*.csv')   # ★ 실제 경로로