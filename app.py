import streamlit as st
import pandas as pd
import pdfplumber
import plotly.express as px
import io
import os

st.set_page_config(page_title="Bank Statement Analyzer", layout="wide")

# --- Visitor Counter Engine ---
def track_visitors():
    file_path = "visitor_count.txt"
    
    # Create the file with '0' if it is the very first time the app is run
    if not os.path.exists(file_path):
        with open(file_path, "w") as f:
            f.write("0")
            
    # Read the current number of visitors
    with open(file_path, "r") as f:
        try:
            count = int(f.read().strip())
        except ValueError:
            count = 0
            
    # If this specific user hasn't been counted yet during this visit, add 1
    if 'has_been_counted' not in st.session_state:
        count += 1
        with open(file_path, "w") as f:
            f.write(str(count))
        # Mark this user as counted so clicking buttons doesn't inflate the number
        st.session_state['has_been_counted'] = True
        
    return count

# Get the current visitor count
total_visitors = track_visitors()

# --- Helper Functions ---
def parse_pdf(file):
    all_data = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            table = page.extract_table()
            if table:
                all_data.extend(table)
    if all_data:
        df = pd.DataFrame(all_data[1:], columns=all_data[0])
        return df
    return pd.DataFrame()

def standardize_dataframe(df):
    df = df.astype(str)
    column_mapping = {
        'Txn Date': 'Date', 'Value Date': 'Date', 'Transaction Date': 'Date',
        'Narration': 'Description', 'Particulars': 'Description', 'Remarks': 'Description',
        'Cheque/Ref.No.': 'Ref/Cheque No', 'Chq/Ref Number': 'Ref/Cheque No', 'Ref No.': 'Ref/Cheque No',
        'Withdrawal': 'Debit', 'Debit': 'Debit', 'Dr': 'Debit',
        'Deposit': 'Credit', 'Credit': 'Credit', 'Cr': 'Credit',
        'Closing Balance': 'Balance', 'Balance': 'Balance'
    }
    df.rename(columns=lambda x: column_mapping.get(x.strip(), x.strip()), inplace=True)
    
    required_cols = ['Date', 'Description', 'Ref/Cheque No', 'Debit', 'Credit', 'Balance']
    for col in required_cols:
        if col not in df.columns:
            df[col] = ""
            
    df = df[required_cols].copy()
    
    for col in ['Debit', 'Credit', 'Balance']:
        df[col] = df[col].str.replace(',', '', regex=True).str.replace(' ', '', regex=True)
        df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        
    df['Date'] = pd.to_datetime(df['Date'], dayfirst=True, errors='coerce')
    df = df.dropna(subset=['Date'])
    return df

def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Statement Analysis')
    return output.getvalue()

# --- Main App UI ---
st.title("🏦 Bank Statement Analyzer")

# Display the Usage Meter at the top of the sidebar
st.sidebar.markdown("### 📈 Analysis Meter")
st.sidebar.info(f"**Total App Users:** {total_visitors}")
st.sidebar.markdown("---")

uploaded_file = st.file_uploader("Upload Bank Statement (PDF, CSV, Excel)", type=["pdf", "csv", "xlsx", "xls"])

