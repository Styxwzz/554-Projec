import streamlit as st
import pandas as pd
import pydeck as pdk
import geopandas as gpd
from shapely.geometry import Point
import numpy as np
import altair as alt
import warnings
from utils.load_data import load_schools_csv, load_collision_school_csv
mapbox_token = st.secrets["MAPBOX_TOKEN"]

# 禁用某些警告
warnings.filterwarnings("ignore", category=RuntimeWarning)

# 页面标题
st.title("School Safety View")

# ============================================
# 加载数据
# ============================================
schools_df = load_schools_csv()
collision_school_df = load_collision_school_csv()

# ============================================
# 初始化会话状态
# ============================================
if "selected_school_idx" not in st.session_state:
    st.session_state.selected_school_idx = None

if "selected_schools_list" not in st.session_state:
    st.session_state.selected_schools_list = None

if "map_center_school" not in st.session_state:
    st.session_state.map_center_school = None

if "filter_applied" not in st.session_state:
    st.session_state.filter_applied = False

if "temp_year_range" not in st.session_state:
    years = sorted(collision_school_df["Year"].dropna().unique())
    st.session_state.temp_year_range = (2021, int(max(years)))

if "temp_category2" not in st.session_state:
    st.session_state.temp_category2 = "All"

if "temp_category3" not in st.session_state:
    st.session_state.temp_category3 = "All"

if "temp_school_search" not in st.session_state:
    st.session_state.temp_school_search = ""

if "temp_safety" not in st.session_state:
    st.session_state.temp_safety = "All"

if "active_year_range" not in st.session_state:
    years = sorted(collision_school_df["Year"].dropna().unique())
    st.session_state.active_year_range = (2021, int(max(years)))

if "active_category2" not in st.session_state:
    st.session_state.active_category2 = "All"

if "active_category3" not in st.session_state:
    st.session_state.active_category3 = "All"

if "active_school_search" not in st.session_state:
    st.session_state.active_school_search = ""

if "active_safety" not in st.session_state:
    st.session_state.active_safety = "All"

# ============================================
# Sidebar Filters
# ============================================
st.sidebar.header("Filters")

# 时间段筛选
years = sorted(collision_school_df["Year"].dropna().unique())
year_min, year_max = int(min(years)), int(max(years))

st.session_state.temp_year_range = st.sidebar.slider(
    "Year Range",
    min_value=year_min,
    max_value=year_max,
    value=st.session_state.temp_year_range,
    key="temp_year_slider"
)

# Category2 筛选
category2_options = ["All"] + sorted([c for c in schools_df["Category2"].unique().tolist() if pd.notna(c)])
st.session_state.temp_category2 = st.sidebar.selectbox(
    "School Type (Category2)",
    options=category2_options,
    index=category2_options.index(st.session_state.temp_category2) if st.session_state.temp_category2 in category2_options else 0,
    key="temp_category2_select"
)

if st.session_state.temp_category2 != "All":
    filtered_by_cat2 = schools_df[schools_df["Category2"] == st.session_state.temp_category2].copy()
else:
    filtered_by_cat2 = schools_df.copy()

# Category3 筛选
category3_options = ["All"] + sorted([c for c in filtered_by_cat2["Category3"].unique().tolist() if pd.notna(c)])
if st.session_state.temp_category3 not in category3_options:
    st.session_state.temp_category3 = "All"
    
st.session_state.temp_category3 = st.sidebar.selectbox(
    "School Category (Category3)",
    options=category3_options,
    index=category3_options.index(st.session_state.temp_category3) if st.session_state.temp_category3 in category3_options else 0,
    key="temp_category3_select"
)

if st.session_state.temp_category3 != "All":
    filtered_by_cat3 = filtered_by_cat2[filtered_by_cat2["Category3"] == st.session_state.temp_category3].copy()
else:
    filtered_by_cat3 = filtered_by_cat2.copy()

# 搜索框
st.session_state.temp_school_search = st.sidebar.text_input(
    "Search schools by name",
    placeholder="e.g., Academy, Elementary",
    value=st.session_state.temp_school_search,
    key="temp_search_input"
)

