"""
MTGNN (Multivariate Time series GNN) - 학습 인접행렬 + Dilated TCN
=================================================
원 논문의 두 핵심 아이디어만 순수 PyTorch로 구현:
  1) 학습 인접행렬: 노드 임베딩 유사도로 인접행렬 자체를 학습
     -> 손으로 만든 OD 관계 외에 "숨은 유용한 이웃"을 데이터가 찾음
  2) Dilated 1D Conv (TCN): GRU 대신 시간축 처리
     -> 병렬화 쉬움, CPU에서 조금 빠름

기존 방향 인접행렬(A)도 옵션으로 함께 사용 가능 (adaptive + static 결합).
분류 출력 [B, N, 3].
"""
import torch, torch.nn as nn, torch.nn.functional as F

class AdaptiveGraph(nn.Module):
    """노드 임베딩 두 세트(E1, E2)로 방향성 있는 학습 그래프 생성.
    A_adaptive = softmax(ReLU(E1 @ E2^T))  <- 비대칭 유지."""
    def __init__(self, n_nodes, emb_dim=16, alpha=3.0, topk=None):
        super().__init__()
        self.E1=nn.Parameter(torch.randn(n_nodes,emb_dim)*0.1)
        self.E2=nn.Parameter(torch.randn(n_nodes,emb_dim)*0.1)
        self.alpha=alpha; self.topk=topk
    def forward(self):
        M=torch.tanh(self.alpha*self.E1) @ torch.tanh(self.alpha*self.E2).T  # [N,N]
        A=F.relu(M - M.T)   # 방향성 잔재만 (비대칭)
        if self.topk is not None:
            k=min(self.topk, A.shape[-1])
            v,_=A.topk(k,dim=-1)
            mask=A>=v[...,-1:]
            A=A*mask
        # 행 정규화 (self-loop 포함)
        A=A+torch.eye(A.shape[0],device=A.device)*0.5
        return A/(A.sum(-1,keepdim=True)+1e-6)

class DilatedTCN(nn.Module):
    """Dilated 1D Conv 두 층 (kernel=3, dilation=1,2) -> 짧은 시퀀스(T=8) 커버."""
    def __init__(self, ch, hidden):
        super().__init__()
        self.conv1=nn.Conv1d(ch,hidden,kernel_size=3,padding=2,dilation=1)
        self.conv2=nn.Conv1d(hidden,hidden,kernel_size=3,padding=4,dilation=2)
        self.dropout=nn.Dropout(0.2)
    def forward(self,x):
        # x: [BN, T, F] -> conv는 [BN, F, T]
        x=x.transpose(1,2)
        x=F.relu(self.conv1(x))
        x=self.dropout(x)
        x=F.relu(self.conv2(x))
        return x.mean(dim=-1)   # 시간축 pooling -> [BN, hidden]

class BiGCN(nn.Module):
    """양방향 GCN: 학습 그래프와 정적 그래프 결합 가능."""
    def __init__(self,in_d,out_d):
        super().__init__()
        self.w_ad=nn.Linear(in_d,out_d)   # 학습 그래프용
        self.w_st=nn.Linear(in_d,out_d)   # 정적 그래프용 (있으면)
        self.w_stT=nn.Linear(in_d,out_d)  # 정적 그래프 역방향
    def forward(self,H,A_ad,A_st=None):
        h=torch.einsum('nm,bmd->bnd',A_ad,self.w_ad(H))
        if A_st is not None:
            h=h+torch.einsum('nm,bmd->bnd',A_st,self.w_st(H))
            h=h+torch.einsum('mn,bmd->bnd',A_st,self.w_stT(H))
        return F.relu(h)

class MTGNN(nn.Module):
    def __init__(self, f_node, f_global, n_nodes, hidden=48, emb_dim=16,
                 n_classes=3, use_static=True):
        super().__init__()
        self.adaptive=AdaptiveGraph(n_nodes, emb_dim=emb_dim, topk=min(20,n_nodes))
        self.use_static=use_static
        self.tcn=DilatedTCN(f_node+f_global, hidden)
        self.gcn1=BiGCN(hidden,hidden); self.gcn2=BiGCN(hidden,hidden)
        self.head=nn.Sequential(nn.Linear(hidden,hidden),nn.ReLU(),
                                 nn.Dropout(0.3),nn.Linear(hidden,n_classes))
    def forward(self, X_node, X_global, A_static=None):
        B,W,N,F_=X_node.shape
        # 전역 피처를 노드마다 broadcast
        Xg=X_global[:,:,None,:].expand(B,W,N,-1)
        X=torch.cat([X_node,Xg],dim=-1)     # [B,W,N,F+Fg]
        # 시간축 TCN: 각 노드별 시퀀스 -> hidden
        seq=X.permute(0,2,1,3).reshape(B*N,W,-1)
        H=self.tcn(seq).reshape(B,N,-1)     # [B,N,hidden]
        # 학습 그래프로 공간 전파
        A_ad=self.adaptive()
        H=self.gcn1(H, A_ad, A_static if self.use_static else None)
        H=self.gcn2(H, A_ad, A_static if self.use_static else None)
        return self.head(H)  # [B,N,3]

if __name__=='__main__':
    m=MTGNN(f_node=17,f_global=4,n_nodes=40,hidden=48)
    A_st=torch.softmax(torch.randn(40,40),-1)
    y=m(torch.randn(4,8,40,17), torch.randn(4,8,4), A_st)
    print('출력:',tuple(y.shape),'(기대 (4,40,3))')
    print('파라미터:',sum(p.numel() for p in m.parameters()))
    # 학습 그래프 확인
    with torch.no_grad(): A_ad=m.adaptive()
    print(f'학습 인접행렬 shape: {tuple(A_ad.shape)}, 비대칭 확인 A[0,1]={A_ad[0,1]:.3f} vs A[1,0]={A_ad[1,0]:.3f}')
    print(f'topk={20}으로 희소화, 행합≈1: {A_ad.sum(1)[:3].round(decimals=3).tolist()}')