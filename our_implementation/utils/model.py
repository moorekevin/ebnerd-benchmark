import numpy as np
import torch
import torch.nn as nn
from utils.helper import SEED

# Set random seed
torch.manual_seed(SEED)
np.random.seed(SEED)


class SelfAttention(nn.Module):
    def __init__(self, hparams, verbose=False):
        super().__init__()
        self.head_num = hparams.head_num
        self.head_dim = hparams.head_dim
        self.output_dim = self.head_num * self.head_dim
        self.WQ = self.WK = self.WV = None
        self.dropout = nn.Dropout(hparams.dropout)
        self.verbose = verbose

    def forward(self, Q_seq, K_seq, V_seq):
        # Lazy initialization of the weights
        if self.WQ is None:
            embedding_dim = Q_seq.size(-1)
            self.WQ = nn.Linear(embedding_dim, self.output_dim)
            self.WK = nn.Linear(embedding_dim, self.output_dim)
            self.WV = nn.Linear(embedding_dim, self.output_dim)

        Q = self.WQ(Q_seq)
        K = self.WK(K_seq)
        V = self.WV(V_seq)

        N, L, _ = Q.size()
        Q = Q.view(N, L, self.head_num, self.head_dim).transpose(1, 2)
        K = K.view(N, L, self.head_num, self.head_dim).transpose(1, 2)
        V = V.view(N, L, self.head_num, self.head_dim).transpose(1, 2)

        if self.verbose:
            print(f"Q shape: {Q.shape}")
            print(f"K shape: {K.shape}")
            print(f"V shape: {V.shape}")

        scores = torch.matmul(Q, K.transpose(-2, -1)) / np.sqrt(self.head_dim)
        attn = torch.softmax(scores, dim=-1)
        attn = self.dropout(attn)

        output = torch.matmul(attn, V)
        output = output.transpose(
            1, 2).contiguous().view(N, L, self.output_dim)

        if self.verbose:
            print(f"Attention shape: {attn.shape}")
            print(f"Output shape: {output.shape}")

        return output


class AdditiveAttention(nn.Module):
    def __init__(self, hparams, verbose=False):
        super().__init__()
        self.W = nn.Linear(
            # Input size: hparams.head_num * hparams.head_dim, Output size: hparams.attention_hidden_dim
            hparams.head_num * hparams.head_dim, hparams.attention_hidden_dim
        )
        self.q = nn.Linear(hparams.attention_hidden_dim, 1, bias=False)
        self.dropout = nn.Dropout(hparams.dropout)
        self.verbose = verbose

    def forward(self, x):
        attn = torch.tanh(self.W(x))
        attn = self.q(attn).squeeze(-1)
        attn = torch.softmax(attn, dim=1).unsqueeze(-1)

        if self.verbose:
            print(f"Attention weights shape: {attn.shape}")
            print(f"Input shape: {x.shape}")

        output = torch.sum(x * attn, dim=1)
        output = self.dropout(output)

        if self.verbose:
            print(f"Output shape: {output.shape}")

        return output


class NRMSModel(nn.Module):
    def __init__(self, hparams, word_embeddings):
        super().__init__()
        self.embedding = nn.Embedding.from_pretrained(
            torch.FloatTensor(word_embeddings), freeze=False
        )
        self.dropout = nn.Dropout(hparams.dropout)

        # News Encoder
        self.news_self_att = SelfAttention(hparams, verbose=hparams.verbose)
        self.news_att = AdditiveAttention(hparams, verbose=hparams.verbose)

        # User Encoder
        self.user_self_att = SelfAttention(hparams, verbose=hparams.verbose)
        self.user_att = AdditiveAttention(hparams, verbose=hparams.verbose)

    def encode_news(self, news_input):
        x = self.embedding(news_input)
        x = self.dropout(x)
        x = self.news_self_att(x, x, x)  # x is Q, K, V
        x = self.news_att(x)
        return x

    def encode_user(self, history_input):
        N, H, L = history_input.size()
        history_input = history_input.view(N * H, L)
        news_vectors = self.encode_news(history_input)
        news_vectors = news_vectors.view(N, H, -1)
        user_vector = self.user_self_att(
            news_vectors, news_vectors, news_vectors)
        user_vector = self.user_att(user_vector)
        return user_vector

    def forward(self, his_input, pred_input):
        user_vector = self.encode_user(his_input)
        N, M, L = pred_input.size()
        pred_input = pred_input.view(N * M, L)
        news_vectors = self.encode_news(pred_input)
        news_vectors = news_vectors.view(N, M, -1)
        scores = torch.bmm(news_vectors, user_vector.unsqueeze(2)).squeeze(-1)
        return scores