# Safety等级筛选
safety_levels = ["All", "Excellent (✓✓✓)", "Good (✓✓)", "Fair (✓)", "Poor (⚠)"]
st.session_state.temp_safety = st.sidebar.selectbox(
    "Safety Rating",
    options=safety_levels,
    index=safety_levels.index(st.session_state.temp_safety) if st.session_state.temp_safety in safety_levels else 0,
    key="temp_safety_select"
)

# 搜索按钮
st.sidebar.markdown("---")
if st.sidebar.button("🔍 Apply Filters", key="apply_filters", use_container_width=True):
    # 保存临时值到活跃状态
    st.session_state.active_year_range = st.session_state.temp_year_range
    st.session_state.active_category2 = st.session_state.temp_category2
    st.session_state.active_category3 = st.session_state.temp_category3
    st.session_state.active_school_search = st.session_state.temp_school_search
    st.session_state.active_safety = st.session_state.temp_safety
    st.rerun()

# 使用活跃的过滤值
selected_years = st.session_state.active_year_range
selected_category2 = st.session_state.active_category2
selected_category3 = st.session_state.active_category3
school_search = st.session_state.active_school_search
selected_safety = st.session_state.active_safety

# ============================================
# 应用筛选逻辑
# ============================================
# 先按年份筛选碰撞数据
collision_filtered = collision_school_df[
    (collision_school_df["Year"] >= selected_years[0]) & 
    (collision_school_df["Year"] <= selected_years[1])
].copy()

# 筛选学校
if school_search:
    filtered_schools = filtered_by_cat3[
        filtered_by_cat3["Name"].str.contains(school_search, case=False, na=False)
    ].copy()
else:
    filtered_schools = filtered_by_cat3.copy()

# 应用到所有筛选后的学校
schools_display = filtered_schools.copy()

# ============================================
# 计算每个学校周围的碰撞数量（基于预处理数据）
# ============================================

# 为每个学校计算周围碰撞数
schools_display = schools_display.reset_index(drop=True)
schools_display["collision_count"] = 0
schools_display["avg_annual_collisions"] = 0.0
schools_display["safety_rating"] = ""

collision_records_by_school = {}

# 计算年份范围
years_range = selected_years[1] - selected_years[0] + 1

# 使用预处理数据：按学校名称分组计算碰撞数
# 使用 groupby 获取碰撞数据的聚合统计
collision_count_by_school = collision_filtered.groupby("school_name").size()

for idx, row in schools_display.iterrows():
    school_name = row["Name"]
    
    # 获取该学校的所有碰撞记录
    school_collisions = collision_filtered[collision_filtered["school_name"] == school_name].copy()
    count = len(school_collisions)
    
    # 计算年均碰撞数
    avg_annual = count / years_range if years_range > 0 else 0
    
    # 安全等级评分（基于年均碰撞数）
    if avg_annual == 0:
        rating = "Excellent (✓✓✓)"
    elif avg_annual <= 3:
        rating = "Good (✓✓)"
    elif avg_annual <= 10:
        rating = "Fair (✓)"
    else:
        rating = "Poor (⚠)"
    
    # 更新学校数据
    schools_display.at[idx, "collision_count"] = count
    schools_display.at[idx, "avg_annual_collisions"] = avg_annual
    schools_display.at[idx, "safety_rating"] = rating
    # 使用学校名称作为键存储碰撞数据（而不是索引）
    collision_records_by_school[school_name] = school_collisions

# 定义搜索半径（用于地图显示）
SEARCH_RADIUS_MILE = 0.2
SEARCH_RADIUS_METERS = SEARCH_RADIUS_MILE * 1609.34  # 0.2 mile ≈ 321.87 meters

# ============================================
# 应用 Safety Rating 过滤
# ============================================
if selected_safety != "All":
    schools_display = schools_display[schools_display["safety_rating"] == selected_safety].copy()

