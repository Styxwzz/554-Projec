import streamlit as st
import pandas as pd
import pydeck as pdk
import altair as alt
import geopandas as gpd
from shapely.geometry import Point, LineString
import requests

# import data functions from utils
from utils.load_data import load_collision_csv, load_nc_geojson
mapbox_token = st.secrets["MAPBOX_TOKEN"]

# Page title
st.title("Spatial Collision Map")


# ============================================
# Utility Functions
# ============================================
def collision_to_color(n):
    """
    Convert collision count to a color in RGB format.
    Higher values produce darker colors.
    """
    n = int(n)
    if n == 0:
        return (230, 230, 230)
    elif n < 100:
        return (198, 239, 206)
    elif n < 1000:
        return (123, 201, 111)
    else:
        return (35, 132, 67)


def get_osrm_route(start_lon, start_lat, end_lon, end_lat):
    """
    Use OSRM public service to obtain a driving route based on 
    the longitude/latitude of start and end points.
    Returns a list of coordinates in the form [[lon, lat], ...].
    """
    url = (
        f"http://router.project-osrm.org/route/v1/driving/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
    )
    params = {
        "overview": "full",      # return full route geometry
        "geometries": "geojson", # return result as GeoJSON coordinates
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()

    if "routes" not in data or len(data["routes"]) == 0:
        raise RuntimeError("No valid route returned from OSRM")

    coords = data["routes"][0]["geometry"]["coordinates"]  # [[lon, lat], ...]
    return coords


# ============================================
# Load Data
# ============================================
df = load_collision_csv()
gdf = load_nc_geojson()

# Ensure date column is in datetime format
if not pd.api.types.is_datetime64_any_dtype(df["Date Occurred"]):
    df["Date Occurred"] = pd.to_datetime(df["Date Occurred"], errors="coerce")

# Extract year if it does not exist
if "Year" not in df.columns:
    df["Year"] = df["Date Occurred"].dt.year

# Ensure CRS is WGS84 (EPSG:4326)
try:
    if getattr(gdf, "crs", None) is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)
except Exception:
    pass

# ===== Count number of collisions per neighborhood polygon =====
points_gdf = gpd.GeoDataFrame(
    df,
    geometry=gpd.points_from_xy(df["lon"], df["lat"]),
    crs="EPSG:4326",
)

if gdf.crs is None:
    gdf = gdf.set_crs("EPSG:4326")
elif gdf.crs.to_epsg() != 4326:
    gdf = gdf.to_crs("EPSG:4326")

# assign a polygon ID for joining
gdf = gdf.reset_index().rename(columns={"index": "poly_id"})

# spatial join collision points with neighborhood polygons
joined = gpd.sjoin(
    points_gdf,
    gdf[["poly_id", "geometry"]],
    how="left",
    predicate="within",
)

# compute collision counts per polygon
counts = (
    joined.groupby("poly_id")
    .size()
    .reset_index(name="collision_count")
)

gdf = gdf.merge(counts, on="poly_id", how="left")
gdf["collision_count"] = gdf["collision_count"].fillna(0)

# assign color values based on collision severity
gdf["fill_r"], gdf["fill_g"], gdf["fill_b"] = zip(
    *gdf["collision_count"].apply(collision_to_color)
)

# ============================================
# Sidebar Filters
# ============================================
st.sidebar.header("Filters")

years = sorted(df["Year"].dropna().unique().tolist())
year_options = ["All"] + [int(y) for y in years]

selected_year = st.sidebar.selectbox(
    "Year (for map & statistics)",
    options=year_options,
    index=len(year_options) - 1
)

# Apply filter based on selected year
if selected_year == "All":
    df_filtered = df.copy()
    df_scope_for_stats = df.copy()
    year_title_suffix = "All Years"
else:
    df_filtered = df[df["Year"] == selected_year]
    df_scope_for_stats = df[df["Year"] == selected_year]
    year_title_suffix = f"Year {selected_year}"

if df_filtered.empty:
    st.warning("No data for this year.")
    st.stop()

# sampling for map rendering performance
max_points = 8000
df_map = df_filtered.sample(max_points, random_state=42) if len(df_filtered) > max_points else df_filtered

