from pathlib import Path

RULE_VERSION = "2026.11.18.3"
TITLE = '设备校准证书与测量追溯'
SHORT = 'calibration-chain'
MODULES = ['证书接收', '设备别名', '有效区间', '量程匹配', '溯源链路', '测量裁决', '撤销复核']
HEADERS = ['cert', 'device', 'alias', 'parent', 'valid_from', 'valid_to', 'minimum', 'maximum', 'unit', 'revoked', 'measured_at', 'value', 'measure_unit', 'version']

# 误差带是可选输入。支持两列（误差数值 + 单位）或一列（例如 “±0.2 V”）。
# 同时接受常见英文/中文表头别名，旧档案无需改写即可补录误差带。
BAND_VALUE_HEADERS = [
    'error', 'uncertainty', 'tolerance', '误差', '不确定度', '允差',
]
BAND_UNIT_HEADERS = [
    'error_unit', 'uncertainty_unit', 'tolerance_unit',
    '误差单位', '不确定度单位', '允差单位',
]
BAND_COMBINED_HEADERS = [
    'error_band', 'band', '误差带',
]

SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "operations.csv"
BAND_SAMPLE = Path(__file__).resolve().parent.parent / "sample_data" / "edge_bands.csv"
LIMIT = 10000
