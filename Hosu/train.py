"""
STGNN 분류 학습 (부족/정상/과잉 3분류)
=================================================
기존 train/test 윈도우의 y(flow_z 회귀타깃)를 3분류 라벨로 변환해 학습.
- 라벨: z < -0.43 -> 부족(0), z > 0.43 -> 과잉(2), 중간 -> 정상(1)
- 손실: CrossEntropy (마스크 적용)
- 평가: 정확도 + 클래스별 + 기준선(다수클래스, 직전회차)
"""
import torch, torch.nn as nn, numpy as np, time
from model_cls_directed import A3TGCN_Dir

OUT_DIR="processed"
HIDDEN=48; LR=0.003; MAX_EPOCH=200; PATIENCE=15; BATCH=64
LO,HI=-0.43,0.43   # 3분류 경계 (대여소별 z 기준)

def pick_device():
    if hasattr(torch,'xpu') and torch.xpu.is_available(): return 'xpu'
    if torch.cuda.is_available(): return 'cuda'
    return 'cpu'

def to_class(z):
    c=torch.ones_like(z,dtype=torch.long)
    c[z<LO]=0; c[z>HI]=2; return c

def load(split):
    return [torch.tensor(np.load(f'{OUT_DIR}/{split}_{n}.npy')) for n in ['X_node','X_global','y','ymask']]

def main():
    device=pick_device(); print(f"[device] {device}")
    A=torch.tensor(np.load(f'{OUT_DIR}/adjacency_directed.npy')).float().to(device)
    Xn_tr,Xg_tr,y_tr,m_tr=load('train'); Xn_te,Xg_te,y_te,m_te=load('test')
    # 회귀타깃 y(flow_z) -> 클래스
    c_tr=to_class(y_tr); c_te=to_class(y_te)
    F,Fg=Xn_tr.shape[-1],Xg_tr.shape[-1]
    n=len(Xn_tr); n_val=max(1,n//10); n_trn=n-n_val
    def dev(*ts): return [t.to(device) for t in ts]

    model=A3TGCN_Dir(F,Fg,hidden=HIDDEN).to(device)
    opt=torch.optim.Adam(model.parameters(),lr=LR)
    # 클래스 가중치: 빈도 역수의 WEIGHT_POWER 승 (0=가중치없음, 1=완전역수)
    WEIGHT_POWER=0.3   # 0.5=완만한 보정 (1.0은 과하게 소수클래스 편향)
    counts=torch.bincount(c_tr[m_tr.bool()].reshape(-1),minlength=3).float()
    inv=(counts.sum()/(counts+1e-6))**WEIGHT_POWER
    weights=(inv/inv.sum()*3).to(device)
    print(f"[클래스 분포] 부족={int(counts[0])} 정상={int(counts[1])} 과잉={int(counts[2])}")
    print(f"[클래스 가중치 p={WEIGHT_POWER}] 부족={weights[0]:.2f} 정상={weights[1]:.2f} 과잉={weights[2]:.2f}")
    lossf=nn.CrossEntropyLoss(weight=weights,reduction='none')
    best=0; best_state=None; wait=0; t0=time.time()

    def masked_ce(logits,y,m):
        # logits[B,N,3], y[B,N], m[B,N]
        l=lossf(logits.reshape(-1,3),y.reshape(-1)).reshape(y.shape)
        return (l*m).sum()/(m.sum()+1e-8)
    def acc(logits,y,m):
        pred=logits.argmax(-1)
        correct=((pred==y).float()*m).sum()
        return (correct/(m.sum()+1e-8)).item()
    def balanced_acc(logits,y,m):
        # 클래스별 정확도의 평균 (불균형·도망에 강건한 지표)
        pred=logits.argmax(-1); mb=m.bool()
        accs=[]
        for k in range(3):
            mk=(y==k)&mb
            if mk.sum()>0: accs.append((((pred==y)&mk).sum().float()/mk.sum()).item())
        return sum(accs)/len(accs) if accs else 0.0

    for ep in range(MAX_EPOCH):
        model.train(); perm=torch.randperm(n_trn); tr_l=0
        for i in range(0,n_trn,BATCH):
            idx=perm[i:i+BATCH]
            xn,xg,y,m=dev(Xn_tr[idx],Xg_tr[idx],c_tr[idx],m_tr[idx])
            opt.zero_grad(); loss=masked_ce(model(xn,xg,A),y,m)
            loss.backward(); opt.step(); tr_l+=loss.item()*len(idx)
        model.eval()
        with torch.no_grad():
            xn,xg,y,m=dev(Xn_tr[n_trn:],Xg_tr[n_trn:],c_tr[n_trn:],m_tr[n_trn:])
            logits_v=model(xn,xg,A)
            va=balanced_acc(logits_v,y,m)   # 클래스 균형 정확도 기준
        if va>best+1e-4: best=va; best_state={k:v.cpu().clone() for k,v in model.state_dict().items()}; wait=0
        else:
            wait+=1
            if wait>=PATIENCE: print(f"[early stop] ep {ep}, best_val_bacc {best:.3f}"); break
        if ep%10==0: print(f"  ep {ep:3d} | train_loss {tr_l/n_trn:.4f} | val_bacc {va:.3f}")

    model.load_state_dict(best_state); print(f"[학습완료] {time.time()-t0:.1f}s")
    model.eval()
    with torch.no_grad():
        logits=model(*dev(Xn_te,Xg_te),A).cpu()
    pred=logits.argmax(-1); mm=m_te.bool()
    y=c_te
    model_acc=((pred==y).float()*m_te).sum()/(m_te.sum()+1e-8)
    # 기준선1: 다수 클래스(정상=1) 항상 예측
    major=(torch.ones_like(y)==y).float()
    base_major=(major*m_te).sum()/(m_te.sum()+1e-8)
    # 클래스별 정확도
    print(f"\n[분류 결과]")
    print(f"  전체 정확도: {model_acc:.3f}")
    print(f"  기준선(항상 정상): {base_major:.3f}")
    bacc_list=[]
    for k,name in [(0,'부족'),(1,'정상'),(2,'과잉')]:
        mask_k=(y==k)&mm
        if mask_k.sum()>0:
            acc_k=(((pred==y)&mask_k).sum().float()/mask_k.sum()).item()
            bacc_list.append(acc_k)
            print(f"  '{name}' 클래스 정확도: {acc_k:.3f} (n={int(mask_k.sum())})")
    print(f"  균형 정확도(클래스평균): {sum(bacc_list)/len(bacc_list):.3f}  <- 핵심 지표")
    torch.save({'state':best_state},f'{OUT_DIR}/a3tgcn_dir.pt')

if __name__=='__main__':
    main()