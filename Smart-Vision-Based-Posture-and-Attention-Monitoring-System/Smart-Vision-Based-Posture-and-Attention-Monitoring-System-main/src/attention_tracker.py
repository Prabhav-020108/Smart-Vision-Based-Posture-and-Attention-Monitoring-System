def detect_attention(nose):

    # -----------------------------
    # DEFAULT STATE
    # -----------------------------

    attention = "FOCUSED"

    color = (0,255,0)

    # -----------------------------
    # DISTRACTION DETECTION
    # -----------------------------

    if nose.x < 0.30 or nose.x > 0.70:

        attention = "DISTRACTED"

        color = (0,0,255)

    # -----------------------------
    # RETURN RESULTS
    # -----------------------------

    return attention, color