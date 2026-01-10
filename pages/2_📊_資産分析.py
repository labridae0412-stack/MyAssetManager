import streamlit as st
import pandas as pd
import utils

st.set_page_config(page_title="資産分析", layout="wide")
st.title("📊 資産・収支分析")

st.info("ここでスプレッドシートのデータを読み込み、グラフ化します。（実装予定）")

# 以下、実装イメージ
# df = utils.load_data_from_sheets() 
# st.bar_chart(df)