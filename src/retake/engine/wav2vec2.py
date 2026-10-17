from __future__ import annotations

import json
import math
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F


class _ConvLayer(nn.Module):
    def __init__(self, in_dim: int, out_dim: int, kernel: int, stride: int, bias: bool, norm: str, first: bool):
        super().__init__()
        self.conv = nn.Conv1d(in_dim, out_dim, kernel, stride=stride, bias=bias)
        self.norm_kind = norm
        if norm == "layer":
            self.layer_norm = nn.LayerNorm(out_dim, elementwise_affine=True)
        elif norm == "group" and first:
            self.layer_norm = nn.GroupNorm(out_dim, out_dim, affine=True)
        else:
            self.layer_norm = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.conv(x)
        if self.norm_kind == "layer":
            x = self.layer_norm(x.transpose(-2, -1)).transpose(-2, -1)
        elif self.layer_norm is not None:
            x = self.layer_norm(x)
        return F.gelu(x)


class _FeatureEncoder(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        dims = config["conv_dim"]
        layers = []
        for i, (dim, kernel, stride) in enumerate(zip(dims, config["conv_kernel"], config["conv_stride"])):
            layers.append(_ConvLayer(1 if i == 0 else dims[i - 1], dim, kernel, stride, config.get("conv_bias", False), config["feat_extract_norm"], i == 0))
        self.conv_layers = nn.ModuleList(layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x[:, None]
        for layer in self.conv_layers:
            x = layer(x)
        return x


class _FeatureProjection(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.layer_norm = nn.LayerNorm(config["conv_dim"][-1], eps=config.get("layer_norm_eps", 1e-5))
        self.projection = nn.Linear(config["conv_dim"][-1], config["hidden_size"])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.projection(self.layer_norm(x))


class _PositionalConv(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        hidden = config["hidden_size"]
        kernel = config["num_conv_pos_embeddings"]
        self.kernel = kernel
        self.groups = config["num_conv_pos_embedding_groups"]
        self.weight_g = nn.Parameter(torch.ones(1, 1, kernel))
        self.weight_v = nn.Parameter(torch.zeros(hidden, hidden // self.groups, kernel))
        self.bias = nn.Parameter(torch.zeros(hidden))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        norm = self.weight_v.norm(dim=(0, 1), keepdim=True)
        weight = self.weight_g * self.weight_v / norm
        out = F.conv1d(x.transpose(1, 2), weight, self.bias, padding=self.kernel // 2, groups=self.groups)
        if self.kernel % 2 == 0:
            out = out[:, :, :-1]
        return F.gelu(out).transpose(1, 2)


class _Attention(nn.Module):
    def __init__(self, hidden: int, heads: int):
        super().__init__()
        self.heads = heads
        self.head_dim = hidden // heads
        self.q_proj = nn.Linear(hidden, hidden)
        self.k_proj = nn.Linear(hidden, hidden)
        self.v_proj = nn.Linear(hidden, hidden)
        self.out_proj = nn.Linear(hidden, hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, length, hidden = x.shape

        def split(t: torch.Tensor) -> torch.Tensor:
            return t.view(batch, length, self.heads, self.head_dim).transpose(1, 2)

        out = F.scaled_dot_product_attention(split(self.q_proj(x)), split(self.k_proj(x)), split(self.v_proj(x)))
        return self.out_proj(out.transpose(1, 2).reshape(batch, length, hidden))


class _FeedForward(nn.Module):
    def __init__(self, hidden: int, intermediate: int):
        super().__init__()
        self.intermediate_dense = nn.Linear(hidden, intermediate)
        self.output_dense = nn.Linear(intermediate, hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.output_dense(F.gelu(self.intermediate_dense(x)))


class _EncoderLayer(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        hidden = config["hidden_size"]
        eps = config.get("layer_norm_eps", 1e-5)
        self.stable = config.get("do_stable_layer_norm", False)
        self.attention = _Attention(hidden, config["num_attention_heads"])
        self.layer_norm = nn.LayerNorm(hidden, eps=eps)
        self.feed_forward = _FeedForward(hidden, config["intermediate_size"])
        self.final_layer_norm = nn.LayerNorm(hidden, eps=eps)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.stable:
            x = x + self.attention(self.layer_norm(x))
            return x + self.feed_forward(self.final_layer_norm(x))
        x = self.layer_norm(x + self.attention(x))
        return self.final_layer_norm(x + self.feed_forward(x))


class _Encoder(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.stable = config.get("do_stable_layer_norm", False)
        self.pos_conv_embed = _PositionalConv(config)
        self.layer_norm = nn.LayerNorm(config["hidden_size"], eps=config.get("layer_norm_eps", 1e-5))
        self.layers = nn.ModuleList(_EncoderLayer(config) for _ in range(config["num_hidden_layers"]))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.pos_conv_embed(x)
        if not self.stable:
            x = self.layer_norm(x)
        for layer in self.layers:
            x = layer(x)
        if self.stable:
            x = self.layer_norm(x)
        return x


class _Wav2Vec2(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.feature_extractor = _FeatureEncoder(config)
        self.feature_projection = _FeatureProjection(config)
        self.encoder = _Encoder(config)

    def forward(self, audio: torch.Tensor) -> torch.Tensor:
        features = self.feature_extractor(audio).transpose(1, 2)
        return self.encoder(self.feature_projection(features))


class Wav2Vec2ForCTC(nn.Module):
    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.wav2vec2 = _Wav2Vec2(config)
        self.lm_head = nn.Linear(config["hidden_size"], config["vocab_size"])

    def forward(self, audio: torch.Tensor) -> torch.Tensor:
        return self.lm_head(self.wav2vec2(audio))

    @property
    def frame_seconds(self) -> float:
        return math.prod(self.config["conv_stride"]) / 16000


def _rename(key: str) -> str | None:
    if key.startswith("wav2vec2.masked_spec_embed") or "adapter" in key:
        return None
    key = key.replace("parametrizations.weight.original0", "weight_g")
    key = key.replace("parametrizations.weight.original1", "weight_v")
    key = key.replace("pos_conv_embed.conv.", "pos_conv_embed.")
    return key


def load(directory: Path, device: str = "cpu", half: bool = False) -> tuple[Wav2Vec2ForCTC, dict[str, int]]:
    config = json.loads((directory / "config.json").read_text())
    vocab = json.loads((directory / "vocab.json").read_text(encoding="utf-8"))
    model = Wav2Vec2ForCTC(config)
    weights_file = directory / "model.safetensors"
    if weights_file.exists():
        from safetensors.torch import load_file

        state = load_file(str(weights_file))
    else:
        state = torch.load(directory / "pytorch_model.bin", map_location="cpu", weights_only=True)
    renamed = {}
    for key, value in state.items():
        new_key = _rename(key)
        if new_key is not None:
            renamed[new_key] = value
    missing, unexpected = model.load_state_dict(renamed, strict=False)
    if missing:
        raise RuntimeError(f"wav2vec2 weights missing: {missing[:5]}")
    model.eval()
    model.to(device)
    if half:
        model.half()
    return model, vocab
