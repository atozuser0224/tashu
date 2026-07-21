"""
대여소별 첫/마지막 등장 확인 -> 신설/폐쇄 대여소 탐지
결과로 마스크 전략(A vs B) 결정.
"""
import pandas as pd
import numpy as np

OUT_DIR = "processed"

def main():
    nf = pd.read_parquet(f'{OUT_DIR}/netflow.parquet')
    node_index = pd.read_csv(f'{OUT_DIR}/node_index.csv')

    # 각 대여소가 "이벤트가 있었던"(inflow+outflow>0) 첫/마지막 회차
    nf['active'] = (nf['inflow'] + nf['outflow']) > 0
    act = nf[nf['active']]

    span = (act.groupby('station_id')
              .agg(first_seen=('round_start','min'),
                   last_seen=('round_start','max'),
                   active_rounds=('round_start','size')).reset_index())

    data_start = nf['round_start'].min()
    data_end   = nf['round_start'].max()
    total_rounds = nf[['service_date','round_id']].drop_duplicates().shape[0]

    # 데이터 경계로부터 얼마나 떨어졌나 (일 단위)
    span['start_gap_days'] = (span['first_seen'] - data_start).dt.days
    span['end_gap_days']   = (data_end - span['last_seen']).dt.days
    span['coverage'] = span['active_rounds'] / total_rounds

    span = span.merge(node_index, on='station_id', how='right').sort_values('start_gap_days')

    print(f"데이터 전체 기간: {data_start.date()} ~ {data_end.date()} (총 {total_rounds}회차)")
    print(f"대여소 수: {len(span)}\n")

    # 신설 의심: 첫 등장이 시작보다 30일+ 늦음
    print("=== 신설 의심 (첫 등장이 데이터 시작보다 30일+ 늦음) ===")
    late = span[span['start_gap_days'] > 30]
    print("없음" if len(late)==0 else late[['station_id','first_seen','start_gap_days']].to_string(index=False))

    # 폐쇄 의심: 마지막 등장이 끝보다 30일+ 이름
    print("\n=== 폐쇄 의심 (마지막 등장이 데이터 끝보다 30일+ 이름) ===")
    early = span[span['end_gap_days'] > 30]
    print("없음" if len(early)==0 else early[['station_id','last_seen','end_gap_days']].to_string(index=False))

    # 커버리지 낮은 대여소 (활동 회차 비율 낮음 = 한적하거나 간헐 운영)
    print("\n=== 활동 커버리지 하위 5개 (전체 회차 중 이벤트 있던 비율) ===")
    print(span.nsmallest(5,'coverage')[['station_id','coverage','active_rounds']].to_string(index=False))

    print("\n=== 판정 ===")
    if len(late)==0 and len(early)==0:
        print(">> 신설/폐쇄 의심 대여소 없음. 마스크 전략 B(격자 빈칸=유효한 0) 안전.")
    else:
        print(">> 신설/폐쇄 의심 있음. 대여소별 first_seen 이후만 유효로 잡는 처리 필요.")

if __name__ == '__main__':
    main()