# calculate aggregated point density for dot color scaling
df_color = df_filtered.copy()
df_color["lat_round"] = df_color["lat"].round(4)
df_color["lon_round"] = df_color["lon"].round(4)

loc_counts_for_color = (
    df_color.groupby(["lat_round", "lon_round"])
    .size()
    .reset_index(name="loc_count")
)

df_map = df_map.copy()
df_map["lat_round"] = df_map["lat"].round(4)
df_map["lon_round"] = df_map["lon"].round(4)

df_map = df_map.merge(
    loc_counts_for_color,
    on=["lat_round", "lon_round"],
    how="left",
)

df_map["loc_count"] = df_map["loc_count"].fillna(1)

# normalize density values to color scale
count_min = df_map["loc_count"].min()
count_max = df_map["loc_count"].max()
denom = (count_max - count_min) if (count_max - count_min) != 0 else 1.0

df_map["loc_norm"] = (df_map["loc_count"] - count_min) / denom

df_map["col_r"] = 255
df_map["col_g"] = 255 - (df_map["loc_norm"] * 255)
df_map["col_g"] = df_map["col_g"].clip(0, 255)
df_map["col_b"] = 0
df_map["col_a"] = 180

# ============================================
# Map Mode Selection, including Commute Route
# ============================================
map_mode = st.sidebar.radio(
    "Map Mode",
    ["Dot Map", "Hexagon Map", "Commute Route"],
    index=0
)

