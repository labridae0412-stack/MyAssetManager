import streamlit as st
import utils # utils.pyを読み込む

st.set_page_config(page_title="AI資産管理マネージャー", page_icon="💰", layout="wide")

# ★ここでログインチェック (必須)
utils.check_password()

st.title("💰 AI資産管理マネージャー")

st.markdown("""
### ようこそ
左側のサイドバーから機能を選択してください。

- **🧾 レシート登録**: AIを使ってレシートを解析し、スプレッドシートに保存します（一括・分割対応）。
- **📊 資産分析**: 保存されたデータを読み込み、25日締めで集計・グラフ化します。

現在、認証済みです。
""")