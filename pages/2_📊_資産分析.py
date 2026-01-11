import streamlit as st
import pandas as pd
import utils # 共通機能を読み込み

st.set_page_config(page_title="データ確認", layout="wide")

# ★全ページでログインチェックを行う
utils.check_password()

st.title("📊 月別支出集計 (25日締め)")

if st.button("データを更新"):
    st.cache_data.clear()

# utilsからデータを読み込む
df = utils.load_data_from_sheets()

if df is not None and not df.empty:
    # --- 前処理 ---
    df['amount'] = pd.to_numeric(
        df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), 
        errors='coerce'
    ).fillna(0).astype(int)

    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date'])
    # utilsの関数を使用
    df['fiscal_month'] = df['date'].apply(utils.get_fiscal_month)
    
    if 'member' in df.columns:
        df['member'] = df['member'].fillna("").astype(str)
    else:
        df['member'] = ""

    # 表示用カテゴリ
    def make_display_category(row):
        cat = str(row['category'])
        mem = str(row['member'])
        if mem and mem.strip() != "":
            return f"{cat}({mem})"
        else:
            return cat

    df['display_category'] = df.apply(make_display_category, axis=1)

    # --- 表示 ---
    month_list = sorted(df['fiscal_month'].unique(), reverse=True)
    selected_month = st.selectbox("対象年月を選択", month_list)
    month_df = df[df['fiscal_month'] == selected_month]

    total_spend = month_df['amount'].sum()
    st.divider()
    col1, col2 = st.columns(2)
    col1.metric(f"{selected_month}月度の総支出", f"¥{total_spend:,}")
    col2.metric("データ件数", f"{len(month_df)} 件")
    
    st.write("### 🥧 カテゴリ別支出")
    cat_sum = month_df.groupby('display_category')['amount'].sum().reset_index().sort_values('amount', ascending=False)
    st.bar_chart(cat_sum.set_index('display_category'))

    st.write("### 📝 詳細データ")
    view_df = month_df.copy()
    view_df = view_df.rename(columns={
        'date': '日付',
        'store': '購入箇所',
        'display_category': 'カテゴリー', 
        'amount': '金額',
        'timestamp': '入力日',
        'member': '対象者',
        'fiscal_month': '対象年月'
    })
    
    display_cols = ['日付', 'カテゴリー', '購入箇所', '金額', '対象者', '入力日']
    view_df = view_df.sort_values('日付', ascending=False)
    st.dataframe(view_df[display_cols])
    
else:
    st.info("データがありません。")