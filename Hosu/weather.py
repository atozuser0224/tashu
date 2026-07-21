"""
타슈 STGNN - 날씨 전처리 및 회차 집계
=================================================
기상청 시간별 대전 관측(여러 파일) -> 회차 구간별 전역(global) 날씨 피처.

핵심 처리:
  - 여러 파일(weather1, weather2...) 이어붙이고 시간 중복 제거
  - 강수량 NaN = 무강수 -> 0 (기상청 관례)
  - 기온 NaN = 진짜 결측 -> 시간 보간
  - 회차 집계: 기온=평균, 강수=합계
  - 강수 구간화: none/light/heavy
"""
import pandas as pd
import numpy as np
import glob
from preprocess import assign_round

def _read_one(path):
    # 인코딩 + 구분자(콤마/탭) 자동 감지
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

def _standardize_cols(w):
    """컬럼명이 조금 달라도(공백, 단위표기) 부분문자열로 매칭."""
    colmap={}
    for c in w.columns:
        cs=str(c).strip()
        if '일시' in cs or '시간' in cs or cs.lower()=='ts':
            colmap[c]='ts'
        elif '기온' in cs or 'temp' in cs.lower():
            colmap[c]='temp'
        elif '강수' in cs or 'precip' in cs.lower() or 'rain' in cs.lower():
            colmap[c]='precip'
    w=w.rename(columns=colmap)
    missing={'ts','temp','precip'}-set(w.columns)
    if missing:
        raise KeyError(f"날씨 필요 컬럼 못 찾음: {missing}. 실제 컬럼: {list(w.columns)}")
    return w

def load_weather(paths):
    """paths: 단일 경로, 경로 리스트, 또는 glob 패턴('weather*.csv') 모두 허용."""
    if isinstance(paths,str):
        files=sorted(glob.glob(paths)) if ('*' in paths or '?' in paths) else [paths]
    else:
        files=list(paths)
    if not files:
        raise FileNotFoundError(f"날씨 파일 없음: {paths}")
    print(f"[날씨] {len(files)}개 파일 로드: {[f.split('/')[-1] for f in files]}")

    frames=[_read_one(f) for f in files]
    w=pd.concat(frames,ignore_index=True)
    w=_standardize_cols(w)
    w['ts']=pd.to_datetime(w['ts'],errors='coerce')
    w=w.dropna(subset=['ts'])

    # 파일 경계에서 시간 중복 가능 -> 제거 (마지막 값 유지)
    n0=len(w)
    w=w.drop_duplicates(subset=['ts'],keep='last').sort_values('ts').reset_index(drop=True)
    if len(w)<n0:
        print(f"[날씨] 시간 중복 {n0-len(w)}건 제거 (파일 경계 겹침)")

    # 연속성 점검: 시간 간격이 1h가 아닌 구간 리포트
    gaps=w['ts'].diff().dropna()
    odd=gaps[gaps!=pd.Timedelta(hours=1)]
    if len(odd)>0:
        print(f"[날씨] 1시간 아닌 간격 {len(odd)}건 (결측/중복 의심). 예: {odd.head(3).tolist()}")

    # NaN 처리: 강수 -> 0(무강수), 기온 -> 보간
    w['precip']=w['precip'].fillna(0.0)
    w['temp']=w['temp'].interpolate(method='linear',limit_direction='both')
    print(f"[날씨] 최종 {len(w)}시간, 기간 {w['ts'].min()} ~ {w['ts'].max()}")
    return w

def aggregate_to_rounds(w):
    r=w['ts'].apply(assign_round)
    w=w.copy()
    w['service_date']=[x[0] for x in r]
    w['round_id']=[x[1] for x in r]
    g=(w.groupby(['service_date','round_id'])
         .agg(temp_mean=('temp','mean'),precip_sum=('precip','sum'),
              n_hours=('ts','size')).reset_index())
    def band(mm):
        if mm<0.1: return 'none'
        if mm<5.0: return 'light'
        return 'heavy'
    g['precip_band']=g['precip_sum'].apply(band)
    return g

if __name__=='__main__':
    # 두 파일 이어붙이기 테스트
    w=load_weather('./data/weather*.csv')   # weather1.csv, weather2.csv 자동 매칭
    g=aggregate_to_rounds(w)
    g.to_parquet('processed/weather_rounds.parquet',index=False)
    print('\n=== 회차별 집계 (앞부분) ===')
    print(g.head(8).to_string(index=False))
    print(f"\n[저장] weather_rounds.parquet ({len(g)}회차)")