# ============================================
# 颜色映射函数（基于Safety Rating）
# ============================================
def safety_rating_to_color(rating):
    """根据安全等级返回 RGB 颜色"""
    color_map = {
        "Excellent (✓✓✓)": (34, 177, 76),     # 绿色
        "Good (✓✓)": (255, 192, 0),           # 黄色
        "Fair (✓)": (255, 127, 0),            # 橙色
        "Poor (⚠)": (255, 0, 0),              # 红色
    }
    return color_map.get(rating, (150, 150, 150))  # 默认灰色

# 为地图添加颜色信息（基于safety_rating）
schools_display["fill_r"] = schools_display["safety_rating"].apply(
    lambda x: safety_rating_to_color(x)[0]
)
schools_display["fill_g"] = schools_display["safety_rating"].apply(
    lambda x: safety_rating_to_color(x)[1]
)
schools_display["fill_b"] = schools_display["safety_rating"].apply(
    lambda x: safety_rating_to_color(x)[2]
)

# 添加搜索半径
schools_display["radius"] = SEARCH_RADIUS_METERS

# ============================================
# 处理地图点击交互
# ============================================
# 初始化会话状态以记录点击的学校
if "clicked_school_name" not in st.session_state:
    st.session_state.clicked_school_name = None

# 创建两个数据集：选中的和未选中的
selected_school_data = pd.DataFrame()
other_schools_data = schools_display.copy()

if st.session_state.clicked_school_name and st.session_state.clicked_school_name in schools_display["Name"].values:
    selected_school_data = schools_display[schools_display["Name"] == st.session_state.clicked_school_name].copy()
    other_schools_data = schools_display[schools_display["Name"] != st.session_state.clicked_school_name].copy()

# ============================================
# 创建 pydeck 图层
# ============================================

# 根据是否选中学校，决定显示哪些图层
if len(selected_school_data) > 0:
    # 已选中学校时：只显示其他学校的点（不显示范围），显示选中学校的范围和碰撞点
    
    # 其他学校点（只显示点，不显示范围）
    other_schools_layer = pdk.Layer(
        "ScatterplotLayer",
        data=other_schools_data,
        get_position="[lon, lat]",
        get_radius=80,
        get_fill_color="[fill_r, fill_g, fill_b, 120]",
        get_line_color=[100, 100, 100],
        line_width_min_pixels=1,
        pickable=True,
    )
    
    # 选中学校的圆形范围（透明度高）
    selected_circle_layer = pdk.Layer(
        "ScatterplotLayer",
        data=selected_school_data,
        get_position="[lon, lat]",
        get_radius="radius",
        get_fill_color="[fill_r, fill_g, fill_b, 80]",  # 高透明度
        pickable=False,
    )
    
    # 选中的学校点（彩色，更大，用于突出显示）
    selected_layer = pdk.Layer(
        "ScatterplotLayer",
        data=selected_school_data,
        get_position="[lon, lat]",
        get_radius=120,
        get_fill_color="[fill_r, fill_g, fill_b, 220]",
        get_line_color=[0, 0, 0],
        line_width_min_pixels=3,
        pickable=True,
    )
    
    # 选中学校的碰撞事故点
    collision_points_layer = None
    selected_school_name = st.session_state.clicked_school_name
    if selected_school_name in collision_records_by_school:
        collision_points = collision_records_by_school[selected_school_name]
        if collision_points is not None and len(collision_points) > 0:
            # 检查是否有lon/lat列
            if 'lon' in collision_points.columns and 'lat' in collision_points.columns:
                # 用ScatterplotLayer显示碰撞点，黑色小点
                collision_points_layer = pdk.Layer(
                    "ScatterplotLayer",
                    data=collision_points,
                    get_position="[lon, lat]",
                    get_radius=30,  # 更小
                    get_fill_color="[0, 0, 0, 120]",  # 黑色，透明度约50%
                    get_line_color=[50, 50, 50],
                    line_width_min_pixels=1,
                    pickable=True,
                )
    
    # 按层级顺序排列：其他学校点 → 选中学校范围 → 选中学校点 → 碰撞点（最上层）
    layers = [
        other_schools_layer,
        selected_circle_layer,
        selected_layer,
    ]
    if collision_points_layer is not None:
        layers.append(collision_points_layer)
