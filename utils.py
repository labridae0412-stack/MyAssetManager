import streamlit as st
import pandas as pd
import json
import base64
import re
import io
import unicodedata
from openai import OpenAI
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, timedelta, timezone
import traceback

# --- 定数定義 ---
# ★修正点: カテゴリ名を「楽天カード」→「Rカード」などに変更
CATEGORIES = [
    "食費", "外食費", "日用品", "娯楽(遊び費用)", "被服費", "医療費", 
    "光熱費", "住居費", "通信費", "保険", "教育費", "投資", 
    "立替", "利息", "給料", "手当", "賞与", "家賃", "保険代",
    "Rカード", "Mカード", "イオンカード", "投資振替", "はると振替", 
    "投資信託", "米国株式", "国内株式", "外国株式", "債券",
    "その他", "資産"
]
MEMBERS = ["マサ", "ユウ", "ハル", "共通"]
JST = timezone(timedelta(hours=9), 'JST')

# シート名設定
LOG_SHEET_NAME = "Transaction_Log"
MASTER_SHEET_NAME = "Category_Master" 

# --- 金融機関ごとの設定 ---
# ★修正点: キー名を「R銀行」「Rカード」「R証券」に変更
INSTITUTION_CONFIG = {
    "M銀行": { 
        "sheet_name": "Bank_DB", "encoding": "shift_jis",
        "date_col": "年月日", "store_col": "お取り扱い内容", 
        "expense_col": "お引出し", "income_col": "お預入れ", "balance_col": "残高"
    },
    "Rカード": { 
        "sheet_name": "Credit_DB", "encoding": "shift_jis",
        "date_col": "利用日", "store_col": "利用店名・商品名", 
        "amount_col": "支払総額", "member_col": "利用者"
    },
    "R証券": {
        "sheet_name": "Securities_DB", "encoding": "shift_jis",
        "custom_loader": "rakuten_sec_balance" 
    },
    # 必要に応じて他の銀行も設定
    "Y銀行": { "sheet_name": "Bank_DB", "date_col": "取引日", "store_col": "お取引内容", "amount_col": "出金金額", "encoding": "shift_jis" },
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

# --- 特殊CSV読み込み機能 ---

def extract_date_from_filename(filename):
    """ファイル名から日付(YYYYMMDD)を抽出する"""
    if not filename: return None
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y%m%d').date()
        except:
            return None
    return None

def load_rakuten_securities_csv(file_obj, encoding="shift_jis"):
    """
    R証券の保有商品一覧CSVを読み込む
    """
    try:
        # バイナリとして読み込み
        content = file_obj.getvalue().decode(encoding)
        lines = content.splitlines()
        
        start_row = 0
        found = False
        # 「■ 保有商品詳細」の行を探す
        for i, line in enumerate(lines):
            if "■ 保有商品詳細" in line:
                start_row = i + 2 # 見出しの2行下からヘッダー
                found = True
                break
        
        if not found:
            start_row = 0

        # メモリ上のCSVとして読み込む
        csv_io = io.StringIO("\n".join(lines[start_row:]))
        df = pd.read_csv(csv_io)
        return df
    except Exception as e:
        # エラー時はNoneを返し、呼び出し元で処理させる
        print(f"Read Error: {e}")
        return None

# --- カテゴリマスタ機能 ---

def load_category_master():
    client = get_gspread_client()
    try:
        sheet = client.open_by_key(st.secrets["SPREADSHEET_ID"]).worksheet(MASTER_SHEET_NAME)
        data = sheet.get_all_values()
        if len(data) <= 1: return {}
        return {row[0]: row[1] for row in data[1:] if row[0]}
    except:
        return {}

def normalize_text(text):
    if not isinstance(text, str): return str(text)
    normalized = unicodedata.normalize('NFKC', text)
    return normalized.replace(" ", "").replace("　", "")

def suggest_category(store_name, master_dict):
    if not store_name: return "未分類"
    target_store = normalize_text(store_name)
    for keyword, category in master_dict.items():
        if normalize_text(keyword) in target_store:
            return category
    return "未分類"

def update_category_master(new_mappings):
    if not new_mappings: return 0
    client = get_gspread_client()
    sheet = client.open_by_key(st.secrets["SPREADSHEET_ID"]).worksheet(MASTER_SHEET_NAME)
    current_master = load_category_master()
    
    rows_to_add = []
    for kw, cat in new_mappings.items():
        if kw and kw not in current_master:
            rows_to_add.append([kw, cat])
    
    if rows_to_add:
        sheet.append_rows(rows_to_add)
        return len(rows_to_add)
    return 0

def create_master_from_history():
    """Bank_DBのみを対象にマスタを作成"""
    client = get_gspread_client()
    spreadsheet = client.open_by_key(st.secrets["SPREADSHEET_ID"])
    history_mappings = {}
    target_config = {"name": "Bank_DB", "store_idx": 1, "cat_idx": 3}

    try:
        sheet = spreadsheet.worksheet(target_config["name"])
        data = sheet.get_all_values()
        if len(data) > 1:
            for row in data[1:]:
                if len(row) > max(target_config["store_idx"], target_config["cat_idx"]):
                    store = row[target_config["store_idx"]].strip()
                    cat = row[target_config["cat_idx"]].strip()
                    if store and cat and cat not in ["未分類", "その他", ""]:
                        history_mappings[store] = cat
    except:
        return 0
    return update_category_master(history_mappings)

# --- 既存の解析・保存ロジック ---

def analyze_receipt(image_bytes, mode="total"):
    # (既存コードと同じため省略せず記述)
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])
    categories_str = "/".join(CATEGORIES)
    
    if mode == "split":
        system_prompt = f"レシート解析。JSON出力。1. date, store. 2. items(name, amount). カテゴリ推測。"
    else:
        system_prompt = f"レシート解析。JSON出力。date, store, amount, category({categories_str})。"

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

