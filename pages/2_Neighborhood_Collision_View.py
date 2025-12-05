import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
import geopandas as gpd
from shapely.geometry import Point

from utils.load_data import load_collision_csv, load_nc_geojson

pdk.settings.mapbox_api_key = st.secrets["MAPBOX_TOKEN"]

st.title("Neighborhood Collision View")

# =============================
# Load data
# =============================
df = load_collision_csv()          
gdf = load_nc_geojson()            

# 确保 gdf 有坐标系，转换到 WGS84（经纬度）
if getattr(gdf, "crs", None) is None:
    gdf = gdf.set_crs("EPSG:4326")
elif gdf.crs.to_epsg() != 4326:
    gdf = gdf.to_crs("EPSG:4326")

# =============================
# Side bar
# =============================
st.sidebar.header("Filters")

years = sorted(df["Year"].dropna().unique())
year_min, year_max = int(min(years)), int(max(years))

selected_years = st.sidebar.slider(
    "Year Range",
    min_value=year_min,
    max_value=year_max,
    value=(2021, year_max),
)

df_filtered = df[(df["Year"] >= selected_years[0]) & (df["Year"] <= selected_years[1])]

# =============================
# 3. Calculate collisions by neighborhood
# =============================

points_gdf = gpd.GeoDataFrame(
    df_filtered,
    geometry=gpd.points_from_xy(df_filtered["lon"], df_filtered["lat"]),
    crs="EPSG:4326",
)

gdf = gdf.reset_index().rename(columns={"index": "poly_id"})


joined = gpd.sjoin(
    points_gdf,
    gdf[["poly_id", "geometry"]],
    how="left",
    predicate="within",
)

counts = (
    joined.groupby("poly_id")
    .size()
    .reset_index(name="collision_count")
)

gdf = gdf.merge(counts, on="poly_id", how="left")
gdf["collision_count"] = gdf["collision_count"].fillna(0)

# =============================
# 4. Find neighborhood name list
# =============================
name_col = None
for col in gdf.columns:
    if gdf[col].dtype == "object":
        lower = str(col).lower()
        if any(k in lower for k in ["name", "neigh", "hood"]):
            name_col = col
            break

if name_col is None:
    obj_cols = [c for c in gdf.columns if gdf[c].dtype == "object"]
    name_col = obj_cols[0] if obj_cols else "poly_id"


# =============================
# Choropleth map color fill
# =============================
min_cnt = float(gdf["collision_count"].min())
max_cnt = float(gdf["collision_count"].max())
rng = max(max_cnt - min_cnt, 1)

# Yellow to orange to red
low = (255, 255, 178)
mid = (254, 204, 92)
high = (227, 26, 28)

def lerp(a, b, t):
    return int(a + (b - a) * t)

def collision_to_color(n):
    t = (n - min_cnt) / rng
    if t < 0.5:
        # yellow → orange
        tt = t / 0.5
        return (
            lerp(low[0], mid[0], tt),
            lerp(low[1], mid[1], tt),
            lerp(low[2], mid[2], tt),
        )
    else:
        # orange → red
        tt = (t - 0.5) / 0.5
        return (
            lerp(mid[0], high[0], tt),
            lerp(mid[1], high[1], tt),
            lerp(mid[2], high[2], tt),
        )

gdf["fill_r"], gdf["fill_g"], gdf["fill_b"] = zip(
    *gdf["collision_count"].apply(collision_to_color)
)


neigh_counts = gdf[[name_col, "collision_count"]].copy()
neigh_counts = neigh_counts.sort_values("collision_count", ascending=False)

# =============================
# Neighborhood dropdown
# =============================
all_neighs = neigh_counts[name_col].astype(str).tolist()
default_neigh = all_neighs[0] if all_neighs else None

selected_neigh = st.sidebar.selectbox(
    "Select a neighborhood",
    options=all_neighs,
    index=0 if default_neigh is not None else None,
)

gdf_selected = gdf[gdf[name_col].astype(str) == selected_neigh] if selected_neigh else gdf.iloc[[]]

if not gdf_selected.empty:
    poly_ids = gdf_selected["poly_id"].tolist()
    df_neigh = joined[joined["poly_id"].isin(poly_ids)].copy()
else:
    df_neigh = df_filtered.iloc[0:0].copy()  

if not gdf_selected.empty:
    center_geom = gdf_selected.geometry.unary_union.centroid
    pin_df = pd.DataFrame(
        [{
            "lat": center_geom.y,
            "lon": center_geom.x,
            "icon_data": {
                "url": "https://cdn-icons-png.flaticon.com/512/684/684908.png",
                "width": 128,
                "height": 128,
                "anchorY": 128,
            },
        }]
    )
else:
    pin_df = pd.DataFrame(columns=["lat", "lon", "icon_data"])


# =============================
# Choropleth map
# =============================
choropleth_layer = pdk.Layer(
    "GeoJsonLayer",
    data=gdf,
    stroked=True,
    filled=True,
    pickable=True,
    opacity=0.6,
    get_fill_color="[fill_r, fill_g, fill_b, 200]",
    get_line_color=[120, 120, 120, 255],
    get_line_width=10,
    lineWidthScale=4,
)

# Add pin
pin_layer = None
if not pin_df.empty:
    pin_layer = pdk.Layer(
        "IconLayer",
        data=pin_df,
        get_position='[lon, lat]',
        get_icon="icon_data",
        get_size=20,          
        size_scale=1,
        pickable=False,
    )


