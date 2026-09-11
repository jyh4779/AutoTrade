
import requests
import json
import pandas as pd
import time
from .kis_auth import KISAuth
from src.utils.decorators import retry

class KISDomestic:
    def __init__(self):
        self.auth = KISAuth()

    def get_current_quote(self, code):
        """KRX current price and cumulative volume from the same response.

        This endpoint may omit exchange timestamps. Receipt time is explicitly
        labelled, never represented as a verified exchange observation time.
        """
        from datetime import datetime, timezone, timedelta
        import math
        try:
            for attempt in range(3):
                data = requests.get(
                    self.auth.base_url + '/uapi/domestic-stock/v1/quotations/inquire-price',
                    headers=self.auth.get_headers('FHKST01010100'),
                    params={'fid_cond_mrkt_div_code': 'J', 'fid_input_iscd': code}, timeout=10).json()
                if data.get('rt_cd') == '0':
                    break
                if attempt < 2:
                    time.sleep(1+attempt)
            if data.get('rt_cd') != '0':
                return None
            o = data['output']
            received = datetime.now(timezone(timedelta(hours=9)))
            price, volume = float(o['stck_prpr']), float(o['acml_vol'])
            if price <= 0 or volume < 0 or not all(math.isfinite(x) for x in (price,volume)):
                return None
            return dict(price=price, cumulative_volume=volume, market='KRX',
                        received_at=received.isoformat(), provider_date=o.get('stck_bsop_date'),
                        asof_basis='receipt', endpoint='inquire-price')
        except Exception:
            return None

    def get_cancelable_order(self, order_no, code):
        # Official preflight query must succeed before any cancellation request.
        if self.auth.is_vts:
            return None  # This preflight endpoint is real-account only.
        cano, product = self.auth.get_account_info()
        headers=self.auth.get_headers('TTTC0084R')
        params=dict(CANO=cano,ACNT_PRDT_CD=product,INQR_DVSN_1='0',INQR_DVSN_2='0',CTX_AREA_FK100='',CTX_AREA_NK100='')
        try:
            for _ in range(20):
                response=requests.get(self.auth.base_url+'/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl',
                                      headers=headers,params=params,timeout=10)
                data=response.json()
                if data.get('rt_cd')!='0':return None
                for row in data.get('output',[]):
                    if str(row.get('odno','')).lstrip('0')==str(order_no).lstrip('0') and row.get('pdno')==code:
                        return dict(order_no=order_no,orgno=row.get('krx_fwdg_ord_orgno'),qty=int(row.get('psbl_qty',0)))
                if response.headers.get('tr_cont') not in ('M','F'):return None
                params['CTX_AREA_FK100']=data.get('ctx_area_fk100','')
                params['CTX_AREA_NK100']=data.get('ctx_area_nk100','')
                headers['tr_cont']='N'
        except Exception:
            pass
        return None

    def cancel_order(self, preview):
        if not preview or preview['qty']<=0 or not preview.get('orgno'):
            return {'rt_cd':'1','msg1':'cancel preflight unavailable'}
        cano,product=self.auth.get_account_info()
        payload=dict(CANO=cano,ACNT_PRDT_CD=product,KRX_FWDG_ORD_ORGNO=preview['orgno'],
                     ORGN_ODNO=preview['order_no'],ORD_DVSN='01',RVSE_CNCL_DVSN_CD='02',
                     ORD_QTY=str(preview['qty']),ORD_UNPR='0',QTY_ALL_ORD_YN='Y',EXCG_ID_DVSN_CD='KRX')
        try:
            return requests.post(self.auth.base_url+'/uapi/domestic-stock/v1/trading/order-rvsecncl',
                headers=self.auth.get_headers('VTTC0013U' if self.auth.is_vts else 'TTTC0013U'),json=payload,timeout=10).json()
        except Exception:
            return {'rt_cd':'9','ambiguous':True,'msg1':'cancel response unavailable'}

    @retry(max_tries=3, delay_sec=1.0)
    def get_current_price(self, code):
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self.auth.get_headers("FHKST01010100") # Current Price TR ID
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": code
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get('rt_cd') == '0':
                return float(data['output']['stck_prpr'])
        except: pass
        return None

    def order_market_price(self, code, qty, is_buy=True):
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0802U" if is_buy else "TTTC0801U"
        if self.auth.is_vts:
            tr_id = "VTTC0802U" if is_buy else "VTTC0801U"
            
        headers = self.auth.get_headers(tr_id)
        # Final adjustment based on latest official real-investment requirements
        headers["custtype"] = "P"
        
        cano, prdt_cd = self.auth.get_account_info()
        
        # Comprehensive payload for real investment
        # FIXED: ORD_SQTY -> ORD_QTY, added EXCG_ID_DVSN_CD
        payload = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "PDNO": code,
            "ORD_DVSN": "01", # Market Price
            "ORD_QTY": str(qty), # Changed from ORD_SQTY
            "ORD_UNPR": "0",
            "EXCG_ID_DVSN_CD": "KRX", # Mandatory for real
            "SLL_TYPE": "01", # Normal sell
            "CNDT_PRIC": "",
            "CTAC_TLNO": "",
            "MGN_DVSN": "01",
            "LOAN_DT": "",
            "ORD_OBJT_CBLC_DVSN_CD": "",
            "LOAN_CLS_CODE": "",
            "RFLG_CONF_NO": "",
            "ALGO_NO": ""
        }
        
        # Virtual account needs an empty OFL_YN
        if self.auth.is_vts:
            payload["OFL_YN"] = ""
            # VTS might use ORD_SQTY? Let's keep ORD_QTY as it worked for real.
            # Official doc says VTS also uses similar structure but let's be careful.
            # Actually, standard is ORD_QTY for TTTC0802U.

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            return {"rt_cd": "9", "ambiguous": True, "msg1": "order response unavailable"}

    @retry(max_tries=3, delay_sec=1.0)
    def get_execution_detail(self, order_no, code="", is_buy=True, date=None):
        """주문번호로 실제 체결 내역(체결평균가, 체결수량, 체결금액)을 조회합니다."""
        from datetime import datetime
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "VTTC8001R" if self.auth.is_vts else "TTTC8001R"
        headers = self.auth.get_headers(tr_id)
        cano, prdt_cd = self.auth.get_account_info()
        today = date or datetime.now().strftime("%Y%m%d")

        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "INQR_STRT_DT": today,
            "INQR_END_DT": today,
            "SLL_BUY_DVSN_CD": "02" if is_buy else "01",
            "INQR_DVSN": "00",
            "PDNO": code,
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": order_no,
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                items = data.get("output1", [])
                for item in items:
                    if (str(item.get('odno','')).lstrip('0') == str(order_no).lstrip('0')
                            and (not code or item.get('pdno') == code)):
                        return {
                            "avg_price": float(item.get("avg_prvs", 0)),
                            "qty": int(item.get("tot_ccld_qty", 0)),
                            "total_amt": float(item.get("tot_ccld_amt", 0)),
                            "name": item.get("prdt_name", ""),
                            "order_qty": int(item.get('ord_qty', 0)),
                            "remaining_qty": int(item['rmn_qty']) if item.get('rmn_qty') not in (None, '') else None,
                            "cancelled": item.get('cncl_yn') == 'Y',
                        }
        except Exception as e:
            print(f"[WARN] 체결 내역 조회 실패: {e}")
        return None

    @retry(max_tries=3, delay_sec=1.0)
    def get_daily_executions(self, date=None):
        """당일(또는 지정일) 전체 체결 내역을 조회합니다."""
        from datetime import datetime
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
        tr_id = "VTTC8001R" if self.auth.is_vts else "TTTC8001R"
        headers = self.auth.get_headers(tr_id)
        cano, prdt_cd = self.auth.get_account_info()

        if date is None:
            date = datetime.now().strftime("%Y%m%d")

        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "INQR_STRT_DT": date,
            "INQR_END_DT": date,
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "01",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = res.json()
            if data.get("rt_cd") == "0":
                return data.get("output1", [])
        except Exception as e:
            print(f"[WARN] 체결 내역 일괄 조회 실패: {e}")
        return []

    def order_limit_price(self, code, qty, price, is_buy=True):
        url = f"{self.auth.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        tr_id = "TTTC0802U" if is_buy else "TTTC0801U"
        if self.auth.is_vts:
            tr_id = "VTTC0802U" if is_buy else "VTTC0801U"
            
        headers = self.auth.get_headers(tr_id)
        cano, prdt_cd = self.auth.get_account_info()
        
        payload = {
            "CANO": cano,
            "ACNT_PRDT_CD": prdt_cd,
            "PDNO": code,
            "ORD_DVSN": "00", # Limit Price
            "ORD_QTY": str(qty), # Changed from ORD_SQTY
            "ORD_UNPR": str(int(price)),
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "01",
            "CNDT_PRIC": "",
            "CTAC_TLNO": "",
            "MGN_DVSN": "01", 
            "LOAN_DT": "",
            "ORD_OBJT_CBLC_DVSN_CD": "",
            "LOAN_CLS_CODE": "",
            "RFLG_CONF_NO": "",
            "ALGO_NO": ""
        }
        
        if self.auth.is_vts:
            payload["OFL_YN"] = ""
        
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            return res.json()
        except Exception as e:
            return {"rt_cd": "9", "ambiguous": True, "msg1": "order response unavailable"}
