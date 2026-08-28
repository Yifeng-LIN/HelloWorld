"""用 Amadeus Self-Service API 做「逐个出发日」的满座程度探测。

为什么需要它：官方统计（Eurostat / DGAC）最细只到「月」，而且滞后 3~12 个月。
想要「哪一周满、哪一周空」只能靠订座侧的实时信号。这里用两个互补指标：

  A. 座位图占用率 —— SeatMap Display 返回每个座位的
     AVAILABLE / BLOCKED / OCCUPIED，OCCUPIED 占比就是**已选座**的满座率。
     ⚠ 它系统性偏低：很多旅客值机前不选座、后排常被航司锁座。
     所以它适合做**横向比较**（这周 vs 那周），不适合当绝对客座率。

  B. 舱位库存 —— Flight Availabilities Search 返回每个舱位等级的可订座位数，
     计数器上限为 9。低舱（如 Y/B/M 之下的 L/V/X/N）全部关闭、只剩高舱开着，
     是航班接近售罄的经典信号。这个指标对「快满了」比座位图敏感得多。

免费额度：Self-Service 计划注册即用，测试环境数据是沙箱数据，
**要拿真实库存必须切到 production 环境**（config.AMADEUS_HOSTS["production"]）。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

from . import config

log = logging.getLogger(__name__)

TIMEOUT = 60
# 免费档限速较紧，两次调用之间留点间隔
MIN_INTERVAL = 0.4

# 低舱位：这些先关闭，说明便宜票已经卖完
LOW_CLASSES = list("LVXNQOSGWETRU")


class Amadeus:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        env: str = "production",
        cache_dir: Optional[Path] = None,
    ):
        self.client_id = client_id or os.environ.get("AMADEUS_CLIENT_ID")
        self.client_secret = client_secret or os.environ.get(
            "AMADEUS_CLIENT_SECRET"
        )
        if not self.client_id or not self.client_secret:
            raise RuntimeError(
                "缺少凭证：请设置环境变量 AMADEUS_CLIENT_ID / AMADEUS_CLIENT_SECRET"
            )
        self.host = config.AMADEUS_HOSTS[env]
        self.session = requests.Session()
        self._token: Optional[str] = None
        self._token_expiry = 0.0
        self._last_call = 0.0
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- 底层
    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < MIN_INTERVAL:
            time.sleep(MIN_INTERVAL - gap)
        self._last_call = time.monotonic()

    def _auth(self) -> str:
        if self._token and time.monotonic() < self._token_expiry - 60:
            return self._token
        resp = self.session.post(
            f"{self.host}/v1/security/oauth2/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        payload = resp.json()
        self._token = payload["access_token"]
        self._token_expiry = time.monotonic() + float(
            payload.get("expires_in", 1799)
        )
        return self._token

    def _request(
        self, method: str, path: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        self._throttle()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._auth()}"
        resp = self.session.request(
            method, f"{self.host}{path}", headers=headers, timeout=TIMEOUT,
            **kwargs
        )
        if resp.status_code == 429:
            log.warning("触发限速，等待 5 秒后重试")
            time.sleep(5)
            return self._request(method, path, headers=headers, **kwargs)
        if not resp.ok:
            log.warning("%s %s -> HTTP %s: %s", method, path,
                        resp.status_code, resp.text[:300])
            return None
        return resp.json()

    # -------------------------------------------------------------- 缓存
    def _cached(self, key: str, producer):
        if not self.cache_dir:
            return producer()
        path = self.cache_dir / f"{key}.json"
        if path.exists():
            return json.loads(path.read_text())
        value = producer()
        if value is not None:
            path.write_text(json.dumps(value, ensure_ascii=False))
        return value

    # -------------------------------------------------------------- 查询
    def flight_offers(
        self, departure_date: str, origin: str, destination: str
    ) -> List[Dict[str, Any]]:
        payload = self._cached(
            f"offers_{origin}_{destination}_{departure_date}",
            lambda: self._request(
                "GET",
                "/v2/shopping/flight-offers",
                params={
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDate": departure_date,
                    "adults": 1,
                    "nonStop": "true",
                    "currencyCode": "EUR",
                    "max": 5,
                },
            ),
        )
        return (payload or {}).get("data", [])

    def seatmap_occupancy(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """返回该航班的座位图统计：总座位 / 已占用 / 占用率。"""
        payload = self._request(
            "POST",
            "/v1/shopping/seatmaps",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"data": [offer]}),
        )
        if not payload or not payload.get("data"):
            return None

        counts = {"AVAILABLE": 0, "OCCUPIED": 0, "BLOCKED": 0}
        for seatmap in payload["data"]:
            for deck in seatmap.get("decks", []):
                for seat in deck.get("seats", []):
                    for tp in seat.get("travelerPricing", []):
                        status = tp.get("seatAvailabilityStatus")
                        if status in counts:
                            counts[status] += 1
                        break

        total = sum(counts.values())
        if total == 0:
            return None
        return {
            "seats_total": total,
            "seats_occupied": counts["OCCUPIED"],
            "seats_available": counts["AVAILABLE"],
            "seats_blocked": counts["BLOCKED"],
            # 把 BLOCKED 也算进「不可卖」，更贴近乘客感知的「满」
            "seatmap_occupancy": (counts["OCCUPIED"] + counts["BLOCKED"]) / total,
            "seatmap_occupied_only": counts["OCCUPIED"] / total,
        }

    def availability(
        self, departure_date: str, origin: str, destination: str
    ) -> List[Dict[str, Any]]:
        """返回各航段的舱位库存计数。"""
        body = {
            "originDestinations": [
                {
                    "id": "1",
                    "originLocationCode": origin,
                    "destinationLocationCode": destination,
                    "departureDateTime": {"date": departure_date},
                }
            ],
            "travelers": [{"id": "1", "travelerType": "ADULT"}],
            "sources": ["GDS"],
        }
        payload = self._cached(
            f"avail_{origin}_{destination}_{departure_date}",
            lambda: self._request(
                "POST",
                "/v1/shopping/availability/flight-availabilities",
                headers={"Content-Type": "application/json"},
                data=json.dumps(body),
            ),
        )
        return (payload or {}).get("data", [])


# ------------------------------------------------------------------ 汇总
def summarise_availability(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把舱位库存压缩成几个可比的标量。"""
    open_classes: Dict[str, int] = {}
    for entry in entries:
        for segment in entry.get("segments", []):
            for cls in segment.get("availabilityClasses", []):
                code = cls.get("class")
                seats = cls.get("numberOfBookableSeats", 0)
                if code:
                    open_classes[code] = max(open_classes.get(code, 0), seats)

    if not open_classes:
        return {
            "classes_open": 0,
            "low_classes_open": 0,
            "total_bookable": 0,
            "scarcity": None,
        }

    low_open = sum(1 for c in open_classes if c in LOW_CLASSES)
    total = sum(open_classes.values())
    return {
        "classes_open": len(open_classes),
        "low_classes_open": low_open,
        "total_bookable": total,
        # 0 = 宽松，1 = 极紧张
        "scarcity": round(1 - min(total / (len(open_classes) * 9 or 1), 1), 3),
        "class_detail": ",".join(
            f"{c}{n}" for c, n in sorted(open_classes.items())
        ),
    }


