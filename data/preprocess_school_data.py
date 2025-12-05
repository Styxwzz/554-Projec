"""
Preprocess collision and school data for School Safety Map.
This script joins collision data with schools and keeps only collisions within school search radius.
Run once to create preprocessed data, then use in the app with caching.
"""

import pandas as pd
import numpy as np
from pathlib import Path

# ============================================
# Configuration
# ============================================
CSV_COLLISION_PATH = "data/Traffic_Collision_Data_2021_and_after.csv"
CSV_SCHOOLS_PATH = "data/Schools_Colleges_and_Universities_-1415912072170881369.csv"
OUTPUT_PATH = "data/collisions_by_school.csv"

SEARCH_RADIUS_MILE = 0.2
SEARCH_RADIUS_DEGREES = SEARCH_RADIUS_MILE * 1609.34 / 111000  # ~0.00289 degrees

# ============================================
# Load Data
# ============================================
print("Loading collision data...")
collision_df = pd.read_csv(CSV_COLLISION_PATH)

# Parse Location column
if "Location" in collision_df.columns:
    loc = collision_df["Location"].astype(str).str.strip("()").str.split(",", expand=True)
    collision_df["lat"] = pd.to_numeric(loc[0].str.strip(), errors="coerce")
    collision_df["lon"] = pd.to_numeric(loc[1].str.strip(), errors="coerce")
    collision_df = collision_df.dropna(subset=["lat", "lon"])

# Parse Date Occurred
if "Date Occurred" in collision_df.columns:
    collision_df["Date Occurred"] = pd.to_datetime(collision_df["Date Occurred"], errors="coerce")

# Extract year
collision_df["Year"] = collision_df["Date Occurred"].dt.year

print(f"Loaded {len(collision_df)} collision records")

print("\nLoading schools data...")
schools_df = pd.read_csv(CSV_SCHOOLS_PATH)
schools_df = schools_df.dropna(subset=["Latitude", "Longitude"])
schools_df = schools_df.rename(columns={"Latitude": "lat", "Longitude": "lon"})
print(f"Loaded {len(schools_df)} schools")

# ============================================
# Join: Find collisions near each school
# ============================================
print(f"\nJoining collision data with schools (radius: {SEARCH_RADIUS_MILE} miles)...")

result_records = []

for school_idx, school_row in schools_df.iterrows():
    school_lat = school_row["lat"]
    school_lon = school_row["lon"]
    school_name = school_row["Name"]
    
    # Find collisions within bounding box (fast filter)
    nearby = collision_df[
        (collision_df["lat"].between(school_lat - SEARCH_RADIUS_DEGREES, school_lat + SEARCH_RADIUS_DEGREES)) &
        (collision_df["lon"].between(school_lon - SEARCH_RADIUS_DEGREES, school_lon + SEARCH_RADIUS_DEGREES))
    ].copy()
    
    # Calculate actual distance (Euclidean)
    distances = np.sqrt(
        (nearby["lat"] - school_lat) ** 2 + 
        (nearby["lon"] - school_lon) ** 2
    )
    
    # Filter by radius
    nearby = nearby[distances <= SEARCH_RADIUS_DEGREES].copy()
    
    if len(nearby) > 0:
        # Add school info to each collision record
        nearby["school_name"] = school_name
        nearby["school_id"] = school_idx
        nearby["school_lat"] = school_lat
        nearby["school_lon"] = school_lon
        
        result_records.append(nearby)
    
    if (school_idx + 1) % 100 == 0:
        print(f"  Processed {school_idx + 1}/{len(schools_df)} schools...")

print(f"  Processed {len(schools_df)} schools")

# ============================================
# Combine Results
# ============================================
if result_records:
    collision_school_df = pd.concat(result_records, ignore_index=True)
    print(f"\nTotal collision-school pairs: {len(collision_school_df)}")
else:
    collision_school_df = pd.DataFrame()
    print("\nNo collisions found near schools")

# ============================================
# Merge with school category info
# ============================================
schools_subset = schools_df[["Name", "Category2", "Category3"]].copy()
schools_subset = schools_subset.rename(columns={"Name": "school_name"})

collision_school_df = collision_school_df.merge(
    schools_subset, 
    on="school_name", 
    how="left"
)

# ============================================
# Keep only necessary columns
# ============================================
keep_columns = [
    "school_name", "school_id", "school_lat", "school_lon",
    "Category2", "Category3",
    "lat", "lon", "Date Occurred", "Year",
    "Area Name", "Address", "DR Number"
]

collision_school_df = collision_school_df[keep_columns]

# ============================================
# Save to CSV
# ============================================
output_dir = Path(OUTPUT_PATH).parent
output_dir.mkdir(parents=True, exist_ok=True)

collision_school_df.to_csv(OUTPUT_PATH, index=False)
print(f"\n✓ Saved to: {OUTPUT_PATH}")
print(f"  Rows: {len(collision_school_df)}")
print(f"  Columns: {len(collision_school_df.columns)}")
print(f"  File size: {Path(OUTPUT_PATH).stat().st_size / 1024 / 1024:.2f} MB")
