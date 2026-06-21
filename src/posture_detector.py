def calculate_posture(nose, left_shoulder, right_shoulder):

    # -----------------------------
    # SHOULDER ALIGNMENT
    # -----------------------------

    shoulder_diff = abs(
        left_shoulder.y - right_shoulder.y
    )

    # -----------------------------
    # SHOULDER CENTER
    # -----------------------------

    shoulder_mid_x = (
        left_shoulder.x + right_shoulder.x
    ) / 2

    # -----------------------------
    # NECK OFFSET
    # -----------------------------

    neck_offset = abs(
        nose.x - shoulder_mid_x
    )

    # -----------------------------
    # POSTURE SCORE
    # -----------------------------

    score = 100

    if shoulder_diff > 0.03:
        score -= 30

    if neck_offset > 0.05:
        score -= 40

    score = max(score, 0)

    # -----------------------------
    # CLASSIFICATION
    # -----------------------------

    if score >= 80:

        posture = "GOOD"
        color = (0,255,0)

    elif score >= 50:

        posture = "MODERATE"
        color = (0,255,255)

    else:

        posture = "BAD"
        color = (0,0,255)

    # -----------------------------
    # RETURN RESULTS
    # -----------------------------

    return score, posture, color