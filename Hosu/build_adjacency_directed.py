"""
방향 인접행렬 (실험) - 대칭화 제거 + 회차별 OD
=================================================
기존: (W+Wᵀ)/2 로 대칭화 -> 방향 소실
변경: 비대칭 유지. A[i,j]=i→j 흐름. 모델에서 A와 Aᵀ 양방향 사용.
     + 회차별로 OD 따로 (출근/퇴근 방향 경향 분리)

정규화: 방향 그래프라 대칭정규화 대신 행 정규화(row-stochastic).
  각 행 i의 합=1 -> "i에서 나가는 흐름의 분포"

산출물 (processed/):
  adjacency_directed.npy       : [N,N] 통합 방향행렬 (회차 안 나눔 버전)
  adjacency_by_round.npy       : [4,N,N] 회차별 방향행렬 (A/B/C/D)
"""
import pandas as pd, numpy as np, os
OUT_DIR="processed"; ROUND_COLS=['A','B','C','D']

def build_directed(od, station_ids):
    """비대칭 방향 행렬 + 행 정규화 + self-loop."""
    N=len(station_ids); idx={s:i for i,s in enumerate(station_ids)}
    W=np.zeros((N,N),dtype=np.float64)
    for _,r in od.iterrows():
        if r['src'] in idx and r['dst'] in idx:
            i,j=idx[r['src']],idx[r['dst']]
            if i!=j: W[i,j]=np.log1p(r['trip_count'])/(1.0+r.get('avg_km',0))
    W=W+np.eye(N)  # self-loop
    # 행 정규화 (나가는 흐름 분포)
    rowsum=W.sum(1,keepdims=True); rowsum[rowsum==0]=1
    A=(W/rowsum).astype(np.float32)
    return A

def main():
    station_ids=pd.read_csv(f'{OUT_DIR}/node_index.csv')['station_id'].tolist()
    # 통합 OD (회차 무관)
    od=pd.read_parquet(f'{OUT_DIR}/od_matrix.parquet')
    A=build_directed(od,station_ids)
    np.save(f'{OUT_DIR}/adjacency_directed.npy',A)
    print(f"[방향행렬] 통합 {A.shape}, 행합≈1 확인: {A.sum(1)[:3].round(2)}")
    print(f"[방향행렬] 비대칭 확인: A[0,1]={A[0,1]:.3f} vs A[1,0]={A[1,0]:.3f}")

    # 회차별 OD (있으면)
    try:
        od_r=pd.read_parquet(f'{OUT_DIR}/od_matrix_by_round.parquet')
        As=[]
        for rc in ROUND_COLS:
            sub=od_r[od_r['round_id']==rc]
            As.append(build_directed(sub,station_ids) if len(sub) else np.eye(len(station_ids),dtype=np.float32))
        Ar=np.stack(As)
        np.save(f'{OUT_DIR}/adjacency_by_round.npy',Ar)
        print(f"[방향행렬] 회차별 {Ar.shape} (A/B/C/D)")
    except FileNotFoundError:
        print("[방향행렬] od_matrix_by_round.parquet 없음 -> 통합만 생성")
        print("           (회차별 OD는 preprocess에서 round_id별 집계 필요)")

if __name__=='__main__':
    main()