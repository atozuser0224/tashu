"""
타슈 STGNN - 인접행렬 A 구성
=================================================
od_matrix.parquet -> [N, N] 대칭 정규화 인접행렬 (A3TGCN용)

파이프라인:
  1) 가중치:  w(i,j) = log(1+trip_count) / (1+avg_km)   [혼합, 튜닝 없음]
  2) 대칭화:  (W + W^T) / 2
  3) self-loop: A = W_sym + I
  4) 대칭 정규화: D^(-1/2) A D^(-1/2)

산출물 (processed/):
  adjacency.npy         : [N, N] float32 정규화 인접행렬
  node_index.csv        : 행렬 인덱스 <-> station_id 매핑 (순서 고정용, 필수)
"""
import pandas as pd
import numpy as np
import os

OUT_DIR = "processed"

def build_adjacency(od, station_ids):
    """
    od: DataFrame[src, dst, trip_count, avg_min, avg_km]
    station_ids: 고정 순서의 대여소 ID 리스트 (station_master 순서)
    returns: (A_norm [N,N] float32, node_index DataFrame)
    """
    N = len(station_ids)
    idx = {sid: i for i, sid in enumerate(station_ids)}

    # ── 1) 가중치 행렬 W (비대칭, 방향 유지) ──
    W = np.zeros((N, N), dtype=np.float64)
    for _, r in od.iterrows():
        if r['src'] in idx and r['dst'] in idx:
            i, j = idx[r['src']], idx[r['dst']]
            if i == j:
                continue  # 자기순환은 3단계에서 I로 따로 추가
            W[i, j] = np.log1p(r['trip_count']) / (1.0 + r['avg_km'])

    # ── 2) 대칭화 ──
    W_sym = (W + W.T) / 2.0

    # ── 3) self-loop ──
    A = W_sym + np.eye(N)

    # ── 4) 대칭 정규화 D^(-1/2) A D^(-1/2) ──
    deg = A.sum(axis=1)
    d_inv_sqrt = np.zeros_like(deg)
    nz = deg > 0
    d_inv_sqrt[nz] = 1.0 / np.sqrt(deg[nz])
    D_inv_sqrt = np.diag(d_inv_sqrt)
    A_norm = D_inv_sqrt @ A @ D_inv_sqrt

    node_index = pd.DataFrame({'idx': range(N), 'station_id': station_ids})
    return A_norm.astype(np.float32), node_index

def main():
    od = pd.read_parquet(f'{OUT_DIR}/od_matrix.parquet')
    sm = pd.read_csv(f'{OUT_DIR}/station_master.csv')
    # station_master 순서를 행렬 인덱스 순서로 고정 (dist_km 정렬 순서 유지)
    station_ids = sm['station_id'].tolist()

    A_norm, node_index = build_adjacency(od, station_ids)

    np.save(f'{OUT_DIR}/adjacency.npy', A_norm)
    node_index.to_csv(f'{OUT_DIR}/node_index.csv', index=False)
    print(f"[저장] adjacency.npy shape={A_norm.shape}")
    print(f"[저장] node_index.csv ({len(node_index)}개 대여소)")

if __name__ == '__main__':
    main()