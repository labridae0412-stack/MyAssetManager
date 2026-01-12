import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import traceback

# --- 定数定義 ---
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "光熱費", "住居費", "通信費", "保険", "教育費", "投資", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル", "共通"]
JST = timezone(timedelta(hours=9), 'JST')

# シート名設定
LOG_SHEET_NAME = "Transaction_Log"

# 金融機関設定
INSTITUTION_CONFIG = {
    "M銀行": { 
        "sheet_name": "Bank_DB", 
        "date_col": "年月日",           # 修正: 日付 -> 年月日
        "store_col": "お取り扱い内容",   # 修正: 摘要 -> お取り扱い内容
        "amount_col": "お引出し",       # 修正: お引出し額 -> お引出し
        "encoding": "shift_jis" 
    },
    "Y銀行": { "sheet_name": "Bank_DB", "date_col": "取引日", "store_col": "お取引内容", "amount_col": "出金金額", "encoding": "shift_jis" },
    "R銀行": { "sheet_name": "Bank_DB", "date_col": "取引日", "store_col": "内容", "amount_col": "入出金", "encoding": "utf-8" },
    "R証券": { "sheet_name": "Securities_DB", "date_col": "受渡日", "store_col": "銘柄名", "amount_col": "受渡金額", "encoding": "shift_jis" },
    "Rクレ": { "sheet_name": "Credit_DB", "date_col": "利用日", "store_col": "利用店名・商品名", "amount_col": "支払総額", "encoding": "utf-8" },
    "Mクレ": { "sheet_name": "Credit_DB", "date_col": "利用日", "store_col": "利用店名", "amount_col": "金額", "encoding": "shift_jis" },
    "Iクレ": { "sheet_name": "Credit_DB", "date_col": "利用日", "store_col": "加盟店名", "amount_col": "利用金額", "encoding": "shift_jis" }
}

def check_password():
    if "APP_PASSWORD" not in st.secrets:
        st.error("設定エラー: Secrets不足")
        st.stop()
    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False
    if st.session_state['authenticated']:
        return True

    st.markdown("""<style>div[data-testid="stTextInput"] input { font-size: 20px; padding: 15px; } div[data-testid="stButton"] button { height: 3em; font-size: 18px; }</style>""", unsafe_allow_html=True)
    st.title("🔐 ログイン")
    password = st.text_input("Password", type="password", key="login_pass")
    if st.button("ログイン"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
            st.stop()

def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

def analyze_receipt(image_bytes, mode="total"):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    categories_str = "/".join(CATEGORIES)

    if mode == "split":
        system_prompt = f"レシート画像を解析し、JSONで出力せよ。1. date(YYYY-MM-DD), store(店名). 2. itemsリスト(name, amount). カテゴリは推測。"
    else:
        system_prompt = f"レシート画像からdate(YYYY-MM-DD),store,amount(数値),category({categories_str})をJSONで抽出せよ。"

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if not content: return None, "空の応答"
        return json.loads(content), ""
    except Exception as e:
        return None, str(e)

def save_to_google_sheets(data):
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(LOG_SHEET_NAME)
        except:
            sheet = client.open_by_key(spreadsheet_id).sheet1
        
        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        row = [str(data['date']), data['store'], data['category'], data['amount'], now_jst, data['member']]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

def save_bulk_to_google_sheets(df_to_save, target_sheet_name):
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(target_sheet_name)
        except gspread.WorksheetNotFound:
            st.error(f"エラー: シート '{target_sheet_name}' が見つかりません。")
            return False, "Sheet not found"

        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        rows_to_append = []
        for _, row in df_to_save.iterrows():
            rows_to_append.append([str(row['date']), str(row['store']), str(row['category']), int(row['amount']), now_jst, str(row['member'])])
        
        sheet.append_rows(rows_to_append)
        return True, len(rows_to_append)
    except Exception as e:
        return False, str(e)

def load_data_from_sheets():
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(LOG_SHEET_NAME)
        except:
            sheet = client.open_by_key(spreadsheet_id).sheet1
        
        data = sheet.get_all_values()
        if len(data) <= 1: return pd.DataFrame()
        
        df = pd.DataFrame(data[1:])
        if df.shape[1] >= 6:
            df = df.iloc[:, :6]
            df.columns = ["date", "store", "category", "amount", "timestamp", "member"]
        else:
            df.columns = [f"col_{i}" for i in range(df.shape[1])]
        return df
    except Exception as e:
        st.error(f"読み込みエラー: {e}")
        return None

def get_fiscal_month(date_obj):
    if date_obj.day >= 25:
        return (date_obj.replace(day=1) + pd.DateOffset(months=1)).strftime('%Y-%m')
    else:
        return date_obj.strftime('%Y-%m')