"""
분류 모델 혼동행렬 분석 - '어떻게 틀리나'로 실용성 평가
치명적 오류(부족<->과잉) vs 경미한 오류(정상과 혼동) 구분
"""
import torch, numpy as np
from model_cls_directed import A3TGCN_Dir
OUT_DIR="processed"; LO,HI=-0.43,0.43
def to_class(z):
    c=torch.ones_like(z,dtype=torch.long); c[z<LO]=0; c[z>HI]=2; return c
def load(s): return [torch.tensor(np.load(f'{OUT_DIR}/{s}_{n}.npy')) for n in ['X_node','X_global','y','ymask']]

A=torch.tensor(np.load(f'{OUT_DIR}/adjacency_directed.npy')).float()
Xn,Xg,y,m=load('test'); c=to_class(y)
model=A3TGCN_Dir(Xn.shape[-1],Xg.shape[-1],hidden=48)
model.load_state_dict(torch.load(f'{OUT_DIR}/a3tgcn_dir.pt',map_location='cpu')['state']); model.eval()
with torch.no_grad(): pred=model(Xn,Xg,A).argmax(-1)
mb=m.bool(); yt=c[mb].numpy(); pt=pred[mb].numpy()

names=['부족','정상','과잉']
cm=np.zeros((3,3),dtype=int)
for t,p in zip(yt,pt): cm[t,p]+=1
print("혼동행렬 (행=실제, 열=예측):")
print("         예측→ 부족   정상   과잉")
for i in range(3):
    row=cm[i]; print(f"  실제 {names[i]}:  {row[0]:5d} {row[1]:6d} {row[2]:6d}  (합 {row.sum()})")
# 치명적 오류: 부족<->과잉
fatal=cm[0,2]+cm[2,0]
total=cm.sum()
adjacent=cm[0,1]+cm[1,0]+cm[1,2]+cm[2,1]  # 정상과의 혼동
correct=cm[0,0]+cm[1,1]+cm[2,2]
print(f"\n정확: {correct}/{total} = {correct/total:.1%}")
print(f"경미한 오류(정상과 혼동): {adjacent}/{total} = {adjacent/total:.1%}")
print(f"치명적 오류(부족<->과잉): {fatal}/{total} = {fatal/total:.1%}  <- 이게 낮아야 실용적")
print(f"\n부족을 과잉으로: {cm[0,2]}건 / 과잉을 부족으로: {cm[2,0]}건")