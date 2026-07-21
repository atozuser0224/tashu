"""
타슈 진짜재고 프로젝트 - 전처리 파이프라인 (최종)
=================================================
대여이력 CSV -> 충남대 1km 40개 대여소 대상 산출물 저장.
날씨 미포함 (STGNN 텐서 조립 단계에서 round_start/end 기준 별도 join).

산출물 (processed/):
  netflow.parquet        : 대여소 x 서비스일 x 회차 -> in/out/net_flow (+round_start/end, is_missing)
  station_master.csv     : 40개 대여소 좌표/구/동/name
  od_matrix.parquet      : 40 내부 이동 빈도 (인접행렬 재료)

수정 필요한 곳: main()의 DATA_GLOB, CNU 기준점, RADIUS_KM
"""
import pandas as pd
import numpy as np
import glob, os

# ── 설정 ──────────────────────────────────────────────
DATA_GLOB = "./data/대전시*.csv"   # ★ 실제 CSV 폴더 경로
CNU_LAT, CNU_LNG = 36.3628, 127.3448          # ★ 충남대 기준점
RADIUS_KM = 1.0                                # ★ 확정된 반경
OUT_DIR = "processed"

ROUND_START_HOUR = {"A": 7.0, "B": 11.5, "C": 16.0, "D": 3.0}
ROUND_END_HOUR   = {"A": 11.5, "B": 16.0, "C": 27.0, "D": 7.0}
KNOWN_MISSING = [("2025-02-26","2025-02-28"), ("2025-03-01","2025-03-03")]

# ── 기간 분할: 26.03을 시연/test 홀드아웃으로 격리 ──
# 인접행렬·정규화 통계는 train 기간만으로 만들어야 누수 없음
TEST_START = pd.Timestamp('2026-03-01')
TEST_END   = pd.Timestamp('2026-03-31 23:59:59')

def period_of(service_date):
    if TEST_START <= service_date <= TEST_END:
        return 'test'
    return 'train'

# ── 견고한 CSV 읽기 (인코딩·구분자 자동) ───────────────
def _smart_read(path, usecols=None):
    for enc in ('utf-8-sig','cp949','euc-kr'):
        try:
            with open(path,'r',encoding=enc) as f: head=f.read(4096)
            break
        except UnicodeDecodeError: continue
    else:
        enc='cp949'
        with open(path,'r',encoding=enc,errors='replace') as f: head=f.read(4096)
    first=head.splitlines()[0] if head else ''
    sep='\t' if first.count('\t')>=first.count(',') else ','
    return pd.read_csv(path, sep=sep, encoding=enc, usecols=usecols)

def load_csv(path):
    df=_smart_read(path); n0=len(df)
    df['대여일시']=pd.to_datetime(df['대여일시'], errors='coerce')  # 포맷 자동감지
    df['반납일시']=pd.to_datetime(df['반납일시'], errors='coerce')
    df=df.dropna(subset=['대여일시','반납일시']); n1=len(df)
    if n1<n0: print(f"  [load] {os.path.basename(path)}: 파싱실패 {n0-n1}행 제거 (남은 {n1})")
    if n1==0: raise ValueError(f"{path}: 전 행 날짜 파싱 실패")
    return df

def load_many(pattern):
    files=sorted(glob.glob(pattern))
    if not files: raise FileNotFoundError(f"'{pattern}'에 파일 없음")
    print(f"[로드] {len(files)}개 파일")
    return pd.concat([load_csv(p) for p in files], ignore_index=True)

# ── 회차 라벨링 ───────────────────────────────────────
def assign_round(ts):
    h=ts.hour+ts.minute/60.0
    if 3.0<=h<7.0:   return ts.normalize(),"D"
    if 7.0<=h<11.5:  return ts.normalize(),"A"
    if 11.5<=h<16.0: return ts.normalize(),"B"
    if 16.0<=h<24.0: return ts.normalize(),"C"
    return (ts.normalize()-pd.Timedelta(days=1)),"C"

def round_window(sd, rid):
    return sd+pd.Timedelta(hours=ROUND_START_HOUR[rid]), sd+pd.Timedelta(hours=ROUND_END_HOUR[rid])

def is_missing_date(d):
    if not isinstance(d,pd.Timestamp) or pd.isna(d): return False
    return any(pd.Timestamp(s)<=d<=pd.Timestamp(e) for s,e in KNOWN_MISSING)

