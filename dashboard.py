"""
Streamlit dashboard for 311 triage results.

Visualizations:
- Borough heatmap of request volume & urgency
- SLA breach trends over time
- Category drilldown with filters
- Real-time stats
"""
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from utils import get_env
from models import init_db

st.set_page_config(page_title="311 Triage Dashboard", layout="wide")

DB_PATH = get_env("DB_PATH", "data/311.db")

def get_connection():
    return init_db(DB_PATH)


def load_data() -> pd.DataFrame:
    """Load joined service_requests + triage_results."""
    conn = get_connection()
    query = """
        SELECT sr.*, tr.urgency_score, tr.department, tr.summary, tr.model_version, tr.created_at as triaged_at
        FROM service_requests sr
        LEFT JOIN triage_results tr ON sr.unique_key = tr.unique_key
    """
    df = pd.read_sql_query(query, conn)
    conn.close()
    # Parse dates
    for col in ["created_date", "closed_date", "due_date", "resolution_action_updated_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    if "triaged_at" in df.columns:
        df["triaged_at"] = pd.to_datetime(df["triaged_at"], errors="coerce")
    return df


def compute_sla_breach(df: pd.DataFrame) -> pd.DataFrame:
    """Mark rows where closed_date > due_date (SLA breach)."""
    df = df.copy()
    df["sla_breach"] = (df["closed_date"] > df["due_date"]) & df["closed_date"].notna() & df["due_date"].notna()
    return df


def borough_heatmap(df: pd.DataFrame):
    """Plotly choropleth of NYC boroughs (using borough centroids)."""
    # Simple borough centroids for bubble map
    borough_coords = {
        "MANHATTAN": (40.7831, -73.9712),
        "BROOKLYN": (40.6782, -73.9442),
        "QUEENS": (40.7282, -73.7949),
        "BRONX": (40.8448, -73.8648),
        "STATEN ISLAND": (40.5795, -74.1502),
    }
    agg = df.groupby("borough").agg(
        count=("unique_key", "count"),
        avg_urgency=("urgency_score", "mean"),
        sla_breach_rate=("sla_breach", "mean"),
    ).reset_index()
    agg["lat"] = agg["borough"].map(lambda b: borough_coords.get(b, (0,0))[0])
    agg["lon"] = agg["borough"].map(lambda b: borough_coords.get(b, (0,0))[1])
    
    fig = px.scatter_mapbox(
        agg, lat="lat", lon="lon", size="count", color="avg_urgency",
        hover_name="borough", hover_data={"count": True, "avg_urgency": ":.1f", "sla_breach_rate": ":.1%"},
        color_continuous_scale="Reds", size_max=40, zoom=9, mapbox_style="carto-positron",
        title="311 Request Volume & Urgency by Borough",
    )
    fig.update_layout(margin={"r":0,"t":40,"l":0,"b":0})
    st.plotly_chart(fig, use_container_width=True)


def sla_trend(df: pd.DataFrame):
    """Line chart of SLA breach rate over time (weekly)."""
    df = df[df["created_date"].notna()].copy()
    df["week"] = df["created_date"].dt.to_period("W").dt.start_time
    weekly = df.groupby("week").agg(
        total=("unique_key", "count"),
        breaches=("sla_breach", "sum"),
    ).reset_index()
    weekly["breach_rate"] = weekly["breaches"] / weekly["total"]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=weekly["week"], y=weekly["breach_rate"], mode="lines+markers", name="SLA Breach Rate"))
    fig.add_trace(go.Bar(x=weekly["week"], y=weekly["total"], name="Total Requests", yaxis="y2", opacity=0.3))
    fig.update_layout(
        title="Weekly SLA Breach Trend",
        xaxis_title="Week",
        yaxis=dict(title="Breach Rate", tickformat=".0%"),
        yaxis2=dict(title="Total Requests", overlaying="y", side="right", showgrid=False),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


def category_drilldown(df: pd.DataFrame):
    """Bar chart of top complaint types with urgency breakdown."""
    top_n = st.slider("Top N complaint types", 5, 30, 15)
    cat = df.groupby("complaint_type").agg(
        count=("unique_key", "count"),
        avg_urgency=("urgency_score", "mean"),
    ).nlargest(top_n, "count").reset_index()
    
    fig = px.bar(
        cat, x="count", y="complaint_type", orientation="h", color="avg_urgency",
        color_continuous_scale="OrRd", title=f"Top {top_n} Complaint Types by Volume & Urgency",
        labels={"count": "Request Count", "avg_urgency": "Avg Urgency"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin={"l": 200})
    st.plotly_chart(fig, use_container_width=True)


def department_workload(df: pd.DataFrame):
    """Stacked bar of department workload by urgency."""
    dept = df[df["department"].notna()].copy()
    dept["urgency_label"] = dept["urgency_score"].map({1: "Low", 2: "Medium-Low", 3: "Medium", 4: "High", 5: "Critical"})
    fig = px.histogram(
        dept, x="department", color="urgency_label",
        category_orders={"urgency_label": ["Low", "Medium-Low", "Medium", "High", "Critical"]},
        title="Department Workload by Urgency Level",
    )
    st.plotly_chart(fig, use_container_width=True)


def main():
    st.title("🗽 NYC 311 Triage Dashboard")
    
    # Sidebar filters
    st.sidebar.header("Filters")
    df = load_data()
    df = compute_sla_breach(df)
    
    if df.empty:
        st.warning("No data found. Run ETL & triage first.")
        return
    
    # Date range filter
    min_date = df["created_date"].min().date() if df["created_date"].notna().any() else datetime.now().date()
    max_date = df["created_date"].max().date() if df["created_date"].notna().any() else datetime.now().date()
    date_range = st.sidebar.date_input("Created date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
    if len(date_range) == 2:
        start, end = date_range
        df = df[(df["created_date"].dt.date >= start) & (df["created_date"].dt.date <= end)]
    
    # Borough filter
    boroughs = sorted(df["borough"].dropna().unique())
    selected_boroughs = st.sidebar.multiselect("Boroughs", boroughs, default=boroughs)
    df = df[df["borough"].isin(selected_boroughs)]
    
    # Urgency filter
    urgency_range = st.sidebar.slider("Urgency score", 1, 5, (1, 5))
    df = df[(df["urgency_score"] >= urgency_range[0]) & (df["urgency_score"] <= urgency_range[1])]
    
    # KPI row
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Requests", f"{len(df):,}")
    col2.metric("Avg Urgency", f"{df['urgency_score'].mean():.1f}" if df["urgency_score"].notna().any() else "N/A")
    col3.metric("SLA Breach Rate", f"{df['sla_breach'].mean():.1%}" if df["sla_breach"].notna().any() else "N/A")
    col4.metric("Triaged %", f"{df['urgency_score'].notna().mean():.1%}")
    
    # Tabs for visualizations
    tab1, tab2, tab3, tab4 = st.tabs(["🗺️ Borough Heatmap", "📈 SLA Trends", "📊 Category Drilldown", "🏢 Department Workload"])
    with tab1:
        borough_heatmap(df)
    with tab2:
        sla_trend(df)
    with tab3:
        category_drilldown(df)
    with tab4:
        department_workload(df)
    
    # Data table (expandable)
    with st.expander("Raw Data (filtered)"):
        display_cols = ["unique_key", "created_date", "complaint_type", "descriptor", "borough", "status", "urgency_score", "department", "summary"]
        st.dataframe(df[display_cols].head(500), use_container_width=True)

if __name__ == "__main__":
    main()
