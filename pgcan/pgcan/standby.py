"""候补/溢出模型：把「月度客座率」翻译成「我这一天上得去吗」。

客座率是个月度平均值，回答不了「今天满了，明天候补能上吗」。
要回答那个问题，得给每日需求一个分布，然后算三件事：

  1. P(某一天卖爆)                 —— 单日订不到票的概率
  2. P(明天有位 | 今天满了)         —— 候补第二天的成功率
  3. P(N 天内有位 | 今天满了)       —— 愿意多等几天的话

关键在第 2 条：**天与天之间不是独立的**。今天满了这件事本身就是「这一阵子
需求偏高」的证据，会把明天的预期一起拉高。所以条件概率一定低于无条件概率，
两者的差距就是「旺季候补有多没用」的量化答案。

需求模型
--------
    季节强度   M ~ LogNormal(log μ0, σ_s)     整个时段共享，制造天与天的相关
    单日需求   D_t | M ~ Gamma(mean=M, CV=k)  给定季节强度后各天独立

μ0 由目标客座率反解得到（客座率 = E[min(D, C)] / C）。
k 是需求变异系数，洲际航线收益管理里常用 0.20–0.35。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

# A350-900 三舱布局
DEFAULT_CAPACITY = 314
# 需求变异系数（K-factor）
DEFAULT_K = 0.25
# 季节强度的不确定性，制造天与天的正相关
DEFAULT_SIGMA_SEASON = 0.10

_RNG_DRAWS = 400_000


def _gamma_draws(mean: np.ndarray, k: float, rng) -> np.ndarray:
    """给定逐元素均值和固定变异系数，抽 Gamma 随机数。"""
    shape = 1.0 / (k * k)
    return rng.gamma(shape=shape, scale=mean / shape)


def solve_mean_demand(
    load_factor: float,
    capacity: int = DEFAULT_CAPACITY,
    k: float = DEFAULT_K,
    seed: int = 7,
) -> float:
    """反解出能产生目标客座率的平均需求（可能大于运力，因为有溢出）。"""
    rng = np.random.default_rng(seed)
    base = _gamma_draws(np.full(_RNG_DRAWS, 1.0), k, rng)   # 均值 1 的形状

    lo, hi = 0.1, 5.0
    for _ in range(60):
        mid = (lo + hi) / 2
        achieved = np.minimum(base * mid * capacity, capacity).mean() / capacity
        if achieved < load_factor:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2 * capacity


def standby_odds(
    load_factor: float,
    capacity: int = DEFAULT_CAPACITY,
    k: float = DEFAULT_K,
    sigma_season: float = DEFAULT_SIGMA_SEASON,
    horizon: int = 4,
    seed: int = 11,
) -> Dict[str, float]:
    """核心计算。返回单日售罄率与候补成功率。"""
    rng = np.random.default_rng(seed)
    mu0 = solve_mean_demand(load_factor, capacity, k)

    n = _RNG_DRAWS
    # 共享的季节强度 —— 天与天的相关性来源
    season = rng.lognormal(mean=np.log(mu0) - sigma_season**2 / 2,
                           sigma=sigma_season, size=n)

    days = np.column_stack([
        _gamma_draws(season, k, rng) for _ in range(horizon + 1)
    ])
    full = days >= capacity

    today_full = full[:, 0]
    p_full = float(today_full.mean())

    result = {
        "load_factor": load_factor,
        "mean_demand": float(mu0),
        "p_sold_out": p_full,
        "p_seat_any_day": 1.0 - p_full,
    }

    if today_full.sum() == 0:
        for d in range(1, horizon + 1):
            result[f"p_seat_within_{d}d"] = 1.0
        result["p_seat_next_day"] = 1.0
        result["independence_gap"] = 0.0
        return result

    # 只看「今天满了」的那些世界
    sub = full[today_full]
    for d in range(1, horizon + 1):
        # 未来 d 天里至少有一天有空位
        got = (~sub[:, 1:d + 1]).any(axis=1)
        result[f"p_seat_within_{d}d"] = float(got.mean())

    result["p_seat_next_day"] = result["p_seat_within_1d"]
    # 独立假设会高估多少 —— 这就是「旺季候补更没用」的量化
    result["independence_gap"] = float(
        (1.0 - p_full) - result["p_seat_next_day"]
    )
    return result


def curve(
    load_factors: Optional[List[float]] = None,
    **kwargs,
) -> List[Dict[str, float]]:
    """扫一条客座率 -> 候补成功率的曲线。"""
    grid = load_factors or [
        round(x, 3) for x in np.arange(0.60, 0.991, 0.01)
    ]
    return [standby_odds(lf, **kwargs) for lf in grid]


if __name__ == "__main__":
    print(f"运力 {DEFAULT_CAPACITY} 座 · K={DEFAULT_K} · σ_season={DEFAULT_SIGMA_SEASON}\n")
    header = f"{'客座率':>7} {'单日售罄':>9} {'明天有位':>9} {'3天内':>8} {'独立假设高估':>13}"
    print(header)
    print("-" * len(header))
    for lf in [0.65, 0.70, 0.75, 0.80, 0.83, 0.86, 0.88, 0.90, 0.92, 0.94, 0.96]:
        r = standby_odds(lf)
        print(f"{lf:>7.0%} {r['p_sold_out']:>9.1%} {r['p_seat_next_day']:>9.1%} "
              f"{r['p_seat_within_3d']:>8.1%} {r['independence_gap']:>13.1%}")