else:
    # 未选中学校时：显示所有学校的范围和点
    circles_layer = pdk.Layer(
        "ScatterplotLayer",
        data=schools_display,
        get_position="[lon, lat]",
        get_radius="radius",
        get_fill_color="[fill_r, fill_g, fill_b, 80]",  # 高透明度
        pickable=False,
    )
    
    all_schools_layer = pdk.Layer(
        "ScatterplotLayer",
        data=schools_display,
        get_position="[lon, lat]",
        get_radius=100,
        get_fill_color="[fill_r, fill_g, fill_b, 150]",
        get_line_color=[100, 100, 100],
        line_width_min_pixels=1,
        pickable=True,
    )
    
    layers = [circles_layer, all_schools_layer]

# 初始化视图：洛杉矶中心
initial_view = pdk.ViewState(
    longitude=-118.25,
    latitude=34.05,
    zoom=11,
    pitch=0,
)
deck = pdk.Deck(
    map_style=pdk.map_styles.LIGHT,
    initial_view_state=initial_view,
    layers=layers,
    tooltip={
        "text": "{Name}\ncollision count: {collision_count}",
    },
    api_keys={'mapbox': mapbox_token}
)

# ============================================
# 处理选校后的地图定位和缩放
# ============================================
if st.session_state.clicked_school_name and st.session_state.clicked_school_name in schools_display["Name"].values:
    school_for_center = schools_display[schools_display["Name"] == st.session_state.clicked_school_name].iloc[0]
    center_lat = school_for_center["lat"]
    center_lon = school_for_center["lon"]
    zoom_level = 15  # 0.2 mile 范围充满整张图
else:
    center_lat = 34.05
    center_lon = -118.25
    zoom_level = 11

view_state_updated = pdk.ViewState(
    longitude=center_lon,
    latitude=center_lat,
    zoom=zoom_level,
    pitch=0,
)

# 创建更新后的地图（根据选校动态更新）
deck_display = pdk.Deck(
    map_style=pdk.map_styles.LIGHT,
    initial_view_state=view_state_updated,
    layers=layers,
    tooltip={
        "text": "{Name}\ncollision count: {collision_count}",
    },
    api_keys={'mapbox': mapbox_token}
)

# ============================================
# 主要布局
# ============================================
col1, col2 = st.columns([2, 1])

with col1:
    # 显示地图（去掉小标题）
    st.pydeck_chart(deck_display, use_container_width=True)
    
    # 图例
    st.markdown("---")
    st.markdown("**Safety Rating Legend:**")
    col_leg1, col_leg2, col_leg3, col_leg4 = st.columns(4)
    with col_leg1:
        st.markdown('<span style="color: #22b14c;">■</span> **Excellent** (0/yr)', unsafe_allow_html=True)
    with col_leg2:
        st.markdown('<span style="color: #ffc000;">■</span> **Good** (≤3/yr)', unsafe_allow_html=True)
    with col_leg3:
        st.markdown('<span style="color: #ff7f00;">■</span> **Fair** (≤10/yr)', unsafe_allow_html=True)
    with col_leg4:
        st.markdown('<span style="color: #ff0000;">■</span> **Poor** (>10/yr)', unsafe_allow_html=True)
    
    # 学校列表表格
    st.markdown("---")
    st.markdown("**Schools List on the Map:**")
    
    school_names_sorted = sorted(schools_display["Name"].unique())
    schools_table_data = schools_display[schools_display["Name"].isin(school_names_sorted)][
        ["Name", "Category2", "collision_count", "avg_annual_collisions", "safety_rating"]
    ].copy()
    schools_table_data.columns = ["School", "Type", "Collisions", "Avg/Year", "Safety"]
    schools_table_data = schools_table_data.sort_values("School").reset_index(drop=True)
    
    # 显示可排序、可滚动的表格
    st.dataframe(
        schools_table_data,
        use_container_width=True,
        hide_index=True,
        height=min(400, len(schools_table_data) * 35 + 50)
    )

