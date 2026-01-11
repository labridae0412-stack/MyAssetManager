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
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "光熱費", "住居費", "通信費", "保険", "教育費", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル", "共通"]
JST = timezone(timedelta(hours=9), 'JST')

# ★重要: データを保存するスプレッドシートの「シート名」
# スプレッドシート側で、履歴を入れるシートの名前をこれに合わせてください
LOG_SHEET_NAME = "Transaction_Log" 

# --- 共通関数: パスワード認証 ---
def check_password():
    if "APP_PASSWORD" not in st.secrets:
        st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
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

# --- 関数: OpenAI解析 ---
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
        return json.loads(response.choices[0].message.content), ""
    except Exception as e:
        return None, str(e)

# --- 関数: Google Sheets接続 ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

# --- 関数: データ保存 (単票) ---
def save_to_google_sheets(data):
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        # シート名を指定して開く
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(LOG_SHEET_NAME)
        except:
            # 指定シートがない場合は1枚目を開く
            sheet = client.open_by_key(spreadsheet_id).sheet1

        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

        # ★修正: 列の並び順をスプレッドシートに合わせる
        # [A:日付, B:店名, C:カテゴリ, D:金額, E:入力日, F:対象者]
        row = [
            str(data['date']), 
            data['store'], 
            data['category'], 
            data['amount'], 
            now_jst,          # E列: 入力日
            data['member']    # F列: 対象者
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

# --- 関数: データ一括保存 (CSV用) ---
def save_bulk_to_google_sheets(df_to_save):
    """
    Pandas DataFrameを受け取り、まとめてスプレッドシートに追加する
    df_to_saveの期待する列: [date, store, category, amount, member]
    """
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(LOG_SHEET_NAME)
        except:
            sheet = client.open_by_key(spreadsheet_id).sheet1

        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        
        # 書き込み用データの作成（リストのリスト）
        rows_to_append = []
        for _, row in df_to_save.iterrows():
            rows_to_append.append([
                str(row['date']),
                str(row['store']),
                str(row['category']),
                int(row['amount']),
                now_jst,            # E列: 入力日
                str(row['member'])  # F列: 対象者
            ])
            
        sheet.append_rows(rows_to_append)
        return True, len(rows_to_append)
    except Exception as e:
        return False, str(e)

# --- 関数: データ読み込み ---
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
        
        # ヘッダー行を除いてDF化
        df = pd.DataFrame(data[1:])
        
        # 列数が足りない場合のガード
        if df.shape[1] >= 6:
            # 列定義をスプレッドシートに合わせる
            df = df.iloc[:, :6]
            df.columns = ["date", "store", "category", "amount", "timestamp", "member"]
        else:
            # 古い形式や列不足の場合の簡易処理
            df.columns = [f"col_{i}" for i in range(df.shape[1])]
            
        return df
    except Exception as e:
        st.error(f"読み込みエラー: {e}")
        return None

# --- 関数: 会計月計算 ---
def get_fiscal_month(date_obj):
    if date_obj.day >= 25:
        next_month = (date_obj.replace(day=1) + pd.DateOffset(months=1))
        return next_month.strftime('%Y-%m')
    else:
        return date_obj.strftime('%Y-%m')