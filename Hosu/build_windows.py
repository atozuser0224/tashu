"""
타슈 STGNN - 텐서 조립 3단계: 슬라이딩 윈도우 학습셋
=================================================
X_node[T,N,F], X_global[T,Fg], mask[T,N], timeline
  -> 입력 8회차 -> 타깃 다음 1회차 flow_z 쌍 생성

윈도우 유효 규칙 (하나라도 위반 시 그 윈도우 버림):
  - 입력 8스텝 + 타깃 1스텝이 모두 같은 period(train끼리/test끼리)
  - 타깃 스텝의 노드 마스크가 유효(결측/신설전 타깃은 학습 제외)
  - 입력 구간에 장애(전체행 mask=0) 스텝이 없을 것

산출 (processed/):
  train_X_node[B,W,N,F], train_X_global[B,W,Fg], train_y[B,N], train_ymask[B,N]
  test_*  동일 구조
  (W=8=윈도우 길이)
"""
import pandas as pd
import numpy as np

OUT_DIR = "processed"
WINDOW = 8   # T=8 입력 회차

def main():
    X_node = np.load(f'{OUT_DIR}/X_node.npy')      # [T,N,F]
    X_global = np.load(f'{OUT_DIR}/X_global.npy')  # [T,Fg]
    mask = np.load(f'{OUT_DIR}/mask.npy')          # [T,N]
    timeline = pd.read_csv(f'{OUT_DIR}/timeline.csv', parse_dates=['service_date'])
    T, N, F = X_node.shape
    period = timeline['period'].values
    flow_z = X_node[:,:,0]   # 타깃으로 쓸 표준화 flow (채널0)

    # 입력 구간 전체가 무효인 스텝(장애) 판정: 그 스텝의 모든 노드 mask=0
    row_all_missing = (mask.sum(axis=1) == 0)   # [T] True=장애행

    buckets = {'train':{'Xn':[],'Xg':[],'y':[],'ym':[]},
               'test' :{'Xn':[],'Xg':[],'y':[],'ym':[]}}

    for t in range(WINDOW, T):
        in_slice = slice(t-WINDOW, t)   # 입력 8스텝
        tgt = t                          # 타깃 1스텝

        # 규칙1: 입력+타깃 같은 period
        segs = period[t-WINDOW:t+1]
        if not (segs == segs[0]).all():
            continue
        p = segs[0]

        # 규칙2: 입력 구간에 장애행 없을 것
        if row_all_missing[t-WINDOW:t].any():
            continue

        # 타깃 마스크 (노드별 유효). 전부 무효면 버림
        ym = mask[tgt].copy()   # [N]
        if ym.sum() == 0:
            continue

        buckets[p]['Xn'].append(X_node[in_slice])       # [W,N,F]
        buckets[p]['Xg'].append(X_global[in_slice])     # [W,Fg]
        buckets[p]['y'].append(flow_z[tgt])             # [N]
        buckets[p]['ym'].append(ym)                     # [N]

    for p in ['train','test']:
        if len(buckets[p]['Xn'])==0:
            print(f"[{p}] 윈도우 0개 (데이터 부족)"); continue
        Xn=np.stack(buckets[p]['Xn']).astype(np.float32)
        Xg=np.stack(buckets[p]['Xg']).astype(np.float32)
        y =np.stack(buckets[p]['y']).astype(np.float32)
        ym=np.stack(buckets[p]['ym']).astype(np.float32)
        np.save(f'{OUT_DIR}/{p}_X_node.npy',Xn)
        np.save(f'{OUT_DIR}/{p}_X_global.npy',Xg)
        np.save(f'{OUT_DIR}/{p}_y.npy',y)
        np.save(f'{OUT_DIR}/{p}_ymask.npy',ym)
        print(f"[{p}] 윈도우 {Xn.shape[0]}개 | X_node{Xn.shape} X_global{Xg.shape} y{y.shape}")

if __name__=='__main__':
    main()