# ── melt ──────────────────────────────────────────────
def melt_events(df):
    rent=pd.DataFrame({'station_id':df['대여_대여소ID'],'ts':df['대여일시'],'event':'out',
        'lat':df['대여_X좌표'],'lng':df['대여_Y좌표'],'name':df['대여_대여소명'],
        'gu':df['대여_구'],'dong':df['대여_동']})
    ret=pd.DataFrame({'station_id':df['반납_대여소ID'],'ts':df['반납일시'],'event':'in',
        'lat':df['반납_X좌표'],'lng':df['반납_Y좌표'],'name':df['반납_대여소명'],
        'gu':df['반납_구'],'dong':df['반납_동']})
    ev=pd.concat([rent,ret],ignore_index=True)
    r=ev['ts'].apply(assign_round)
    ev['service_date']=[x[0] for x in r]; ev['round_id']=[x[1] for x in r]
    return ev

def build_netflow(ev):
    g=(ev.groupby(['station_id','service_date','round_id','event']).size()
         .unstack('event',fill_value=0).reset_index())
    for c in ['in','out']:
        if c not in g: g[c]=0
    g=g.rename(columns={'in':'inflow','out':'outflow'})
    g['net_flow']=g['inflow']-g['outflow']
    win=g.apply(lambda r:round_window(r['service_date'],r['round_id']),axis=1)
    g['round_start']=[w[0] for w in win]; g['round_end']=[w[1] for w in win]
    g['is_missing']=g['service_date'].apply(is_missing_date)
    g['period']=g['service_date'].apply(period_of)
    return g.sort_values(['station_id','round_start']).reset_index(drop=True)

def build_station_master(ev):
    def mode1(s):
        m=s.mode(); return m.iloc[0] if len(m) else s.iloc[0]
    return (ev.groupby('station_id').agg(name=('name',mode1),lat=('lat','median'),
            lng=('lng','median'),gu=('gu',mode1),dong=('dong',mode1)).reset_index())

def build_od(df, target_ids):
    # 인접행렬은 train 기간만으로 (26.03 test 누수 방지). 대여일시 기준 분할.
    d=df[df['대여_대여소ID'].isin(target_ids) & df['반납_대여소ID'].isin(target_ids)]
    d=d[~((d['대여일시']>=TEST_START) & (d['대여일시']<=TEST_END))]
    return (d.groupby(['대여_대여소ID','반납_대여소ID'])
             .agg(trip_count=('자전거번호','size'),avg_min=('이용시간(분)','mean'),
                  avg_km=('이용거리(km)','mean')).reset_index()
             .rename(columns={'대여_대여소ID':'src','반납_대여소ID':'dst'}))

def haversine_km(lat,lng):
    R=6371;dlat=np.radians(lat-CNU_LAT);dlng=np.radians(lng-CNU_LNG)
    a=np.sin(dlat/2)**2+np.cos(np.radians(CNU_LAT))*np.cos(np.radians(lat))*np.sin(dlng/2)**2
    return 2*R*np.arcsin(np.sqrt(a))

def main():
    os.makedirs(OUT_DIR,exist_ok=True)
    df=load_many(DATA_GLOB)
    print(f"[로드] 총 {len(df)}행")
    ev=melt_events(df)

    # 좌표 축 점검
    if not (35<ev['lat'].mean()<37):
        print("  [!] lat 평균이 36 근처가 아님 -> X/Y 축 확인 필요")

    sm_all=build_station_master(ev)
    sm_all['dist_km']=haversine_km(sm_all['lat'].values,sm_all['lng'].values)
    sm=sm_all[sm_all['dist_km']<=RADIUS_KM].sort_values('dist_km').reset_index(drop=True)
    target_ids=set(sm['station_id'])
    print(f"[필터] 충남대 {RADIUS_KM}km 내 대여소: {len(target_ids)}개")

    # net_flow: 대상 대여소 이벤트 (상대 무관)
    ev_t=ev[ev['station_id'].isin(target_ids)]
    nf=build_netflow(ev_t)
    # OD: 내부 이동만
    od=build_od(df,target_ids)

    nf.to_parquet(f'{OUT_DIR}/netflow.parquet',index=False)
    od.to_parquet(f'{OUT_DIR}/od_matrix.parquet',index=False)
    sm.to_csv(f'{OUT_DIR}/station_master.csv',index=False,encoding='utf-8-sig')
    tr=(nf['period']=='train').sum(); te=(nf['period']=='test').sum()
    print(f"[저장] netflow {len(nf)}행 (train {tr} / test {te}), od {len(od)}행(train만), master {len(sm)}개")
    print(f"[저장] -> {OUT_DIR}/  (인접행렬은 od_matrix.parquet=train기간으로 생성됨)")

if __name__=='__main__':
    main()