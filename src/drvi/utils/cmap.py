from matplotlib.colors import LinearSegmentedColormap

cmap_data = {
    "red": ((0.0, 0.0, 0.0), (0.25, 0.0, 0.0), (0.5, 1.0, 1.0), (0.75, 1.0, 1.0), (1.0, 0.5, 0.0)),
    "green": ((0.0, 0.0, 0.0), (0.25, 0.0, 0.0), (0.5, 1.0, 1.0), (0.75, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "blue": ((0.0, 0.0, 0.5), (0.25, 1.0, 1.0), (0.5, 1.0, 1.0), (0.75, 0.0, 0.0), (1.0, 0.0, 0.0)),
}

saturated_red_blue_cmap = LinearSegmentedColormap("SaturatedRdBu", cmap_data)


cmap_data = {
    "red": ((0.0, 0.0, 240 / 256), (0.75, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "green": ((0.0, 0.0, 240 / 256), (0.75, 200 / 255, 200 / 255), (1.0, 63 / 255, 0.0)),
    "blue": ((0.0, 0.0, 240 / 256), (0.75, 255 / 255, 255 / 255), (1.0, 80 / 255, 0.0)),
}

saturated_just_sky_cmap = LinearSegmentedColormap("SaturatedJSky", cmap_data)


cmap_data = {
    "red": ((0.0, 0.0, 136 / 255), (0.5, 250 / 256, 250 / 256), (0.65, 0.0, 0.0), (1.0, 0.0, 0.0)),
    "green": ((0.0, 0.0, 136 / 255), (0.5, 250 / 256, 250 / 256), (0.65, 200 / 255, 200 / 255), (1.0, 63 / 255, 0.0)),
    "blue": ((0.0, 0.0, 136 / 255), (0.5, 250 / 256, 250 / 256), (0.65, 255 / 255, 255 / 255), (1.0, 80 / 255, 0.0)),
}

saturated_sky_cmap = LinearSegmentedColormap("SaturatedSky", cmap_data)
