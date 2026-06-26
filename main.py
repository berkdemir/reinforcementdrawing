"""Reinforced Concrete Section Drawer.

Uses the `blueprints` package (https://blueprints.readthedocs.io) for geometry,
rebar placement, area/weight calculation and plotting.

Install with:  pip install blue-prints   (import name is `blueprints`)

Supports two element types (chosen in the sidebar):
  * Beam / Column  - full rectangular section, reinforcement on any edge,
                     closed stirrups for shear.
  * Wall / Slab    - a 1 m wide design strip. Side faces are notional (no side
                     cover), reinforcement is given by spacing and reported as
                     area per metre (mm2/m).

Reinforcement input syntax (per edge, layers separated by '+'):
    By distance (centre-to-centre):  K32/150   ->  d=32, c/c=150
    By quantity:                     6K25  |  6Ø25  |  6x25  ->  6 bars of d=25

    Example:  K32/150+Y25/220+6K25
              layer 1 by distance, layer 2 by distance, layer 3 by quantity.

Note on prefixes: blueprints models one steel material for the whole section,
so the K / Y letters are treated as cosmetic labels only and do not change the
steel grade. If mixed grades per layer are needed, switch to building Rebar
objects directly (ask and this can be extended).
"""

import re

import matplotlib

matplotlib.use("Agg")
import streamlit as st

from blueprints.materials.concrete import ConcreteMaterial, ConcreteStrengthClass
from blueprints.materials.reinforcement_steel import (
    ReinforcementSteelMaterial,
    ReinforcementSteelQuality,
)
from blueprints.structural_sections.concrete.covers import CoversRectangular
from blueprints.structural_sections.concrete.reinforced_concrete_sections.rectangular import (
    RectangularReinforcedCrossSection,
)
from blueprints.structural_sections.concrete.reinforced_concrete_sections.reinforcement_configurations import (
    ReinforcementByDistance,
    ReinforcementByQuantity,
)

st.set_page_config(layout="wide", page_title="RC Section Drawer")


# ----------------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------------

# By distance:  optional prefix letter(s), diameter, "/", spacing   ->  K32/150
_RE_BY_DISTANCE = re.compile(r"^([A-Za-z]*)(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)$")
# By quantity:  count, optional prefix, optional Ø / x, diameter    ->  6K25, 6Ø25, 6x25
_RE_BY_QUANTITY = re.compile(r"^(\d+)\s*([A-Za-z]*)?(?:Ø|x|X)?\s*(\d+(?:\.\d+)?)$")


def parse_layer(token: str) -> dict:
    """Parse a single layer token into a structured description."""
    token = token.strip()

    m = _RE_BY_DISTANCE.match(token)
    if m:
        prefix, dia, spacing = m.group(1), float(m.group(2)), float(m.group(3))
        return {
            "mode": "distance",
            "prefix": prefix.upper(),
            "diameter": dia,
            "spacing": spacing,
            "label": token,
        }

    m = _RE_BY_QUANTITY.match(token)
    if m:
        n, prefix, dia = int(m.group(1)), (m.group(2) or ""), float(m.group(3))
        return {
            "mode": "quantity",
            "prefix": prefix.upper(),
            "diameter": dia,
            "n": n,
            "label": token,
        }

    raise ValueError(
        f"Invalid layer '{token}'. Use 'K32/150' (by distance) or '6K25' (by quantity)."
    )


def parse_reinforcement(text: str) -> list[dict]:
    """Parse a '+'-separated reinforcement string into a list of layers."""
    text = text.replace(" ", "")
    if not text:
        return []
    return [parse_layer(tok) for tok in text.split("+") if tok]


# Slab/wall shear links given as  ø/sx/sy  e.g. Ø12/300/300, K12/250/300, 10/200/200
_RE_SLAB_SHEAR = re.compile(
    r"^[A-Za-zØø]*\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$"
)


def parse_slab_shear(text: str):
    """Parse 'ø/sx/sy' into (diameter, sx, sy) in mm, or None if empty/invalid."""
    text = text.strip()
    if not text:
        return None
    m = _RE_SLAB_SHEAR.match(text)
    if not m:
        raise ValueError(
            f"Invalid shear link '{text}'. Use the form 'Ø12/300/300' (ø/sx/sy)."
        )
    return tuple(float(g) for g in m.groups())


