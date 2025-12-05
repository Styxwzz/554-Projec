import pandas as pd
import geopandas as gpd
import streamlit as st

# -----------------------------
# 你的真实上传路径
# -----------------------------
CSV_PATH = "data/Traffic_Collision_Data_2021_and_after.csv"
GEOJSON_PATH = "data/Neighborhood_Council_Boundaries_(2018).geojson"
SCHOOLS_PATH = "data/Schools_Colleges_and_Universities_-1415912072170881369.csv"


# ==============================
# 加载 collision CSV
# ==============================
@st.cache_data
def load_collision_csv():
    df = pd.read_csv(CSV_PATH)

    # --- 解析 Location → lat / lon ---
    if "Location" in df.columns:
        loc = df["Location"].astype(str).str.strip("()").str.split(",", expand=True)
        df["lat"] = pd.to_numeric(loc[0].str.strip(), errors="coerce")
        df["lon"] = pd.to_numeric(loc[1].str.strip(), errors="coerce")
        df = df.dropna(subset=["lat", "lon"])

    # --- 解析 Date Occurred ---
    if "Date Occurred" in df.columns:
        df["Date Occurred"] = pd.to_datetime(df["Date Occurred"], errors="coerce")


    return df


# ==============================
# 加载社区 GeoJSON
# ==============================
@st.cache_data
def load_nc_geojson():
    gdf = gpd.read_file(GEOJSON_PATH)
    return gdf


# ==============================
# 加载学校 CSV
# ==============================
@st.cache_data
def load_schools_csv():
    df = pd.read_csv(SCHOOLS_PATH)
    # 确保经纬度列存在且有效
    df = df.dropna(subset=["Latitude", "Longitude"])
    df = df.rename(columns={"Latitude": "lat", "Longitude": "lon"})
    return df


# ==============================
# 加载预处理后的 collision-school 关联数据
# ==============================
@st.cache_data
def load_collision_school_csv():
    """加载预处理后的碰撞-学校关联数据（仅包含学校周围0.2英里内的碰撞）"""
    collision_school_df = pd.read_csv("data/collisions_by_school.csv")
    collision_school_df["Date Occurred"] = pd.to_datetime(collision_school_df["Date Occurred"], errors="coerce")
    return collision_school_df
