"""
MTGNN 분류 학습 - 학습 인접행렬 + 정적 방향 그래프 결합
=================================================
기존 train_cls_directed와 인터페이스 동일:
  - 입력: train/test 윈도우 (build_windows 산출), adjacency_directed.npy(정적)
  - 라벨: y(z-score) -> 3분류 (LO/HI)
  - 손실: 가중 CrossEntropy (p=0.3)
  - 평가: balanced accuracy + 혼동행렬
차이: model.py -> MTGNN, 정적 그래프는 GCN에서 결합용으로 전달
"""
import torch, torch.nn as nn, numpy as np, time
from model_mtgnn import MTGNN
try: from tqdm import tqdm
except ImportError:
    def tqdm(it,**kw): return it

OUT_DIR="processed"
HIDDEN=48; EMB_DIM=16; LR=0.003; MAX_EPOCH=80; PATIENCE=12; BATCH=64
WEIGHT_POWER=0.3; LO,HI=-0.43,0.43; USE_STATIC=True   # 정적 그래프 결합 여부

def pick_device():
    if torch.cuda.is_available(): return 'cuda'
    return 'cpu'   # XPU는 GRU 대신 TCN이니 될 수도 있으나 안전하게 CPU
def to_class(z):
    c=torch.ones_like(z,dtype=torch.long); c[z<LO]=0; c[z>HI]=2; return c
def load(s): return [torch.tensor(np.load(f'{OUT_DIR}/{s}_{n}.npy')) for n in ['X_node','X_global','y','ymask']]

def main():
    device=pick_device(); print(f"[device] {device}")
    A_st=torch.tensor(np.load(f'{OUT_DIR}/adjacency_directed.npy')).float().to(device) if USE_STATIC else None
    Xn_tr,Xg_tr,y_tr,m_tr=load('train'); Xn_te,Xg_te,y_te,m_te=load('test')
    c_tr=to_class(y_tr); c_te=to_class(y_te)
    F_,Fg=Xn_tr.shape[-1],Xg_tr.shape[-1]; N=Xn_tr.shape[2]
    n=len(Xn_tr); nv=max(1,n//10); nt=n-nv
    def dev(*ts): return [t.to(device) for t in ts]

    torch.manual_seed(0)
    model=MTGNN(F_,Fg,n_nodes=N,hidden=HIDDEN,emb_dim=EMB_DIM,use_static=USE_STATIC).to(device)
    opt=torch.optim.Adam(model.parameters(),lr=LR,weight_decay=1e-5)
    counts=torch.bincount(c_tr[m_tr.bool()].reshape(-1),minlength=3).float()
    inv=(counts.sum()/(counts+1e-6))**WEIGHT_POWER; w=(inv/inv.sum()*3).to(device)
    print(f"[클래스 분포] 부족={int(counts[0])} 정상={int(counts[1])} 과잉={int(counts[2])}")
    print(f"[클래스 가중치 p={WEIGHT_POWER}] {w.cpu().numpy().round(2).tolist()}")
    print(f"[모델] MTGNN, 파라미터 {sum(p.numel() for p in model.parameters())}, "
          f"정적그래프 결합={USE_STATIC}")
    lossf=nn.CrossEntropyLoss(weight=w,reduction='none')

    def mce(lg,y,m): return (lossf(lg.reshape(-1,3),y.reshape(-1)).reshape(y.shape)*m).sum()/(m.sum()+1e-8)
    def bacc(lg,y,m):
        pr=lg.argmax(-1); mb=m.bool(); accs=[]
        for k in range(3):
            mk=(y==k)&mb
            if mk.sum()>0: accs.append((((pr==y)&mk).sum().float()/mk.sum()).item())
        return sum(accs)/len(accs) if accs else 0

    best=0; bs=None; wait=0; t0=time.time()
    pbar=tqdm(range(MAX_EPOCH), desc="MTGNN", ncols=100)
    for ep in pbar:
        ep_t0=time.time()
        model.train(); perm=torch.randperm(nt); tr_l=0
        for i in range(0,nt,BATCH):
            idx=perm[i:i+BATCH]
            xn,xg,y,m=dev(Xn_tr[idx],Xg_tr[idx],c_tr[idx],m_tr[idx])
            opt.zero_grad()
            loss=mce(model(xn,xg,A_st),y,m)
            loss.backward(); opt.step(); tr_l+=loss.item()*len(idx)
        model.eval()
        with torch.no_grad():
            xn,xg,y,m=dev(Xn_tr[nt:],Xg_tr[nt:],c_tr[nt:],m_tr[nt:])
            va=bacc(model(xn,xg,A_st),y,m)
        ep_sec=time.time()-ep_t0; improved=va>best+1e-4
        if hasattr(pbar,'set_postfix'):
            pbar.set_postfix(loss=f"{tr_l/nt:.4f}",val_bacc=f"{va:.3f}",
                             best=f"{max(best,va):.3f}",ep_s=f"{ep_sec:.1f}")
        if improved: best=va; bs={k:v.cpu().clone() for k,v in model.state_dict().items()}; wait=0
        else:
            wait+=1
            if wait>=PATIENCE:
                msg=f"[early stop] ep {ep}, best {best:.3f}"
                if hasattr(pbar,'write'): pbar.write(msg)
                else: print(msg)
                break
    if hasattr(pbar,'close'): pbar.close()

    model.load_state_dict(bs); print(f"[학습완료] {time.time()-t0:.1f}s")
    model.eval()
    with torch.no_grad(): pred=model(*dev(Xn_te,Xg_te),A_st).argmax(-1).cpu()
    mm=m_te.bool()
    cm=np.zeros((3,3),int)
    for t_,p_ in zip(c_te[mm].numpy(), pred[mm].numpy()): cm[t_,p_]+=1
    correct=np.trace(cm); tot=cm.sum(); fatal=cm[0,2]+cm[2,0]
    ba=np.mean([cm[k,k]/cm[k].sum() if cm[k].sum()>0 else 0 for k in range(3)])
    print(f"\n[MTGNN 결과] 전체 {correct/tot:.3f} | 균형 {ba:.3f} | 치명 {fatal/tot:.3f}")
    for k,nm in [(0,'부족'),(1,'정상'),(2,'과잉')]:
        print(f"  {nm}: {cm[k,k]/cm[k].sum():.3f} (n={cm[k].sum()})")
    print(f"\n[비교 기준] 방향 대칭 A3TGCN: 균형 0.465, 치명 0.139")
    torch.save({'state':bs},f'{OUT_DIR}/mtgnn.pt')

if __name__=='__main__':
    main()