# ============================================
# Mode 1 / 2: Dot Map & Hexagon Map
# ============================================
if map_mode in ["Dot Map", "Hexagon Map"]:
    # ----- location selector on sidebar -----
    st.sidebar.subheader("Select a collision location")

    loc_df = df_filtered.copy()
    loc_df["lat_round"] = loc_df["lat"].round(4)
    loc_df["lon_round"] = loc_df["lon"].round(4)

    loc_group = (
        loc_df.groupby(["lat_round", "lon_round"])
        .agg(
            collisions=("DR Number", "count"),
            sample_address=("Address", "first"),
            sample_area=("Area Name", "first"),
        )
        .reset_index()
    )

    loc_group["label"] = (
        loc_group["sample_address"].fillna("No address")
        + " | "
        + loc_group["sample_area"].fillna("")
        + " | "
        + loc_group["collisions"].astype(str)
        + " collisions"
    )

    location_options = ["All locations"] + loc_group["label"].tolist()
    selected_label = st.sidebar.selectbox("Location", location_options)

    # ----- handling selected location -----
    if selected_label == "All locations":
        same_loc_all = df_filtered.sort_values(["Date Occurred", "Time Occurred"])
        sel_lat, sel_lon = 34.05, -118.25  # LA City Center
        highlight_layer_enabled = False
    else:
        selected_loc = loc_group[loc_group["label"] == selected_label].iloc[0]

        same_loc_all = loc_df[
            (loc_df["lat_round"] == selected_loc["lat_round"]) &
            (loc_df["lon_round"] == selected_loc["lon_round"])
        ].sort_values(["Date Occurred", "Time Occurred"])

        represent_row = same_loc_all.iloc[0]
        sel_lat = represent_row["lat"]
        sel_lon = represent_row["lon"]
        highlight_layer_enabled = True

    # ----- PyDeck Layers -----
    nc_layer = pdk.Layer(
        "GeoJsonLayer",
        data=gdf,
        stroked=True,
        filled=False,
        pickable=True,
        opacity=0.6,
        get_fill_color="[fill_r, fill_g, fill_b, 120]",
        get_line_color=[0, 120, 0, 255],
        get_line_width=4,
    )

    collision_layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_map,
        get_position='[lon, lat]',
        get_radius=80,
        get_fill_color='[col_r, col_g, col_b, col_a]',
    )

    highlight_layer = pdk.Layer(
        "ScatterplotLayer",
        data=pd.DataFrame({"lat": [sel_lat], "lon": [sel_lon]}),
        get_position='[lon, lat]',
        get_radius=60,
        get_fill_color=[0, 0, 255, 255],
    )

    hex_layer = pdk.Layer(
        "HexagonLayer",
        data=df_filtered,
        get_position='[lon, lat]',
        auto_highlight=True,
        elevation_scale=25,
        radius=200,
        extruded=True,
        elevation_range=[0, 3000],
    )

    initial_view = pdk.ViewState(
        longitude=float(sel_lon),
        latitude=float(sel_lat),
        zoom=11,
        min_zoom=9,
        max_zoom=16,
        pitch=40,
    )

    if map_mode == "Dot Map":
        layers = [nc_layer, collision_layer]
        if highlight_layer_enabled:
            layers.append(highlight_layer)
        map_title = f"Collision Map ({year_title_suffix}) - Dot Map with Neighborhoods"
    else:
        layers = [nc_layer, hex_layer]
        map_title = f"Collision Map ({year_title_suffix}) - Cumulative Hexagon Density Map"

    deck = pdk.Deck(
        map_style=pdk.map_styles.DARK,
        initial_view_state=initial_view,
        layers=layers,
        tooltip={"text": "{elevationValue}"},
        api_keys={'mapbox': mapbox_token}  
    )

    # ----- Map block -----
    st.subheader(map_title)
    st.pydeck_chart(deck, use_container_width=True)

    # ----- Detail & bar chart section -----
    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Collision Details")

        if selected_label == "All locations":
            st.caption(f"Showing all {len(same_loc_all)} collisions in this year range.")
            st.info("Select a specific location to see detailed record info.")
        else:
            st.caption(f"Number of collisions at this location: {len(same_loc_all)}")

            if len(same_loc_all) > 0:
                same_loc_all = same_loc_all.copy()
                same_loc_all["record_label"] = (
                    same_loc_all["DR Number"].astype(str)
                    + " | "
                    + same_loc_all["Date Occurred"].dt.strftime("%Y-%m-%d").fillna("")
                    + " | "
                    + same_loc_all["Time Occurred"].astype(str)
                )
                selected_record_label = st.selectbox(
                    "Select a record",
                    same_loc_all["record_label"].tolist(),
                )
                detail_row = same_loc_all[same_loc_all["record_label"] == selected_record_label].iloc[0]

                detail_cols = [
                    "DR Number", "Date Occurred", "Time Occurred",
                    "Area Name", "Crime Code Description",
                    "Address", "Cross Street",
                    "Victim Age", "Victim Sex", "Victim Descent",
                    "Premise Description",
                ]
                st.table(detail_row[detail_cols].to_frame().rename(columns={0: "Value"}))

    with col2:
        st.subheader("Location-level Crime Type Distribution")

        if selected_label == "All locations":
            st.info("Select a specific location to see crime distribution.")
        else:
            if len(same_loc_all) > 0:
                crime_counts = same_loc_all["Crime Code Description"].value_counts().head(10)
                bar_data = pd.DataFrame({
                    "Crime": crime_counts.index,
                    "Count": crime_counts.values,
                })
                chart = (
                    alt.Chart(bar_data)
                    .mark_bar()
                    .encode(
                        x=alt.X("Count:Q", title="Count"),
                        y=alt.Y("Crime:N", sort="-x", axis=alt.Axis(title=None)),
                        tooltip=["Crime", "Count"],
                    )
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.info("No data for this location.")

# ============================================
# Mode 3: Commute Route Analysis
# ============================================
elif map_mode == "Commute Route":
    st.subheader(f"Commute Route Safety Analysis ({year_title_suffix})")

    commute_df = df_scope_for_stats.copy()

    if commute_df.empty:
        st.info("No data available under current filter conditions. Route analysis cannot be conducted.")
    else:
        # Aggregate location points for commute selection
        commute_loc_df = commute_df.copy()
        commute_loc_df["lat_round"] = commute_loc_df["lat"].round(4)
        commute_loc_df["lon_round"] = commute_loc_df["lon"].round(4)

        commute_loc_group = (
            commute_loc_df.groupby(["lat_round", "lon_round"])
            .agg(
                collisions=("DR Number", "count"),
                sample_address=("Address", "first"),
                sample_area=("Area Name", "first"),
            )
            .reset_index()
        )

        commute_loc_group["label"] = (
            commute_loc_group["sample_address"].fillna("No address")
            + " | "
            + commute_loc_group["sample_area"].fillna("")
            + " | "
            + commute_loc_group["collisions"].astype(str)
            + " collisions"
        )

        if len(commute_loc_group) < 2:
            st.info("Fewer than two available locations. Cannot construct a commuting route.")
        else:
            st.caption("The starting and ending points are derived from address points in collision data.")

            col_start, col_end = st.columns(2)
            with col_start:
                start_label = st.selectbox(
                    "Select the starting point for commuting",
                    commute_loc_group["label"].tolist(),
                    key="commute_start",
                )
            with col_end:
                end_label = st.selectbox(
                    "Select the ending point for commuting",
                    commute_loc_group["label"].tolist(),
                    key="commute_end",
                )

            if start_label == end_label:
                st.warning("The starting point and the ending point cannot be the same. Please select different locations.")
            else:
                start_row = commute_loc_group[commute_loc_group["label"] == start_label].iloc[0]
                end_row = commute_loc_group[commute_loc_group["label"] == end_label].iloc[0]

                start_lat, start_lon = float(start_row["lat_round"]), float(start_row["lon_round"])
                end_lat, end_lon = float(end_row["lat_round"]), float(end_row["lon_round"])

                buffer_m = st.slider(
                    "Buffer distance on both sides of the route (meters)",
                    min_value=50,
                    max_value=1000,
                    value=200,
                    step=50,
                    help="Used to count collisions within a certain distance from both sides of the route.",
                )

                commute_points_gdf = gpd.GeoDataFrame(
                    commute_df.copy(),
                    geometry=gpd.points_from_xy(commute_df["lon"], commute_df["lat"]),
                    crs="EPSG:4326",
                )

                # request route from OSRM
                try:
                    route_coords = get_osrm_route(start_lon, start_lat, end_lon, end_lat)
                except Exception as e:
                    st.error(f"OSRM route fetch failed. Reverting to straight-line mode. Error: {e}")
                    route_coords = [
                        [start_lon, start_lat],
                        [end_lon, end_lat],
                    ]

                route_line = LineString(route_coords)
                route_gdf = gpd.GeoDataFrame(geometry=[route_line], crs="EPSG:4326")

                try:
                    # project to metric CRS for buffering
                    commute_points_3857 = commute_points_gdf.to_crs(epsg=3857)
                    route_3857 = route_gdf.to_crs(epsg=3857)

                    route_buffer_3857 = route_3857.buffer(buffer_m).iloc[0]
                    buffer_gdf_3857 = gpd.GeoDataFrame(geometry=[route_buffer_3857], crs=route_3857.crs)

                    # spatial join: points within route buffer
                    joined_route = gpd.sjoin(
                        commute_points_3857,
                        buffer_gdf_3857,
                        how="inner",
                        predicate="within",
                    )

                    collisions_on_route = len(joined_route)
                    total_collisions = len(commute_df)
                    ratio = collisions_on_route / total_collisions if total_collisions > 0 else 0.0

                    joined_route_4326 = joined_route.to_crs(epsg=4326)

                    # summary metrics
                    st.markdown("**Summary of Safety Tips for Commuting Routes:**")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Number of collisions within route buffer", collisions_on_route)
                    c2.metric("Total collisions under current filter", total_collisions)
                    c3.metric("Percentage", f"{ratio:.1%}")

                    # high-risk intersections
                    if collisions_on_route > 0:
                        st.markdown("**High-risk intersections near the route (sorted by collisions)**")

                        tmp = joined_route_4326.copy()
                        tmp["lat_round"] = tmp["lat"].round(4)
                        tmp["lon_round"] = tmp["lon"].round(4)

                        hotspot = (
                            tmp.groupby(["lat_round", "lon_round"])
                            .agg(
                                collisions=("DR Number", "count"),
                                sample_address=("Address", "first"),
                                sample_area=("Area Name", "first"),
                            )
                            .reset_index()
                            .sort_values("collisions", ascending=False)
                            .head(3)
                        )

                        hotspot["location"] = (
                            hotspot["sample_address"].fillna("No address")
                            + " | "
                            + hotspot["sample_area"].fillna("")
                        )
                        hotspot_display = hotspot[["location", "collisions"]].rename(columns={"collisions": "number of collisions"})
                        st.table(hotspot_display)
                    else:
                        st.info("No collision records found within the buffer zone.")

                    # route visualization layer
                    st.markdown("**Route visualization (based on road network & surrounding collision points)**")

                    route_map_df = pd.DataFrame({
                        "path": [route_coords]
                    })

                    route_layer = pdk.Layer(
                        "PathLayer",
                        data=route_map_df,
                        get_path="path",
                        get_width=5,
                        width_min_pixels=3,
                        get_color=[0, 0, 255, 255],
                    )

                    route_collision_layer = pdk.Layer(
                        "ScatterplotLayer",
                        data=joined_route_4326,
                        get_position='[lon, lat]',
                        get_radius=80,
                        get_fill_color=[255, 0, 0, 200],
                    )

                    route_view = pdk.ViewState(
                        longitude=float((start_lon + end_lon) / 2),
                        latitude=float((start_lat + end_lat) / 2),
                        zoom=11,
                        min_zoom=9,
                        max_zoom=16,
                        pitch=40,
                    )

                    route_deck = pdk.Deck(
                        map_style="mapbox://styles/mapbox/dark-v9",
                        initial_view_state=route_view,
                        layers=[route_layer, route_collision_layer],
                        tooltip={"text": "Collision points near the commuting route"},
                    )

                    st.pydeck_chart(route_deck, use_container_width=True)

                except Exception as e:
                    st.error(f"Error occurred during route analysis: {e}")
                    st.info("This may be caused by coordinate system issues or incomplete lat/lon values in the dataset.")

# ============================================
# Histograms only for Dot / Hex modes
# ============================================
if map_mode != "Commute Route":
    # monthly histogram
    if selected_year == "All":
        st.subheader("Number of traffic collisions by month (All Years)")
    else:
        st.subheader(f"Number of traffic collisions by month in {selected_year}")

    df_year = df_scope_for_stats.copy()
    df_year["Month"] = df_year["Date Occurred"].dt.month

    month_counts = (
        df_year["Month"]
        .value_counts()
        .reindex(range(1, 13), fill_value=0)
        .sort_index()
    )

    month_df = pd.DataFrame({
        "Month": list(range(1, 13)),
        "Count": month_counts.values,
    })

    month_chart = (
        alt.Chart(month_df)
        .mark_bar()
        .encode(
            x=alt.X("Month:O", title="month (1-12)"),
            y=alt.Y("Count:Q", title="number of traffic collisions"),
            color=alt.Color(
                "Count:Q",
                scale=alt.Scale(range=["#ffff66", "#ff0000"]),
                legend=None,
            ),
            tooltip=["Month", "Count"],
        )
    )

    st.altair_chart(month_chart, use_container_width=True)

    # hourly histogram
    if selected_year == "All":
        st.subheader("Number of traffic collisions by hour (All Years)")
    else:
        st.subheader(f"Number of traffic collisions by hour in {selected_year}")

    df_hour = df_scope_for_stats.copy()
    df_hour["Hour"] = (
        pd.to_numeric(df_hour["Time Occurred"], errors="coerce")
        .fillna(0)
        .astype(int) // 100
    ).clip(0, 23)

    hour_counts = (
        df_hour["Hour"]
        .value_counts()
        .reindex(range(0, 24), fill_value=0)
        .sort_index()
    )

    hour_df = pd.DataFrame({
        "Hour": list(range(0, 24)),
        "Count": hour_counts.values,
    })

    hour_chart = (
        alt.Chart(hour_df)
        .mark_bar()
        .encode(
            x=alt.X("Hour:O", title="hour of day (0-23)"),
            y=alt.Y("Count:Q", title="number of traffic collisions"),
            color=alt.Color(
                "Count:Q",
                scale=alt.Scale(range=["#ffff66", "#ff0000"]),
                legend=None,
            ),
            tooltip=["Hour", "Count"],
        )
    )

    st.altair_chart(hour_chart, use_container_width=True)
