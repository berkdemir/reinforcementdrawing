import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.patches as patches


st.set_page_config(layout="wide")
st.title("Beam Reinforcement Drawer")


def draw_beam(
    top_reinf,
    bottom_reinf,
    top_cover,
    bottom_cover,
    beam_width,
    beam_height,
    layer_spacing
):

    def parse_reinforcement(reinf, cover):
        layers = reinf.replace(" ", "").split("+")
        parsed = []

        for layer in layers:
            if layer.startswith(("K", "Y")):
                prefix = layer[0]
                diameter, spacing = layer[1:].split("/")
                diameter = int(diameter)
                spacing = int(spacing)

                num_bars = int((beam_width - 2 * cover) // spacing) + 1

                parsed.append({
                    "type": prefix,
                    "diameter": diameter,
                    "spacing": spacing,
                    "num_bars": num_bars,
                    "label": layer
                })

            elif "Ø" in layer:
                num, dia = layer.split("Ø")
                num = int(num)
                dia = int(dia)

                spacing = (beam_width - 2 * cover) / (num - 1)

                parsed.append({
                    "type": "Ø",
                    "diameter": dia,
                    "spacing": spacing,
                    "num_bars": num,
                    "label": layer
                })
            else:
                raise ValueError(f"Invalid format: {layer}")

        return parsed


    def draw_layers(ax, layers, y_start, cover, direction):

        y = y_start

        for i, layer in enumerate(layers):
            dia = layer["diameter"]
            spacing = layer["spacing"]
            n = layer["num_bars"]

            x0 = cover
            for j in range(n):
                x = x0 + j * spacing
                circle = patches.Circle(
                    (x, y),
                    dia / 2,
                    facecolor="black",
                    edgecolor="black"
                )
                ax.add_patch(circle)

            # annotation
            ax.plot([beam_width, beam_width + 60], [y, y], linestyle="--", color="gray")
            ax.text(beam_width + 70, y, layer["label"], va="center")

            # vertical spacing
            if i < len(layers) - 1:
                next_dia = layers[i + 1]["diameter"]
                delta = (dia / 2 + next_dia / 2 + layer_spacing)
            else:
                delta = dia / 2 + layer_spacing

            y = y - delta if direction == "top" else y + delta


    top_layers = parse_reinforcement(top_reinf, top_cover)
    bottom_layers = parse_reinforcement(bottom_reinf, bottom_cover)

    fig, ax = plt.subplots(figsize=(6, 6))

    rect = patches.Rectangle(
        (0, 0),
        beam_width,
        beam_height,
        linewidth=2,
        edgecolor="black",
        facecolor="white"
    )
    ax.add_patch(rect)

    # top
    y_top = beam_height - top_cover - top_layers[0]["diameter"] / 2
    draw_layers(ax, top_layers, y_top, top_cover, "top")

    # bottom
    y_bot = bottom_cover + bottom_layers[0]["diameter"] / 2
    draw_layers(ax, bottom_layers, y_bot, bottom_cover, "bottom")

    # dimensions
    ax.annotate("", xy=(0, -50), xytext=(beam_width, -50),
                arrowprops=dict(arrowstyle="<->"))
    ax.text(beam_width / 2, -70, f"{beam_width} mm",
            ha="center", va="center")

    ax.annotate("", xy=(-50, 0), xytext=(-50, beam_height),
                arrowprops=dict(arrowstyle="<->"))
    ax.text(-70, beam_height / 2, f"{beam_height} mm",
            ha="center", va="center", rotation=90)

    ax.set_xlim(-100, beam_width + 150)
    ax.set_ylim(-100, beam_height + 100)
    ax.set_aspect("equal")
    ax.axis("off")

    return fig


# ===== LAYOUT =====

col1, col2 = st.columns([3, 2])  # wider drawing area

with col1:
    st.header("Inputs")

    st.subheader("Geometry")
    beam_width = st.number_input("Beam width (mm)", value=1000)
    beam_height = st.number_input("Beam height (mm)", value=1000)
    layer_spacing = st.number_input("Layer spacing (mm)", value=25)

    st.subheader("Covers")
    top_cover = st.number_input("Top cover (mm)", value=110)
    bottom_cover = st.number_input("Bottom cover (mm)", value=45)

    st.subheader("Reinforcement")
    top_reinf = st.text_input(
        "Top reinforcement",
        value="K32/150+Y25/220+K25/134"
    )
    bottom_reinf = st.text_input(
        "Bottom reinforcement",
        value="Y32/150+K25/150+6Ø32"
    )


with col2:
    st.header("Section")

    try:
        fig = draw_beam(
            top_reinf,
            bottom_reinf,
            top_cover,
            bottom_cover,
            beam_width,
            beam_height,
            layer_spacing
        )

        st.pyplot(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Input error: {e}")