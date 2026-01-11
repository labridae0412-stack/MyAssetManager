import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="CSV一括登録", layout="wide")
utils.check_password()

st.title("📥 銀行・カード明細の一括登録")

st.markdown("""
銀行やクレジットカードのサイトからダウンロードしたCSVファイルをアップロードしてください。
列を割り当てて、まとめて家計簿データベース(`Transaction_Log`)に登録します。
""")

# 1. ファイルアップロード
uploaded_file = st.file_uploader("CSVファイルをドラッグ＆ドロップ", type=["csv"])

if uploaded_file:
    # CSV読み込み (エンコーディング自動判別)
    try:
        df = pd.read_csv(uploaded_file)
    except UnicodeDecodeError:
        # 日本の銀行CSVによくあるShift-JISで再トライ
        uploaded_file.seek(0)
        df = pd.read_csv(uploaded_file, encoding="shift_jis")

    st.write("### プレビュー (最初の5行)")
    st.dataframe(df.head())

    st.markdown("---")
    st.subheader("🛠 列の割り当て設定")
    
    # 列選択用のプルダウンを作成
    cols = df.columns.tolist()
    
    col1, col2, col3 = st.columns(3)
    date_col = col1.selectbox("「日付」の列は？", cols, index=0 if len(cols)>0 else None)
    store_col = col2.selectbox("「利用先/摘要」の列は？", cols, index=1 if len(cols)>1 else None)
    amount_col = col3.selectbox("「金額(出金)」の列は？", cols, index=2 if len(cols)>2 else None)
    
    # 追加設定
    col1, col2 = st.columns(2)
    default_cat = col1.selectbox("デフォルトのカテゴリ", ["その他"] + utils.CATEGORIES)
    default_mem = col2.selectbox("デフォルトの対象者", utils.MEMBERS)

    # 変換プレビューボタン
    if st.button("変換して確認する"):
        try:
            # 必要な列だけ抽出して整形
            import_df = pd.DataFrame()
            import_df['date'] = pd.to_datetime(df[date_col], errors='coerce').dt.date
            import_df['store'] = df[store_col].fillna("")
            
            # 金額のクリーニング (カンマ除去など)
            import_df['amount'] = df[amount_col].astype(str).str.replace(',', '').str.replace('円', '')
            import_df['amount'] = pd.to_numeric(import_df['amount'], errors='coerce').fillna(0).astype(int)
            
            # マイナス値の処理（支出として正の値にするか選択可能にするのが理想だが、一旦絶対値にするかそのままにするか）
            # 今回は「出金」列を選んだと仮定し、もしマイナスで表現されている場合は正に直す処理を入れる
            import_df['amount'] = import_df['amount'].abs()

            import_df['category'] = default_cat
            import_df['member'] = default_mem

            # 日付が無効な行（合計行など）を除外
            import_df = import_df.dropna(subset=['date'])

            st.session_state['csv_import_data'] = import_df
            st.success("変換に成功しました！下の表で内容を確認・修正してください。")

        except Exception as e:
            st.error(f"変換エラー: {e}")

    # 最終確認と登録
    if 'csv_import_data' in st.session_state:
        st.write("### ✅ 登録データの最終確認")
        st.info("カテゴリなどはここで直接修正できます。")
        
        edited_df = st.data_editor(
            st.session_state['csv_import_data'],
            num_rows="dynamic",
            column_config={
                "date": st.column_config.DateColumn("日付"),
                "category": st.column_config.SelectboxColumn("カテゴリ", options=utils.CATEGORIES + ["その他"]),
                "member": st.column_config.SelectboxColumn("対象者", options=utils.MEMBERS),
                "amount": st.column_config.NumberColumn("金額")
            },
            hide_index=True
        )

        if st.button("これでデータベースに登録する"):
            success, msg = utils.save_bulk_to_google_sheets(edited_df)
            if success:
                st.balloons()
                st.success(f"{msg} 件のデータを登録しました！")
                # 完了したらデータをクリア
                del st.session_state['csv_import_data']
            else:
                st.error(f"登録失敗: {msg}")