if uploaded_file:
    try:
        file_extension = uploaded_file.name.split('.')[-1].lower()
        if file_extension == 'pdf':
            raw_df = parse_pdf(uploaded_file)
        elif file_extension == 'csv':
            raw_df = pd.read_csv(uploaded_file)
        else:
            raw_df = pd.read_excel(uploaded_file)
            
        if raw_df.empty:
            st.error("Could not extract data. Ensure the file contains readable tables.")
            st.stop()
            
        df = standardize_dataframe(raw_df)
        
        # --- Sidebar Filters & Sorting ---
        st.sidebar.header("🔍 Filter Transactions")
        
        min_date, max_date = df['Date'].min(), df['Date'].max()
        start_date = st.sidebar.date_input("Start Date", min_date)
        end_date = st.sidebar.date_input("End Date", max_date)
        
        desc_search = st.sidebar.text_input("Search Description (e.g., UPI, Amazon)")
        ref_search = st.sidebar.text_input("Search Ref/Cheque/NEFT/RTGS No.")
        
        st.sidebar.markdown("**Amount Filters**")
        min_debit = st.sidebar.number_input("Minimum Debit (₹)", value=0.0)
        min_credit = st.sidebar.number_input("Minimum Credit (₹)", value=0.0)
        
        st.sidebar.header("↕️ Sort Data")
        sort_column = st.sidebar.selectbox("Sort By", ['Date', 'Debit', 'Credit', 'Balance'])
        sort_order = st.sidebar.radio("Order", ['Ascending', 'Descending'])
        
        # --- Apply Filters ---
        mask = (df['Date'].dt.date >= start_date) & (df['Date'].dt.date <= end_date)
        
        if desc_search:
            mask = mask & df['Description'].astype(str).str.contains(desc_search, case=False, na=False)
        if ref_search:
            mask = mask & df['Ref/Cheque No'].astype(str).str.contains(ref_search, case=False, na=False)
        if min_debit > 0:
            mask = mask & (df['Debit'] >= min_debit)
        if min_credit > 0:
            mask = mask & (df['Credit'] >= min_credit)
            
        filtered_df = df.loc[mask]
        
        ascending_bool = True if sort_order == 'Ascending' else False
        filtered_df = filtered_df.sort_values(by=sort_column, ascending=ascending_bool)
        
        # --- Dashboard Metrics ---
        st.subheader("📊 Financial Overview (Filtered)")
        total_inflow = filtered_df['Credit'].sum()
        total_outflow = filtered_df['Debit'].sum()
        net_flow = total_inflow - total_outflow
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Inflow (Credits)", f"₹ {total_inflow:,.2f}")
        col2.metric("Total Outflow (Debits)", f"₹ {total_outflow:,.2f}")
        col3.metric("Net Flow", f"₹ {net_flow:,.2f}")
        
        # --- Charts ---
        if total_inflow > 0 or total_outflow > 0:
            chart_data = pd.DataFrame({
                "Category": ["Inflow (Credit)", "Outflow (Debit)"],
                "Amount": [total_inflow, total_outflow]
            })
            fig = px.bar(chart_data, x="Category", y="Amount", color="Category", 
                         color_discrete_sequence=["#2ecc71", "#e74c3c"],
                         title="Inflow vs Outflow")
            st.plotly_chart(fig, use_container_width=True)
        
        # --- Data Table & Export ---
        st.subheader("📑 Transaction Details")
        st.dataframe(filtered_df, use_container_width=True)
        
        st.markdown("### 📥 Download & Print")
        dl_col1, dl_col2, dl_col3 = st.columns([1, 1, 2])
        
        csv = filtered_df.to_csv(index=False).encode('utf-8')
        dl_col1.download_button(label="⬇️ Download CSV", data=csv, file_name="statement_analysis.csv", mime="text/csv")
        
        excel_data = convert_df_to_excel(filtered_df)
        dl_col2.download_button(label="⬇️ Download Excel", data=excel_data, file_name="statement_analysis.xlsx", mime="application/vnd.ms-excel")
        
        st.info("🖨️ **To Save as PDF or Print:** Press `Ctrl + P` (or `Cmd + P` on Mac) on your keyboard to print this entire dashboard view, and select 'Save as PDF' as your printer.")
        
    except Exception as e:
        st.error(f"An error occurred while processing the file: {str(e)}")

# --- Custom Footer ---
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #888888; font-size: 14px; padding: 20px;'>
        <strong>Created and Copyright © by Dr. Rahul Patil</strong><br>
        Asst. Prof. Dept. of Zoology, PDEA's Annasaheb Waghire College, Otur, Junnar, Pune.
    </div>
    """, 
    unsafe_allow_html=True
)