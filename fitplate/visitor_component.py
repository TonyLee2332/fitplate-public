"""Trusted local component; no remote scripts and no provider credentials."""
from pathlib import Path
import streamlit as st

visitor_component = st.components.v2.component(
    'fitplate_visitor_identity',
    js=(Path(__file__).resolve().parents[1] / 'assets/visitor_identity.js').read_text(encoding='utf-8'),
)
