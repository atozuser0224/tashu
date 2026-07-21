"""
STGNN 학습 v2: Huber 손실 + 대여소별 역변환
=================================================
변경점:
  - MSE -> Huber (평균 도망 완화, 큰 값 예측 벌점 감소)
  - 역변환: 대여소별 mean/std (flow_mean_n, flow_std_n)
  - 예측 std / 기준선 비교를 항상 출력 (진단 상시화)
"""
import torch, torch.nn as nn, numpy as np, json, time
from model import A3TGCN

OUT_DIR="processed"
HIDDEN=48; LR=0.003; MAX_EPOCH=200; PATIENCE=15; BATCH=64
HUBER_DELTA=1.0

def pick_device():
    #if hasattr(torch,'xpu') and torch.xpu.is_available(): return 'xpu'
    if torch.cuda.is_available(): return 'cuda'
    return 'cpu'

def masked_huber(yhat,y,m,delta=HUBER_DELTA):
    err=yhat-y
    absr=err.abs()
    quad=torch.minimum(absr,torch.tensor(delta,device=err.device))
    lin=absr-quad
    loss=(0.5*quad**2+delta*lin)*m
    return loss.sum()/(m.sum()+1e-8)

def load(split):
    return [torch.tensor(np.load(f'{OUT_DIR}/{split}_{n}.npy')) for n in ['X_node','X_global','y','ymask']]

def main():
    device=pick_device(); print(f"[device] {device}")
    A=torch.tensor(np.load(f'{OUT_DIR}/adjacency.npy')).float().to(device)
    fmn=torch.tensor(np.load(f'{OUT_DIR}/flow_mean_n.npy'))  # [N] 대여소별
    fsn=torch.tensor(np.load(f'{OUT_DIR}/flow_std_n.npy'))

    Xn_tr,Xg_tr,y_tr,m_tr=load('train')
    Xn_te,Xg_te,y_te,m_te=load('test')
    F,Fg=Xn_tr.shape[-1],Xg_tr.shape[-1]
    n=len(Xn_tr); n_val=max(1,n//10); n_trn=n-n_val
    def dev(*ts): return [t.to(device) for t in ts]

    model=A3TGCN(F,Fg,hidden=HIDDEN).to(device)
    opt=torch.optim.Adam(model.parameters(),lr=LR)
    best=float('inf'); best_state=None; wait=0; t0=time.time()

    for ep in range(MAX_EPOCH):
        model.train(); perm=torch.randperm(n_trn)
        tr_sum=0.0
        for i in range(0,n_trn,BATCH):
            idx=perm[i:i+BATCH]
            xn,xg,y,m=dev(Xn_tr[idx],Xg_tr[idx],y_tr[idx],m_tr[idx])
            opt.zero_grad()
            loss=masked_huber(model(xn,xg,A),y,m)
            loss.backward(); opt.step()
            tr_sum+=loss.item()*len(idx)
        tr_loss=tr_sum/n_trn
        model.eval()
        with torch.no_grad():
            xn,xg,y,m=dev(Xn_tr[n_trn:],Xg_tr[n_trn:],y_tr[n_trn:],m_tr[n_trn:])
            val=masked_huber(model(xn,xg,A),y,m).item()
        if val<best-1e-5: best=val; best_state={k:v.cpu().clone() for k,v in model.state_dict().items()}; wait=0
        else:
            wait+=1
            if wait>=PATIENCE: print(f"[early stop] ep {ep}, best_val {best:.4f}"); break
        if ep%10==0: print(f"  ep {ep:3d} | train {tr_loss:.4f} | val {val:.4f}")

    model.load_state_dict(best_state)
    print(f"[학습완료] {time.time()-t0:.1f}s")

    # test: 대여소별 역변환
    model.eval()
    with torch.no_grad():
        yhat=model(*dev(Xn_te,Xg_te),A).cpu()
    def inv(z): return z*fsn[None,:]+fmn[None,:]   # 대여소별 역변환
    pred=inv(yhat); true=inv(y_te); mm=m_te
    def mae(p): return ((p-true).abs()*mm).sum()/(mm.sum()+1e-8)

    zero=inv(torch.zeros_like(y_te))
    persist=inv(Xn_te[:,-1,:,0])
    print(f"\n[예측분포] 예측 std={pred.std():.2f}, 실제 std={true.std():.2f}")
    print(f"[예측분포] 예측범위 {pred.min():.1f}~{pred.max():.1f}, 실제 {true.min():.1f}~{true.max():.1f}")
    print(f"\n[MAE] 모델 {mae(pred):.2f} | 0예측 {mae(zero):.2f} | 직전회차 {mae(persist):.2f}")
    mo,ze=mae(pred).item(),mae(zero).item()
    print(f"[개선] 0예측 대비 {100*(1-mo/ze):.0f}%")

    torch.save({'state':best_state},f'{OUT_DIR}/a3tgcn_v2.pt')

if __name__=='__main__':
    main()