def slab_shear_weight_per_m2(diameter, sx, sy, leg_length_mm, density=7850.0):
    """Reinforcement mass of vertical shear legs per m2 of slab plan area [kg/m2].

    One vertical leg per (sx * sy) of plan area. Leg length is taken as the clear
    distance between the outer mats (thickness - top cover - bottom cover) as a
    simple, slightly conservative estimate that ignores hooks/anchorage.
    """
    import math

    a_bar = math.pi * diameter**2 / 4.0  # mm2
    n_per_m2 = 1e6 / (sx * sy)  # legs per m2 of plan
    volume_mm3_per_m2 = a_bar * leg_length_mm * n_per_m2
    return volume_mm3_per_m2 * 1e-9 * density  # kg/m2


# ----------------------------------------------------------------------------
# Build the cross-section
# ----------------------------------------------------------------------------

def add_layers(
    cs: RectangularReinforcedCrossSection,
    layers: list[dict],
    edge: str,
    base_cover: float,
    layer_spacing: float,
    material: ReinforcementSteelMaterial,
    corner_offset: float,
) -> None:
    """Add the parsed layers to one edge, stacking them inward by layer_spacing.

    The `cover` passed to blueprints is the distance from the edge face to the
    bar *surface*; blueprints subtracts d/2 itself to find the bar centre.
    Layer 1 sits at base_cover. Each subsequent layer is offset inward by
    (previous bar diameter + layer_spacing), giving a clear gap of layer_spacing
    between consecutive layers' surfaces.
    """
    cover_surface = base_cover  # running edge-face-to-bar-surface distance
    prev_dia = None

    for i, layer in enumerate(layers):
        dia = layer["diameter"]

        if i == 0:
            cover_surface = base_cover
        else:
            cover_surface = cover_surface + prev_dia + layer_spacing

        if layer["mode"] == "quantity":
            cs.add_longitudinal_reinforcement_by_quantity(
                n=layer["n"],
                diameter=dia,
                material=material,
                edge=edge,
                cover=cover_surface,
                corner_offset=corner_offset,
            )
        else:  # distance
            cs.add_reinforcement_configuration(
                line=cs._get_reference_line,
                configuration=ReinforcementByDistance(
                    diameter=dia,
                    material=material,
                    center_to_center=layer["spacing"],
                ),
                edge=edge,
                cover=cover_surface,
                corner_offset=corner_offset,
                diameter=dia,
            )

        prev_dia = dia


def build_section(
    beam_width,
    beam_height,
    top_cover,
    bottom_cover,
    side_cover,
    layer_spacing,
    corner_offset,
    top_reinf,
    bottom_reinf,
    left_reinf,
    right_reinf,
    concrete_class,
    steel_quality,
    stirrup_diameter=0.0,
    stirrup_distance=0.0,
    inner_stirrup_diameter=0.0,
    inner_stirrup_distance=0.0,
    inner_stirrup_width=0.0,
):
    concrete = ConcreteMaterial(concrete_class=concrete_class)
    steel = ReinforcementSteelMaterial(steel_quality=steel_quality)

    cs = RectangularReinforcedCrossSection(
        width=beam_width,
        height=beam_height,
        concrete_material=concrete,
        covers=CoversRectangular(
            upper=top_cover,
            lower=bottom_cover,
            left=side_cover,
            right=side_cover,
        ),
    )

    # Stirrups must be added BEFORE longitudinal bars: blueprints offsets the
    # longitudinal reference lines inward by the stirrup diameter, so the bars
    # sit inside the links automatically.
    if stirrup_diameter > 0 and stirrup_distance > 0:
        cs.add_stirrup_along_edges(
            diameter=stirrup_diameter,
            distance=stirrup_distance,
            material=steel,
            shear_check=False,
            torsion_check=False,
        )

    # Optional second (internal) link spanning a given width in the centre,
    # for multi-leg shear arrangements.
    if (
        inner_stirrup_diameter > 0
        and inner_stirrup_distance > 0
        and inner_stirrup_width > 0
    ):
        cs.add_stirrup_in_center(
            width=inner_stirrup_width,
            diameter=inner_stirrup_diameter,
            distance=inner_stirrup_distance,
            material=steel,
            shear_check=False,
            torsion_check=False,
        )

    edge_specs = [
        ("upper", top_reinf, top_cover),
        ("lower", bottom_reinf, bottom_cover),
        ("left", left_reinf, side_cover),
        ("right", right_reinf, side_cover),
    ]
    for edge, text, base_cover in edge_specs:
        layers = parse_reinforcement(text)
        if layers:
            add_layers(
                cs, layers, edge, base_cover, layer_spacing, steel, corner_offset
            )

    return cs


# ----------------------------------------------------------------------------
# Sidebar - element type and shape selection
# ----------------------------------------------------------------------------