def save_bulk_to_google_sheets(df_to_save, target_sheet_name, institution_name):
    client = get_gspread_client()
    try:
        spreadsheet_id = st.secrets["SPREADSHEET_ID"]
        try:
            sheet = client.open_by_key(spreadsheet_id).worksheet(target_sheet_name)
        except gspread.WorksheetNotFound:
            st.error(f"エラー: シート '{target_sheet_name}' が見つかりません。")
            return False, "Sheet not found", 0

        existing_data = sheet.get_all_values()
        existing_signatures = set()

        if len(existing_data) > 1:
            for row in existing_data[1:]:
                if len(row) < 7: continue 
                
                amount_clean = str(row[4]).replace(',', '').replace('円', '')
                inst_val = str(row[7]) if len(row) > 7 else ""
                balance_val = str(row[8]) if len(row) > 8 else ""
                balance_clean = balance_val.replace(',', '').replace('円', '')
                
                signature = (
                    str(row[0]), str(row[1]), str(row[2]), 
                    amount_clean, str(row[6]), inst_val, balance_clean
                )
                existing_signatures.add(signature)

        now_jst = datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')
        rows_to_append = []
        skipped_count = 0

        for _, row in df_to_save.iterrows():
            raw_bal = row.get('balance', '')
            bal_str = str(raw_bal).replace(',', '').replace('円', '').replace('nan', '').replace('None', '')
            try:
                if bal_str: bal_str = str(int(float(bal_str)))
            except: pass

            new_signature = (
                str(row['date']), str(row['store']), str(row['category_1']), 
                str(row['amount']), str(row['member']), str(institution_name), bal_str
            )

            if new_signature not in existing_signatures:
                rows_to_append.append([
                    str(row['date']), str(row['store']), str(row['category_1']), 
                    str(row['category_2']), int(row['amount']), now_jst, 
                    str(row['member']), str(institution_name), bal_str
                ])
                existing_signatures.add(new_signature)
            else:
                skipped_count += 1
            
        if rows_to_append:
            sheet.append_rows(rows_to_append)
            return True, len(rows_to_append), skipped_count
        else:
            return True, 0, skipped_count

    except Exception as e:
        return False, str(e), 0

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
    return date_obj.strftime('%Y-%m')