def scan_dates(
    client: Amadeus,
    dates: Iterable[str],
    origin: str = config.IATA_ORIGIN,
    destination: str = config.IATA_DEST,
    with_seatmap: bool = True,
):
    """逐个出发日扫描，返回一张可直接做周度聚合的表。"""
    import pandas as pd

    rows = []
    for date in dates:
        row: Dict[str, Any] = {
            "departure_date": date,
            "origin": origin,
            "destination": destination,
        }
        try:
            row.update(summarise_availability(
                client.availability(date, origin, destination)
            ))
            offers = client.flight_offers(date, origin, destination)
            row["offers_found"] = len(offers)
            if offers:
                cheapest = min(
                    offers, key=lambda o: float(o["price"]["grandTotal"])
                )
                row["cheapest_eur"] = float(cheapest["price"]["grandTotal"])
                row["seats_left_flag"] = cheapest.get("numberOfBookableSeats")
                if with_seatmap:
                    occ = client.seatmap_occupancy(cheapest)
                    if occ:
                        row.update(occ)
        except Exception as exc:                       # 单日失败不该中断整轮扫描
            log.warning("%s 扫描失败: %s", date, exc)
            row["error"] = str(exc)
        rows.append(row)
        log.info("已扫描 %s", date)

    df = pd.DataFrame(rows)
    if not df.empty:
        df["departure_date"] = pd.to_datetime(df["departure_date"])
        iso = df["departure_date"].dt.isocalendar()
        df["iso_year"] = iso.year
        df["iso_week"] = iso.week
        df["weekday"] = df["departure_date"].dt.dayofweek + 1
    return df


def date_range(start: str, days: int) -> List[str]:
    begin = dt.date.fromisoformat(start)
    return [(begin + dt.timedelta(days=i)).isoformat() for i in range(days)]