with st.sidebar:
    st.header("Configuration")

    element_type = st.radio(
        "Element type",
        options=["Beam / Column", "Wall / Slab"],
        help=(
            "Beam / Column: full section, reinforcement on any edge, closed "
            "stirrups.\n\nWall / Slab: a 1 m wide design strip with results "
            "reported per metre."
        ),
    )

    shape = st.radio(
        "Cross-section shape",
        options=["Rectangular", "Circular (coming soon)"],
        help="Only rectangular is available for now. Circular will follow.",
    )
    if shape.startswith("Circular"):
        st.info("Circular sections are not implemented yet. Using rectangular.")

    st.divider()
    st.caption(
        "Built on the open-source [blueprints]"
        "(https://blueprints.readthedocs.io) library."
    )

is_slab = element_type == "Wall / Slab"


# ----------------------------------------------------------------------------
# Main layout
# ----------------------------------------------------------------------------

st.title("Wall / Slab Strip Drawer" if is_slab else "Beam / Column Section Drawer")

col1, col2 = st.columns([2, 3], gap="large")

# --- Inputs (left), grouped into tabs to stay within one screen height -------
with col1:
    tab_geo, tab_rebar, tab_shear = st.tabs(["Section", "Reinforcement", "Shear"])

    # ---- Tab 1: geometry, covers, materials ----
    with tab_geo:
        if is_slab:
            st.caption("A 1 m wide strip is modelled. Enter the member thickness.")
            beam_width = 1000.0
            g1, g2 = st.columns(2)
            beam_height = g1.number_input("Thickness (mm)", value=300.0, step=10.0)
            layer_spacing = g2.number_input(
                "Layer gap (mm)", value=25.0, step=5.0,
                help="Clear gap between reinforcement layers in the same face.",
            )
            corner_offset = 0.0
        else:
            g1, g2 = st.columns(2)
            beam_width = g1.number_input("Width (mm)", value=1000.0, step=50.0)
            beam_height = g2.number_input("Height (mm)", value=800.0, step=50.0)
            g3, g4 = st.columns(2)
            layer_spacing = g3.number_input(
                "Layer gap (mm)", value=25.0, step=5.0,
                help="Clear gap between reinforcement layers on the same edge.",
            )
            corner_offset = g4.number_input(
                "Corner offset (mm)", value=0.0, step=5.0,
                help="Inset of the first/last bar from the corners towards the centre.",
            )

        st.markdown("**Covers** (to bar surface)")
        if is_slab:
            cc1, cc2 = st.columns(2)
            top_cover = cc1.number_input("Top (mm)", value=30.0, step=5.0)
            bottom_cover = cc2.number_input("Bottom (mm)", value=30.0, step=5.0)
            side_cover = 0.0  # notional strip cut, no real side face
            st.caption("Side faces are notional strip cuts, so no side cover is used.")
        else:
            cc1, cc2, cc3 = st.columns(3)
            top_cover = cc1.number_input("Top (mm)", value=45.0, step=5.0)
            bottom_cover = cc2.number_input("Bottom (mm)", value=35.0, step=5.0)
            side_cover = cc3.number_input("Side (mm)", value=50.0, step=5.0)

        st.markdown("**Materials**")
        m1, m2 = st.columns(2)
        concrete_class = m1.selectbox(
            "Concrete",
            options=list(ConcreteStrengthClass),
            index=list(ConcreteStrengthClass).index(ConcreteStrengthClass.C35_45),
            format_func=lambda c: c.value,
        )
        steel_quality = m2.selectbox(
            "Steel",
            options=list(ReinforcementSteelQuality),
            index=list(ReinforcementSteelQuality).index(ReinforcementSteelQuality.B500B),
            format_func=lambda q: q.value,
        )

    # ---- Tab 2: longitudinal reinforcement ----
    with tab_rebar:
        if is_slab:
            top_reinf = st.text_input("Top face", value="K16/150")
            bottom_reinf = st.text_input("Bottom face", value="K16/150")
            left_reinf = ""
            right_reinf = ""
            st.caption(
                "By distance (e.g. `K16/150`) is normal for slabs/walls. "
                "Results are reported per metre (mm²/m)."
            )
        else:
            top_reinf = st.text_input("Top (upper edge)", value="5Ø14")
            bottom_reinf = st.text_input("Bottom (lower edge)", value="4Ø40")
            r1, r2 = st.columns(2)
            left_reinf = r1.text_input("Left edge", value="5Ø14")
            right_reinf = r2.text_input("Right edge", value="5Ø14")
            st.caption(
                "Stack layers on one edge with `+`. "
                "**By distance** `K32/150` (ø/spacing) · **by quantity** `6K25` "
                "(count·ø). Mix them: `K32/150+3K20`.\n\n"
                "The leading letter is just a label, use any (K, Y, T, Ø, …); it "
                "does not change the steel grade."
            )

    # ---- Tab 3: shear reinforcement ----
    with tab_shear:
        if is_slab:
            slab_shear = st.text_input("Shear links (ø/sx/sy)", value="")
            st.caption(
                "Slab/wall links as ø/sx/sy (spacing both ways), e.g. `K12/300/300`. "
                "Not drawn (blueprints models one in-plane link only) but counted "
                "in the steel ratio."
            )
            stirrup_diameter = stirrup_distance = 0.0
            inner_stirrup_diameter = inner_stirrup_distance = inner_stirrup_width = 0.0
        else:
            slab_shear = ""
            st.markdown("**Perimeter stirrup**")
            sc1, sc2 = st.columns(2)
            stirrup_diameter = sc1.number_input("ø (mm)", value=8.0, step=2.0)
            stirrup_distance = sc2.number_input("c/c (mm)", value=150.0, step=25.0)
            st.caption("Closed link along all edges. Set ø or c/c to 0 to omit.")

            st.markdown("**Internal link** (optional, multi-leg)")
            ic1, ic2, ic3 = st.columns(3)
            inner_stirrup_diameter = ic1.number_input("ø (mm)", value=12.0, step=2.0, key="inner_d")
            inner_stirrup_distance = ic2.number_input("c/c (mm)", value=300.0, step=25.0, key="inner_s")
            inner_stirrup_width = ic3.number_input("width (mm)", value=500.0, step=50.0, key="inner_w")
            st.caption("Set any field to 0 to omit.")


