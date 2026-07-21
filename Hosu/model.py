"""
타슈 STGNN - A3TGCN (순수 PyTorch 구현)
=================================================
scatter/sparse 확장 없음 -> CPU/XPU/CUDA 어디서나 device만 바꾸면 동작.
인접행렬은 사전 정규화된 A (adjacency.npy)를 행렬곱으로 직접 사용.

구조 (A3TGCN 핵심):
  각 타임스텝: GCN으로 공간 전파 -> 노드 임베딩
  시퀀스: GRU로 시간 인코딩
  Attention: 8개 타임스텝을 가중합 (어느 시점이 중요한지 학습)
  출력: 노드별 다음 회차 flow_z 예측

입력:  X_node [B, W, N, F], X_global [B, W, Fg], A [N, N]
출력:  y_hat [B, N]
"""
import torch
import torch.nn as nn

class GCNLayer(nn.Module):
    """사전 정규화 A를 쓰는 단순 GCN: H' = A @ H @ W"""
    def __init__(self, in_dim, out_dim):
        super().__init__()
        self.lin = nn.Linear(in_dim, out_dim)
    def forward(self, H, A):
        # H: [B, N, in], A: [N, N]
        H = self.lin(H)                    # [B, N, out]
        H = torch.einsum('nm,bmd->bnd', A, H)  # A @ H  (공간 전파)
        return torch.relu(H)

class A3TGCN(nn.Module):
    def __init__(self, f_node, f_global, hidden=48, gru_layers=1):
        super().__init__()
        self.gcn1 = GCNLayer(f_node, hidden)
        self.gcn2 = GCNLayer(hidden, hidden)
        # 전역 피처(날씨)를 각 타임스텝 노드 임베딩에 결합
        self.global_proj = nn.Linear(f_global, hidden)
        self.gru = nn.GRU(hidden, hidden, num_layers=gru_layers, batch_first=True)
        # 시간 attention: 각 타임스텝 hidden -> 스칼라 점수
        self.attn = nn.Linear(hidden, 1)
        self.head = nn.Linear(hidden, 1)   # 노드별 flow 예측

    def forward(self, X_node, X_global, A):
        B, W, N, F = X_node.shape
        # 각 타임스텝별 GCN 공간 전파
        spatial = []
        for t in range(W):
            h = self.gcn1(X_node[:,t], A)     # [B,N,hidden]
            h = self.gcn2(h, A)               # [B,N,hidden]
            # 전역 피처(날씨) 결합: 모든 노드에 broadcast
            g = self.global_proj(X_global[:,t])   # [B,hidden]
            h = h + g[:,None,:]                    # [B,N,hidden]
            spatial.append(h)
        S = torch.stack(spatial, dim=1)   # [B, W, N, hidden]

        # 노드별로 GRU (시간 인코딩). 노드축을 배치로 접어서 처리
        Bn = B*N
        seq = S.permute(0,2,1,3).reshape(Bn, W, -1)   # [B*N, W, hidden]
        out, _ = self.gru(seq)                          # [B*N, W, hidden]

        # 시간 attention 가중합
        score = self.attn(out).softmax(dim=1)           # [B*N, W, 1]
        ctx = (out * score).sum(dim=1)                  # [B*N, hidden]

        y = self.head(ctx).reshape(B, N)                # [B, N]
        return y

if __name__ == '__main__':
    torch.manual_seed(0)
    B,W,N,F,Fg = 4,8,40,12,4
    model = A3TGCN(F, Fg)
    Xn = torch.randn(B,W,N,F)
    Xg = torch.randn(B,W,Fg)
    A  = torch.randn(N,N); A = (A@A.T).softmax(-1)  # 더미 정규화 A
    y = model(Xn, Xg, A)
    print('입력 X_node:', tuple(Xn.shape))
    print('입력 X_global:', tuple(Xg.shape))
    print('인접행렬 A:', tuple(A.shape))
    print('출력 y_hat:', tuple(y.shape), '(기대: (4, 40))')
    print('파라미터 수:', sum(p.numel() for p in model.parameters()))
    print('shape 검증:', 'OK' if y.shape==(B,N) else 'FAIL')