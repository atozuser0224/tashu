"""
타슈 STGNN - 텐서 조립 1단계: flow 격자화 + 노드정렬 + 마스킹
=================================================
netflow.parquet -> [T, N] net_flow 격자 + [T, N] 마스크 + 시간축 메타

핵심:
  - 모든 (타임스텝 x 노드) 격자를 채움. 이벤트 없던 칸은 net_flow=0
  - 노드축(N) 순서 = node_index.csv 순서로 고정 (인접행렬과 정합!)
  - 타임스텝(T) = (service_date, round_id)를 시간순 정렬
  - 결측 마스킹: is_missing 회차 + 격자 빈칸을 mask=0으로
"""
import pandas as pd
import numpy as np

OUT_DIR = "processed"
ROUND_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}  # 하루 내 회차 순서

def build_flow_grid():
    nf = pd.read_parquet(f'{OUT_DIR}/netflow.parquet')
    node_index = pd.read_csv(f'{OUT_DIR}/node_index.csv')

    # 노드축 순서 고정 (인접행렬과 반드시 동일)
    station_ids = node_index['station_id'].tolist()
    sid_to_col = {s: i for i, s in enumerate(station_ids)}
    N = len(station_ids)

    # 타임스텝축: (service_date, round_id) 유니크 조합을 시간순 정렬
    nf['round_ord'] = nf['round_id'].map(ROUND_ORDER)
    timeline = (nf[['service_date', 'round_id', 'round_ord', 'period']]
                .drop_duplicates()
                .sort_values(['service_date', 'round_ord'])
                .reset_index(drop=True))
    T = len(timeline)
    ts_to_row = {(r.service_date, r.round_id): i for i, r in timeline.iterrows()}

    # 빈 격자 초기화: flow=0
    flow = np.zeros((T, N), dtype=np.float32)

    for _, r in nf.iterrows():
        ti = ts_to_row[(r['service_date'], r['round_id'])]
        ni = sid_to_col[r['station_id']]
        flow[ti, ni] = r['net_flow']

    # ── 마스크 전략 B + 신설 대여소 처리 ──
    # 기본: 전체 격자 유효(1). 빈칸의 0은 "유효한 순변동 0"으로 해석.
    mask = np.ones((T, N), dtype=np.float32)

    # (1) 대여소별 first_seen 이전은 무효 (그땐 대여소 미존재 = 신설 전)
    nf['active'] = (nf['inflow'] + nf['outflow']) > 0
    first_seen = nf[nf['active']].groupby('station_id')['round_start'].min()
    ts_order = timeline.set_index(['service_date','round_id'])  # for lookup
    # 각 대여소 first_seen에 해당하는 타임스텝 인덱스 찾기
    tl = timeline.reset_index().rename(columns={'index':'ti'})
    tl_start = tl.merge(nf[['service_date','round_id','round_start']].drop_duplicates(),
                        on=['service_date','round_id'], how='left')
    start_to_ti = dict(zip(tl_start['round_start'], tl_start['ti']))
    for sid, fs in first_seen.items():
        if sid not in sid_to_col: continue
        ni = sid_to_col[sid]
        # first_seen 타임스텝 인덱스 (없으면 근사: 그 이전 전부 무효)
        fs_ti = start_to_ti.get(fs, None)
        if fs_ti is None:
            fs_ti = tl_start[tl_start['round_start'] >= fs]['ti'].min()
        if pd.notna(fs_ti):
            mask[:int(fs_ti), ni] = 0.0   # 신설 전 구간 무효

    # (2) is_missing 장애 구간 전체 행 무효
    missing_ts = nf[nf['is_missing']][['service_date','round_id']].drop_duplicates()
    for _, r in missing_ts.iterrows():
        if (r['service_date'], r['round_id']) in ts_to_row:
            mask[ts_to_row[(r['service_date'], r['round_id'])], :] = 0.0

    # 저장
    np.save(f'{OUT_DIR}/flow.npy', flow)
    np.save(f'{OUT_DIR}/mask.npy', mask)
    timeline.to_csv(f'{OUT_DIR}/timeline.csv', index=False)

    return flow, mask, timeline, station_ids

if __name__ == '__main__':
    flow, mask, timeline, station_ids = build_flow_grid()
    print(f"[격자] flow shape = {flow.shape}  (T={flow.shape[0]}, N={flow.shape[1]})")
    print(f"[격자] mask 유효비율 = {mask.mean():.3f}")
    print(f"[격자] flow 범위 = {flow.min():.0f} ~ {flow.max():.0f}, 평균 {flow.mean():.2f}")
    print(f"[타임라인] period 분포:")
    print(timeline['period'].value_counts().to_string())
    print(f"\n[검증] 노드축 순서 = node_index 순서 (인접행렬 정합)")
    print(f"  첫 3개 노드: {station_ids[:3]}")