# --- Section drawing + results (right) ---------------------------------------
with col2:
    try:
        cs = build_section(
            beam_width=beam_width,
            beam_height=beam_height,
            top_cover=top_cover,
            bottom_cover=bottom_cover,
            side_cover=side_cover,
            layer_spacing=layer_spacing,
            corner_offset=corner_offset,
            top_reinf=top_reinf,
            bottom_reinf=bottom_reinf,
            left_reinf=left_reinf,
            right_reinf=right_reinf,
            concrete_class=concrete_class,
            steel_quality=steel_quality,
            stirrup_diameter=stirrup_diameter,
            stirrup_distance=stirrup_distance,
            inner_stirrup_diameter=inner_stirrup_diameter,
            inner_stirrup_distance=inner_stirrup_distance,
            inner_stirrup_width=inner_stirrup_width,
        )

        figsize = (8, 4) if is_slab else (8, 8)
        fig = cs.plot(figsize=figsize, include_legend=True)
        st.pyplot(fig, use_container_width=True)

        # --- Results: lead with the total steel ratio -----------------------
        concrete_area_m2 = (beam_width * beam_height) * 1e-6  # mm2 -> m2
        long_kg_per_m3 = cs.reinforcement_weight_longitudinal_bars / concrete_area_m2
        stirrup_kg_per_m3 = cs.reinforcement_weight_stirrups / concrete_area_m2
        as_total = cs.reinforcement_area_longitudinal_bars

        if is_slab:
            shear = parse_slab_shear(slab_shear)
            shear_kg_per_m3 = 0.0
            shear_detail = ""
            if shear is not None:
                d_s, sx, sy = shear
                leg_len = max(beam_height - top_cover - bottom_cover, 0.0)
                shear_kg_per_m3 = slab_shear_weight_per_m2(
                    d_s, sx, sy, leg_len
                ) / (beam_height / 1000.0)
                shear_detail = (
                    f" + shear Ø{d_s:g}/{sx:g}/{sy:g} {shear_kg_per_m3:,.1f} "
                    f"(leg ≈ {leg_len:g} mm, hooks not counted)"
                )
            total_kg_per_m3 = long_kg_per_m3 + shear_kg_per_m3

            st.metric("Total steel ratio", f"{total_kg_per_m3:,.1f} kg/m³")
            st.caption(
                f"As (longitudinal): {as_total:,.0f} mm²/m  ·  "
                f"main mats {long_kg_per_m3:,.1f} kg/m³{shear_detail}.  "
                f"Strip 1 m wide, thickness {beam_height / 1000:.3f} m."
            )
        else:
            total_kg_per_m3 = long_kg_per_m3 + stirrup_kg_per_m3
            st.metric("Total steel ratio", f"{total_kg_per_m3:,.1f} kg/m³")
            st.caption(
                f"As: {as_total:,.0f} mm²  ·  "
                f"longitudinal {long_kg_per_m3:,.1f} kg/m³  ·  "
                f"stirrups {stirrup_kg_per_m3:,.1f} kg/m³.  "
                f"Concrete section {concrete_area_m2:.3f} m²."
            )

    except Exception as e:
        st.error(f"Could not build the section: {e}")
