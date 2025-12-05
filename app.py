import streamlit as st

st.set_page_config(page_title='Interactive Map-based dashboard for Urban Traffic Collision Analysis', layout='wide')
st.sidebar.success('Choose a page')
st.title('Interactive Map-based dashboard for Urban Traffic Collision Analysis')

st.markdown("""
### Project Overview

This dashboard provides a multi-level exploration of Los Angeles traffic collisions using publicly available datasets.
By integrating spatial data, collision records, and school-zone information, our system enables users to examine
traffic safety from three perspectives:

1. **Citywide Collision Map** – Analyze overall collision patterns across Los Angeles, identify hotspots, and observe temporal trends.
2. **Neighborhood View** – Compare neighborhoods based on collision frequency, severity, and relevant socioeconomic factors.
3. **School Safety View** – Evaluate collision risks around schools and visualize safety conditions near educational zones.

### Purpose

The goal of this project is to transform complex traffic data into an intuitive visual analytics tool that allows
residents, policymakers, and researchers to better understand where and why collisions occur, and to support
data-driven decisions aimed at improving road safety.

### Key Features

- Interactive maps with severity-based encodings  
- Multi-granularity exploration from city to school zones  
- Coordinated visualizations for comparing spatial and temporal patterns  
- Clear, task-oriented interface for non-technical users

""")