# Adjust location to LA
initial_view = pdk.ViewState(
    longitude=-118.25,
    latitude=34.05,
    zoom=10,
    pitch=0,
)

layers = [choropleth_layer]
if pin_layer is not None:
    layers.append(pin_layer)

deck = pdk.Deck(
    map_style="mapbox://styles/mapbox/light-v9",
    initial_view_state=initial_view,
    layers=layers,
    tooltip={"text": f"{name_col}: {{{name_col}}}\nCollisions: {{collision_count}}"},
)

# =============================
# 8. Overall layout
# =============================
col_map, col_bar = st.columns([2, 1])

with col_map:
    st.subheader("Neighborhood-level Collision Choropleth")
    st.pydeck_chart(deck)

with col_bar:
    st.subheader("Collisions per Neighborhood")

    TOP_N = 20  

    ranked = neigh_counts.sort_values("collision_count", ascending=False).reset_index(drop=True)

    topN = ranked.head(TOP_N)

    selected_row = ranked[ranked[name_col].astype(str) == selected_neigh]

    if not selected_row.empty and selected_neigh not in topN[name_col].astype(str).values:
        bar_data = pd.concat([topN, selected_row]).drop_duplicates(subset=[name_col])
    else:
        bar_data = topN

    # Show all checkbox
    show_more = st.checkbox("Show all neighborhoods", value=False)

    if show_more:
        bar_data = ranked  

    bar_data = bar_data.sort_values("collision_count", ascending=False)

    bar_chart = (
        alt.Chart(bar_data)
        .mark_bar()
        .encode(
            x=alt.X("collision_count:Q", title="Number of collisions"),
            y=alt.Y(f"{name_col}:N", sort="-x", title="Neighborhood"),
            color=alt.condition(
                alt.datum[name_col] == selected_neigh,
                alt.value("#1f77b4"),  
                alt.value("#bbbbbb"),  
            ),
            tooltip=[name_col, "collision_count"],
        )
        .properties(
            title=f"Collisions per Neighborhood (Top {TOP_N} + selected)"
            if not show_more else "Collisions per Neighborhood (All Neighborhoods)",
            width=380,   
            height=420,  
        )
    )

    st.altair_chart(bar_chart, use_container_width=False)


# =============================
# Detail information for selected neighborhood
# =============================
st.markdown("---")
st.subheader(f"Details for neighborhood: {selected_neigh}")

if df_neigh.empty:
    st.info("No collision records for this neighborhood in the selected time range.")
else:
    col_age, col_sex, col_premise = st.columns(3)

    with col_age:
        st.caption("Victim Age Distribution")
        age_series = df_neigh["Victim Age"].dropna()
        age_series = age_series[(age_series >= 0) & (age_series <= 100)]

        if age_series.empty:
            st.write("No age data.")
        else:
            age_df = pd.DataFrame({"Age": age_series})
            age_chart = (
                alt.Chart(age_df)
                .mark_bar()
                .encode(
                    x=alt.X("Age:Q", bin=alt.Bin(step=10), title="Age (10-year bins)"),
                    y=alt.Y("count():Q", title="Count"),
                    tooltip=["count()"],
                )
            )
            st.altair_chart(age_chart, use_container_width=True)

    with col_sex:
        st.caption("Victim Sex Distribution (Pie Chart)")

        sex_series = (
            df_neigh["Victim Sex"]
            .fillna("Unknown")
            .astype(str)
        )

        if sex_series.empty:
            st.write("No sex data available for this neighborhood.")
        else:
            sex_counts = sex_series.value_counts().reset_index()
            sex_counts.columns = ["Sex", "Count"]

            sex_color_scale = alt.Scale(
                domain=["M", "F", "Unknown", "X"],
                range=["#1f77b4", "#ff7f0e", "#d3d3d3", "#2ca02c"], 
            )

            sex_pie = (
                alt.Chart(sex_counts)
                .mark_arc(innerRadius=60)
                .encode(
                    theta=alt.Theta("Count:Q"),
                    color=alt.Color(
                        "Sex:N",
                        legend=None,
                        scale=sex_color_scale,   
                    ),
                    tooltip=["Sex", "Count"],
                )
                .properties(width=220, height=220)
            )

            sex_legend = (
                alt.Chart(sex_counts)
                .mark_rect()
                .encode(
                    y=alt.Y("Sex:N", axis=alt.Axis(title="Sex")),
                    color=alt.Color(
                        "Sex:N",
                        legend=None,
                        scale=sex_color_scale,   
                    ),
                )
            )

            sex_chart = sex_pie | sex_legend
            st.altair_chart(sex_chart, use_container_width=False)


    with col_premise:
        st.caption("Premise Description Distribution")

        premise_series = (
            df_neigh["Premise Description"]
            .fillna("Unknown")
            .astype(str)
        )

        if premise_series.empty:
            st.write("No premise data available for this neighborhood.")
        else:
            premise_counts = premise_series.value_counts().head(8).reset_index()
            premise_counts.columns = ["Premise", "Count"]

            premise_chart = (
                alt.Chart(premise_counts)
                .mark_bar()
                .encode(
                    x=alt.X("Count:Q", title="Count"),
                    y=alt.Y("Premise:N", sort="-x", title="Premise"),
                    tooltip=["Premise", "Count"],
                )
            )
            st.altair_chart(premise_chart, use_container_width=True)

