"""航线常量与数据源配置。

事实来源说明（2026-08 核实）：
  * CDG <-> CAN 直飞目前只有中国南方航空一家承运，每周 7 班往返
    （CZ348 CDG->CAN, CZ347 CAN->CDG）。
  * 法航（AF）已于 2019 年 3 月底停飞该航线，此后仅以代码共享形式售票，
    因此 2019 夏季以后该航线的运力 = 南航运力。
  * 未经核实的历史班次/机型一律不写死，留给 Eurostat 的 ST_PAS 字段作准。
"""

from __future__ import annotations

# ---------------------------------------------------------------- 航线标识
IATA_ORIGIN = "CDG"          # 巴黎戴高乐
IATA_DEST = "CAN"            # 广州白云
ICAO_ORIGIN = "LFPG"
ICAO_DEST = "ZGGG"

# ---------------------------------------------------------------- Eurostat
# avia_par_fr = "Air passenger transport routes between partner airports and
# main airports in France"，月度、航线级，含座位数与旅客数。
EUROSTAT_DATASET = "avia_par_fr"
EUROSTAT_BASE = (
    "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
)
EUROSTAT_BULK = "https://ec.europa.eu/eurostat/api/dissemination/files"

# airp_pr 维度的取值形如 <报告国机场>_<伙伴国机场>
EUROSTAT_ROUTE_CODES = [
    "FR_LFPG_CN_ZGGG",
    "FR_LFPG_CN_ZGGG_2",   # Eurostat 偶尔对同一航线做拆分编码
]
# 兜底：在整份 TSV 里按这个子串抓行
EUROSTAT_ROUTE_GREP = "ZGGG"

# tra_meas 代码含义（Eurostat 官方码表）
TRA_MEAS = {
    "PAS_CRD": "旅客运输量 (passengers carried)",
    "PAS_BRD": "在机旅客数 (passengers on board)",
    "ST_PAS": "可提供座位数 (passenger seats available)",
    "CAF_PAS": "商业客运航班班次 (commercial passenger air flights)",
}
# 计算客座率所需的最小字段组合，按优先级排列
LOAD_FACTOR_PAIRS = [("PAS_CRD", "ST_PAS"), ("PAS_BRD", "ST_PAS")]

# ---------------------------------------------------------------- DGAC / data.gouv.fr
# 法国民航局：1990 年起、按机场对、按方向的月度商业航空运量
DGAC_DATASET_SLUG = (
    "trafic-aerien-commercial-mensuel-francais-par-paire-daeroports-"
    "par-sens-depuis-1990"
)
DGAC_API = "https://www.data.gouv.fr/api/1/datasets"

# DGAC 的列名多年间变动过，这里用模糊匹配而不是写死列名
DGAC_COLUMN_HINTS = {
    "airport_a": ["apt_a", "aeroport_a", "apt1", "origine", "depart"],
    "airport_b": ["apt_b", "aeroport_b", "apt2", "destination", "arrivee"],
    "year": ["anmois", "annee", "an", "year"],
    "month": ["anmois", "mois", "month"],
    "passengers": ["pax", "passager", "psg", "trafic"],
    "seats": ["siege", "sieges", "offert", "capacite", "seat"],
    "flights": ["mouvement", "vol", "flight", "mvt"],
}

# ---------------------------------------------------------------- 机型座位数
# 南航实际投放在洲际航线上的三舱布局
AIRCRAFT_SEATS = {
    "359": 314,   # A350-900  28J + 24W + 262Y
    "35A": 314,
    "A350": 314,
    "77W": 309,   # 777-300ER 4F + 34J + 44W + 227Y
    "773": 309,
    "B777": 309,
    "789": 269,
    "332": 218,
}

# ---------------------------------------------------------------- Amadeus
AMADEUS_HOSTS = {
    "production": "https://api.amadeus.com",
    "test": "https://test.api.amadeus.com",
}
