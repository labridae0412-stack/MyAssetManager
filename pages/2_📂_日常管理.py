import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="日常管理", layout="wide")
utils.check_password()

st.title("📊 日常収支管理")

# データ更新ボタン
if st.button("データを更新"):
    st.cache_data.clear()
    st.rerun()

# データの読み込み
df = utils.load_data_from_sheets()

if df is not None and not df.empty:
    # --- データ前処理 ---
    # 金額を数値に変換
    df['amount'] = pd.to_numeric(
        df['amount'].astype(str).str.replace(',', '').str.replace('円', ''), 
        errors='coerce'
    ).fillna(0).astype(int)

    # 日付型へ変換
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    df = df.dropna(subset=['date']) # 日付がない行は除外

    # 会計月（25日締め）カラムを作成
    df['fiscal_month'] = df['date'].apply(utils.get_fiscal_month)

    # メンバー情報の欠損埋め
    if 'member' not in df.columns:
        df['member'] = "共通"
    df['member'] = df['member'].fillna("共通").replace("", "共通")

    # 表示用カテゴリ作成（カテゴリ + 対象者）
    df['display_category'] = df['category'] + " (" + df['member'] + ")"

    # --- 画面表示 ---
    
    # 1. 月選択
    month_list = sorted(df['fiscal_month'].unique(), reverse=True)
    if not month_list:
        st.warning("有効な日付データが見つかりません。")
        st.stop()
        
    selected_month = st.selectbox("対象年月を選択", month_list)
    
    # 選択された月のデータのみ抽出
    month_df = df[df['fiscal_month'] == selected_month]

    # 2. 重要指標（KPI）表示
    total_spend = month_df['amount'].sum()
    
    st.divider()
    col1, col2, col3 = st.columns(3)
    col1.metric(f"{selected_month}月度の総支出", f"¥{total_spend:,}")
    col2.metric("データ件数", f"{len(month_df)} 件")
    # ここに予算機能が入る予定
    col3.metric("予算残高", "設定待ち", delta_color="off")

    # 3. グラフ表示
    st.write("### 🥧 カテゴリ別支出構成")
    if not month_df.empty:
        # カテゴリ×対象者ごとの集計
        chart_data = month_df.groupby(['category', 'member'])['amount'].sum().reset_index()
        
        # 棒グラフ（積み上げ）
        st.bar_chart(
            chart_data,
            x="category",
            y="amount",
            color="member",
            stack=True
        )
    else:
        st.info("この月のデータはありません。")

    # 4. 詳細データテーブル
    st.write("### 📝 明細リスト")
    if not month_df.empty:
        # 表示する列を見やすく整理
        view_df = month_df[['date', 'store', 'category', 'amount', 'member']].copy()
        view_df.columns = ['日付', '店名/摘要', 'カテゴリ', '金額', '対象者']
        
        # 日付の新しい順に並べ替え
        view_df = view_df.sort_values('日付', ascending=False)
        
        st.dataframe(
            view_df,
            column_config={
                "金額": st.column_config.NumberColumn(format="%d円")
            },
            hide_index=True,
            use_container_width=True
        )

else:
    st.info("データが見つかりません。")
    st.markdown("""
    **確認事項:**
    1. スプレッドシートの `Transaction_Log` シートにデータが入っていますか？
    2. `シート1` にあるデータを `Transaction_Log` にコピーしてください。
    """)