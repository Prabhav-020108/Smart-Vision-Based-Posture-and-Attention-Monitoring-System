def update_timers(
    attention,
    posture,
    dt,
    focused_time,
    distracted_time,
    continuous_distraction_time,
    bad_posture_time
):

    # -----------------------------
    # ATTENTION TIMERS
    # -----------------------------

    if attention == "FOCUSED":

        focused_time += dt

        continuous_distraction_time = 0

    else:

        distracted_time += dt

        continuous_distraction_time += dt

    # -----------------------------
    # POSTURE TIMER
    # -----------------------------

    if posture == "GOOD":

        bad_posture_time = 0

    else:

        bad_posture_time += dt

    # -----------------------------
    # RETURN UPDATED VALUES
    # -----------------------------

    return (
        focused_time,
        distracted_time,
        continuous_distraction_time,
        bad_posture_time
    )