"""KIS real-time WebSocket field layouts.

Verified against the official sample code, not reconstructed from memory:
https://github.com/koreainvestment/open-trading-api examples_user/domestic_stock
(`domestic_stock_functions_ws.py`, the `columns` lists for H0STCNT0/H0STASP0),
fetched 2026-09 while KIS_APP_KEY/KIS_APP_SECRET were not yet provisioned (see
docs/KIS_SETUP.md) - re-verify against a live payload once credentials exist,
since KIS does not publish a versioned schema guarantee for these fields.
"""

# H0STCNT0: 국내주식 실시간체결가 (real-time trade/execution price).
H0STCNT0_FIELDS = [
    "MKSC_SHRN_ISCD",
    "STCK_CNTG_HOUR",
    "STCK_PRPR",
    "PRDY_VRSS_SIGN",
    "PRDY_VRSS",
    "PRDY_CTRT",
    "WGHN_AVRG_STCK_PRC",
    "STCK_OPRC",
    "STCK_HGPR",
    "STCK_LWPR",
    "ASKP1",
    "BIDP1",
    "CNTG_VOL",
    "ACML_VOL",
    "ACML_TR_PBMN",
    "SELN_CNTG_CSNU",
    "SHNU_CNTG_CSNU",
    "NTBY_CNTG_CSNU",
    "CTTR",
    "SELN_CNTG_SMTN",
    "SHNU_CNTG_SMTN",
    "CCLD_DVSN",
    "SHNU_RATE",
    "PRDY_VOL_VRSS_ACML_VOL_RATE",
    "OPRC_HOUR",
    "OPRC_VRSS_PRPR_SIGN",
    "OPRC_VRSS_PRPR",
    "HGPR_HOUR",
    "HGPR_VRSS_PRPR_SIGN",
    "HGPR_VRSS_PRPR",
    "LWPR_HOUR",
    "LWPR_VRSS_PRPR_SIGN",
    "LWPR_VRSS_PRPR",
    "BSOP_DATE",
    "NEW_MKOP_CLS_CODE",
    "TRHT_YN",
    "ASKP_RSQN1",
    "BIDP_RSQN1",
    "TOTAL_ASKP_RSQN",
    "TOTAL_BIDP_RSQN",
    "VOL_TNRT",
    "PRDY_SMNS_HOUR_ACML_VOL",
    "PRDY_SMNS_HOUR_ACML_VOL_RATE",
    "HOUR_CLS_CODE",
    "MRKT_TRTM_CLS_CODE",
    "VI_STND_PRC",
]

# H0STASP0: 국내주식 실시간호가 (real-time orderbook / asking price), 10 levels.
H0STASP0_FIELDS = (
    ["MKSC_SHRN_ISCD", "BSOP_HOUR", "HOUR_CLS_CODE"]
    + [f"ASKP{i}" for i in range(1, 11)]
    + [f"BIDP{i}" for i in range(1, 11)]
    + [f"ASKP_RSQN{i}" for i in range(1, 11)]
    + [f"BIDP_RSQN{i}" for i in range(1, 11)]
    + [
        "TOTAL_ASKP_RSQN",
        "TOTAL_BIDP_RSQN",
        "OVTM_TOTAL_ASKP_RSQN",
        "OVTM_TOTAL_BIDP_RSQN",
        "ANTC_CNPR",
        "ANTC_CNQN",
        "ANTC_VOL",
        "ANTC_CNTG_VRSS",
        "ANTC_CNTG_VRSS_SIGN",
        "ANTC_CNTG_PRDY_CTRT",
        "ACML_VOL",
        "TOTAL_ASKP_RSQN_ICDC",
        "TOTAL_BIDP_RSQN_ICDC",
        "OVTM_TOTAL_ASKP_ICDC",
        "OVTM_TOTAL_BIDP_ICDC",
        "STCK_DEAL_CLS_CODE",
    ]
)
