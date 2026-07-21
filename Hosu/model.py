"""
A3TGCN 분류 + 양방향 GCN (방향 인접행렬용)
=================================================
기존 GCN은 A 한 방향만. 여기선 A(나감)와 Aᵀ(들어옴)를 둘 다 전파해
'어디로 나가고 어디서 들어오는지' 양방향 경향을 학습.
"""
import torch, torch.nn as nn

class BiGCNLayer(nn.Module):
    """양방향 GCN: A와 Aᵀ로 각각 전파 후 결합."""
    def __init__(self, in_dim, out_dim):
        super().__init__()
        self.lin_out=nn.Linear(in_dim,out_dim)   # 나가는 방향 (A)
        self.lin_in=nn.Linear(in_dim,out_dim)    # 들어오는 방향 (Aᵀ)
    def forward(self, H, A):
        out_dir=torch.einsum('nm,bmd->bnd',A,self.lin_out(H))      # A @ H
        in_dir=torch.einsum('mn,bmd->bnd',A,self.lin_in(H))        # Aᵀ @ H
        return torch.relu(out_dir+in_dir)

class A3TGCN_Dir(nn.Module):
    def __init__(self, f_node, f_global, hidden=48, n_classes=3):
        super().__init__()
        self.gcn1=BiGCNLayer(f_node,hidden); self.gcn2=BiGCNLayer(hidden,hidden)
        self.global_proj=nn.Linear(f_global,hidden)
        self.gru=nn.GRU(hidden,hidden,batch_first=True)
        self.attn=nn.Linear(hidden,1); self.head=nn.Linear(hidden,n_classes)
    def forward(self, X_node, X_global, A):
        B,W,N,F=X_node.shape; sp=[]
        for t in range(W):
            h=self.gcn2(self.gcn1(X_node[:,t],A),A)
            g=self.global_proj(X_global[:,t])
            sp.append(h+g[:,None,:])
        S=torch.stack(sp,1); seq=S.permute(0,2,1,3).reshape(B*N,W,-1)
        out,_=self.gru(seq); score=self.attn(out).softmax(1)
        ctx=(out*score).sum(1)
        return self.head(ctx).reshape(B,N,-1)

if __name__=='__main__':
    m=A3TGCN_Dir(17,4)
    y=m(torch.randn(4,8,40,17),torch.randn(4,8,4),torch.softmax(torch.randn(40,40),-1))
    print('출력:',tuple(y.shape),'(기대 (4,40,3))')
    print('파라미터:',sum(p.numel() for p in m.parameters()),'(양방향이라 GCN 파라미터 2배)')