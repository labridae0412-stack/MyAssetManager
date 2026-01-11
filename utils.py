import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone

# --- 定数定義 ---
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "光熱費", "住居費", "通信費", "保険", "教育費", "投資", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル", "共通"]
JST = timezone(timedelta(hours=9), 'JST')

# --- 金融機関ごとの設定（ここをCSVに合わせて調整します） ---
# sheet_name: 保存先のシート名
# date_col: CSV内の「日付」の列名
# store_col: CSV内の「摘要/店名」の列名
# amount_col: CSV内の「金額」の列名
# encoding: 文字コード (shift_jis または utf-8)

INSTITUTION_CONFIG = {
    "M銀行": {
        "sheet_name": "Bank_DB",
        "date_col": "日付",          # ★実際のCSVヘッダーに合わせて変更してください
        "store_col": "摘要",         # ★実際のCSVヘッダーに合わせて変更してください
        "amount_col": "お引出し額",  # ★実際のCSVヘッダーに合わせて変更してください
        "encoding": "shift_jis"
    },
    "Y銀行": {
        "sheet_name": "Bank_DB",
        "date_col": "取引日",
        "store_col": "お取引内容",
        "amount_col": "出金金額",
        "encoding": "shift_jis"
    },
    "R銀行": {
        "sheet_name": "Bank_DB",
        "date_col": "取引日",
        "store_col": "内容",
        "amount_col": "入出金",
        "encoding": "utf-8"
    },
    "R証券": {
        "sheet_name": "Securities_DB",
        "date_col": "受渡日",
        "store_col": "銘柄名",
        "amount_col": "受渡金額",
        "encoding": "shift_jis"
    },
    "Rクレ": {
        "sheet_name": "Credit_DB",
        "date_col": "利用日",
        "store_col": "利用店名・商品名",
        "amount_col": "支払総額",
        "encoding": "utf-8" # 楽天系はUTF-8が多い傾向
    },
    "Mクレ": {
        "sheet_name": "Credit_DB",
        "date_col": "利用日",
        "store_col": "利用店名",
        "amount_col": "金額",
        "encoding": "shift_jis"
    },
    "Iクレ": {
        "sheet_name": "Credit_DB",
        "date_col": "利用日",
        "store_col": "加盟店名",
        "amount_col": "利用金額",
        "encoding": "shift_jis"
    }
}

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

# --- 関数: Google Sheets接続 ---
def get_gspread_client():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

# --- 関数: データ一括保存 (シート指定対応版) ---
def save_bulk_to_google_sheets(df_to_save, target_sheet_name):
    """
    Pandas DataFrameを受け取り、指定されたシートに追加する
    """
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        
        # シートが存在するか確認し、なければ作成するロジックを入れると親切ですが
        # 今回は事前に作ってある前提で進めます（エラーハンドリングのみ）
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(target_sheet_name)
        except gspread.WorksheetNotFound:
            st.error(f"エラー: スプレッドシートに '{target_sheet_name}' というシートが見つかりません。作成してください。")
            return False, "Sheet not found"

        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        
        rows_to_append = []
        for _, row in df_to_save.iterrows():
            rows_to_append.append([
                str(row['date']),
                str(row['store']),
                str(row['category']),
                int(row['amount']),
                now_jst,            # 入力日
                str(row['member'])  # 対象者
            ])
            
        sheet.append_rows(rows_to_append)
        return True, len(rows_to_append)
    except Exception as e:
        return False, str(e)

# --- 他の関数（analyze_receipt等は既存のまま維持してください） ---
# (省略: 以前のコードにある analyze_receipt, save_to_google_sheets, load_data_from_sheets, get_fiscal_month はそのまま残してください)
# ※ load_data_from_sheets は後で「全シート結合」に対応する必要がありますが、一旦そのままでOKです。