with col2:
    st.subheader("School Details")
    
    school_names_sorted = sorted(schools_display["Name"].unique())
    
    # 选择学校的下拉框
    school_options = ["-- Select a school --"] + school_names_sorted
    selected_school_name = st.selectbox(
        "Select a school",
        options=school_options,
        index=school_options.index(st.session_state.clicked_school_name) 
            if st.session_state.clicked_school_name and st.session_state.clicked_school_name in school_options 
            else 0,
        key="school_selector"
    )
    
    # 更新会话状态并触发地图重新渲染
    if selected_school_name != "-- Select a school --" and selected_school_name != st.session_state.clicked_school_name:
        st.session_state.clicked_school_name = selected_school_name
        st.rerun()
    
    # 只有当选中学校时才显示详情
    if st.session_state.clicked_school_name and st.session_state.clicked_school_name != "-- Select a school --":
        selected_school_name = st.session_state.clicked_school_name
        school_data = schools_display[schools_display["Name"] == selected_school_name].iloc[0]
        
        # 学校标题
        st.markdown(f"### {school_data['Name']}")
        st.markdown(f"*{school_data['Category2']}*")
        
        # 关键指标
        st.markdown("---")
        st.markdown("**Metrics:**")
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.metric("Collisions", int(school_data["collision_count"]))
            st.metric("Avg/Year", f"{school_data['avg_annual_collisions']:.2f}")
        with col_m2:
            st.metric("Safety", school_data["safety_rating"])
            if pd.notna(school_data["Enrollment"]):
                st.metric("Enrollment", int(school_data["Enrollment"]))
        
        # 位置信息
        st.markdown("---")
        st.markdown("**Location:**")
        st.write(f"{school_data['Address Line 1']}")
        st.write(f"{school_data['City']}, {school_data['State']}")
        
        # 碰撞详情
        st.markdown("---")
        st.markdown("#### Collision Analysis")
        
        if selected_school_name in collision_records_by_school:
            nearby_collisions = collision_records_by_school[selected_school_name]
            
            if len(nearby_collisions) > 0:
                st.write(f"**Total:** {len(nearby_collisions)} records")
                
                # 按年份
                st.markdown("**By Year:**")
                nearby_collisions_copy = nearby_collisions.copy()
                nearby_collisions_copy["Year_val"] = nearby_collisions_copy["Date Occurred"].dt.year
                year_counts = nearby_collisions_copy["Year_val"].value_counts().sort_index()
                
                year_df = pd.DataFrame({
                    'Year': year_counts.index,
                    'Count': year_counts.values
                }).sort_values('Year')
                
                year_chart = (
                    alt.Chart(year_df)
                    .mark_bar()
                    .encode(
                        x=alt.X('Year:O', axis=alt.Axis(labelAngle=0)),
                        y='Count:Q',
                        tooltip=['Year', 'Count']
                    )
                    .properties(height=120)
                )
                st.altair_chart(year_chart, use_container_width=True)
            else:
                st.info("No collisions within 0.2 miles")
            
            # # 碰撞事故点的具体位置
            # if len(nearby_collisions) > 0:
            #     st.markdown("---")
            #     st.markdown("**Incident Locations:**")
                
            #     # 创建位置列表数据框
            #     locations_df = nearby_collisions[[
            #         "Date Occurred", "lat", "lon", "Area Name", "Address"
            #     ]].copy()
            #     locations_df.columns = ["Date", "Lat", "Lon", "Area", "Address"]
            #     locations_df["Date"] = locations_df["Date"].dt.strftime("%Y-%m-%d")
                
            #     # 显示为可滚动的表格
            #     st.dataframe(
            #         locations_df,
            #         use_container_width=True,
            #         hide_index=True,
            #         height=min(300, len(locations_df) * 35 + 50)
            #     )
        
        st.markdown("---")
        st.caption(f"Period: {selected_years[0]}-{selected_years[1]} | Radius: 0.2 mi")
    else:
        st.info("Please select a school from the dropdown to view details")
