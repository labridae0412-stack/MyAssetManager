import streamlit as st
import pandas as pd
import json
import base64
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date, timedelta, timezone
import traceback

# --- 定数定義 ---
CATEGORIES = ["食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", "その他"]
MEMBERS = ["マサ", "ユウ", "ハル"]
JST = timezone(timedelta(hours=9), 'JST')

# --- 共通関数: パスワード認証 (全ページで呼び出す) ---
def check_password():
    """Returns `True` if the user had the correct password."""
    if "APP_PASSWORD" not in st.secrets:
        st.error("設定エラー: Secretsに 'APP_PASSWORD' を設定してください。")
        st.stop()
        return False

    if 'authenticated' not in st.session_state:
        st.session_state['authenticated'] = False

    if st.session_state['authenticated']:
        return True

    # パスワード入力画面のスタイル
    st.markdown("""
    <style>
        div[data-testid="stTextInput"] input { font-size: 20px; padding: 15px; }
        div[data-testid="stButton"] button { height: 3em; font-size: 18px; }
    </style>
    """, unsafe_allow_html=True)

    st.title("🔐 ログイン")
    password = st.text_input("Password", type="password", key="login_pass")
    if st.button("ログイン"):
        if password == st.secrets["APP_PASSWORD"]:
            st.session_state['authenticated'] = True
            st.rerun()
        else:
            st.error("パスワードが違います")
    
    # 認証されていない場合はここで処理を止める
    st.stop()
    return False

# --- 関数: OpenAI解析 ---
def analyze_receipt(image_bytes, mode="total"):
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    categories_str = "/".join(CATEGORIES)

    if mode == "split":
        system_prompt = f"""
        レシート画像を解析し、JSONで出力せよ。
        1. date(YYYY-MM-DD)とstore(店名)を抽出。
        2. 購入品目を全てリスト化し、key名を'items'とする。
        3. itemsの中身は {{"name": "商品名", "amount": 金額(数値)}} の形式にする。
        """
    else:
        system_prompt = f"レシート画像からdate(YYYY-MM-DD),store,amount(合計金額・数値),category({categories_str})をJSONで抽出せよ。"

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
        return json.loads(content), content
    except Exception as e:
        return None, str(e)

# --- 関数: Google Sheets保存 ---
def save_to_google_sheets(data):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)

    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        
        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')

        # [日付, 店名, カテゴリ, 金額, 対象者, タイムスタンプ]
        row = [
            str(data['date']), 
            data['store'], 
            data['category'], 
            data['amount'], 
            data['member'], 
            now_jst
        ]
        sheet.append_row(row)
        return True
    except Exception as e:
        st.error(f"保存エラー: {e}")
        return False

# --- 関数: 会計月の計算 (25日締め) ---
def get_fiscal_month(date_obj):
    if date_obj.day >= 25:
        next_month = (date_obj.replace(day=1) + pd.DateOffset(months=1))
        return next_month.strftime('%Y-%m')
    else:
        return date_obj.strftime('%Y-%m')

# --- 関数: データ読み込み ---
def load_data_from_sheets():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = dict(st.secrets["gcp_service_account"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        sheet = client.open_by_key(spreadsheet_id).sheet1
        data = sheet.get_all_values()
        
        if len(data) <= 1: return pd.DataFrame()
        df = pd.DataFrame(data[1:]) 
        
        # 列ズレ補正ロジック
        if df.shape[1] == 5:
            df.columns = ["date", "store", "category", "amount", "timestamp"]
            df["member"] = ""
        elif df.shape[1] >= 6:
            df = df.iloc[:, :6]
            df.columns = ["date", "store", "category", "amount", "member", "timestamp"]
            
            def align_row(row):
                m = str(row['member']).strip()
                if (m.startswith("202") and "-" in m) or (m.startswith("203") and "-" in m):
                    row['timestamp'] = row['member']
                    row['member'] = ""
                return row
            
            df = df.apply(align_row, axis=1)
        else:
            return pd.DataFrame()
        return df

    except Exception as e:
        st.error(f"読み込みエラー: {e}")
        return None