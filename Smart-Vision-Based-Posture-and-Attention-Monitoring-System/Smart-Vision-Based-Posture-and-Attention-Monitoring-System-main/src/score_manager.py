def calculate_focus_percentage(
    focused_time,
    distracted_time
):

    total_time = (
        focused_time + distracted_time
    )

    if total_time > 0:

        focus_percentage = (
            focused_time / total_time
        ) * 100

    else:

        focus_percentage = 0

    return focus_percentage