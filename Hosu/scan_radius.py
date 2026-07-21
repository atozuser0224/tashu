"""
충남대 반경별 대여소 개수 스캐너
전처리 본 파이프라인 돌리기 전에, 반경을 얼마로 잡아야
대여소가 30~50개 걸리는지 먼저 확인하는 용도.

사용법:
  1) CNU_LAT/LNG를 실제 충남대 기준점으로 맞춘다 (아래 주석 참고)
  2) DATA_GLOB를 실제 CSV 폴더 경로로 바꾼다
  3) python3 scan_radius.py
"""
import pandas as pd
import numpy as np
import glob

# ── 여기 두 개만 님이 맞추세요 ─────────────────────────
DATA_GLOB = "/mnt/user-data/uploads/*.csv"   # 실제 CSV 경로로 변경
CNU_LAT, CNU_LNG = 36.3665, 127.3445          # 충남대 기준점 (검증 필요)
# 기준점을 바꾸고 싶으면: 지도에서 원하는 지점 우클릭 -> 좌표 복사.
# 정문/공대/농대 등 어디를 중심으로 볼지에 따라 걸리는 대여소가 달라짐.
# ──────────────────────────────────────────────────────

RADII = [0.8, 1.0, 1.25, 1.5, 1.75, 2.0, 2.5, 3.0]

def load_stations(pattern):
    """모든 CSV에서 대여/반납 대여소 좌표만 가볍게 추출."""
    stations = {}
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"[!] '{pattern}' 에 파일이 없습니다. DATA_GLOB 경로를 확인하세요.")
        return None
    for f in files:
        # 인코딩 자동 시도: utf-8 실패 시 cp949
        try:
            df = pd.read_csv(f, sep='\t', usecols=[
                '대여_대여소ID','대여_대여소명','대여_X좌표','대여_Y좌표','대여_구',
                '반납_대여소ID','반납_대여소명','반납_X좌표','반납_Y좌표','반납_구'])
        except UnicodeDecodeError:
            df = pd.read_csv(f, sep='\t', encoding='cp949', usecols=[
                '대여_대여소ID','대여_대여소명','대여_X좌표','대여_Y좌표','대여_구',
                '반납_대여소ID','반납_대여소명','반납_X좌표','반납_Y좌표','반납_구'])
        for pfx in ['대여','반납']:
            for _, r in df[[f'{pfx}_대여소ID',f'{pfx}_대여소명',f'{pfx}_X좌표',f'{pfx}_Y좌표',f'{pfx}_구']].dropna().iterrows():
                sid = r[f'{pfx}_대여소ID']
                if sid not in stations:
                    stations[sid] = (r[f'{pfx}_X좌표'], r[f'{pfx}_Y좌표'], r[f'{pfx}_대여소명'], r[f'{pfx}_구'])
    m = pd.DataFrame([(k,v[0],v[1],v[2],v[3]) for k,v in stations.items()],
                     columns=['station_id','lat','lng','name','gu'])
    return m

def haversine_km(lat, lng):
    R=6371
    dlat=np.radians(lat-CNU_LAT); dlng=np.radians(lng-CNU_LNG)
    a=(np.sin(dlat/2)**2 + np.cos(np.radians(CNU_LAT))*np.cos(np.radians(lat))*np.sin(dlng/2)**2)
    return 2*R*np.arcsin(np.sqrt(a))

if __name__ == '__main__':
    m = load_stations(DATA_GLOB)
    if m is None: raise SystemExit
    # 좌표 축 자동 점검
    print(f"[좌표 점검] lat(={CNU_LAT} 근처여야) 범위: {m['lat'].min():.3f}~{m['lat'].max():.3f}")
    print(f"[좌표 점검] lng(={CNU_LNG} 근처여야) 범위: {m['lng'].min():.3f}~{m['lng'].max():.3f}")
    if not (35 < m['lat'].mean() < 37):
        print("  [!] lat이 36 근처가 아님 -> X/Y 축이 바뀐 것일 수 있음. preprocess.py의 lat/lng 매핑 확인!")
    print(f"\n전체 고유 대여소 수: {len(m)}")
    m['dist_km'] = haversine_km(m['lat'].values, m['lng'].values)
    print(f"\n{'반경(km)':>8} | {'걸리는 대여소 수':>14}")
    print("-"*30)
    for r in RADII:
        cnt = (m['dist_km'] <= r).sum()
        flag = "  <- 30~50개 구간" if 30 <= cnt <= 50 else ""
        print(f"{r:>8} | {cnt:>14}{flag}")
    # 가장 가까운 20개 미리보기
    print("\n가장 가까운 대여소 20개:")
    print(m.nsmallest(20,'dist_km')[['station_id','name','gu','dist_km']].to_string(index=False))