import csv
import os
from datetime import datetime


def save_session(
    focused_time,
    distracted_time,
    focus_percentage
):

    os.makedirs("data", exist_ok=True)

    file_path = "data/session_log.csv"

    file_exists = os.path.isfile(file_path)

    with open(
        file_path,
        mode="a",
        newline=""
    ) as file:

        writer = csv.writer(file)

        if not file_exists:

            writer.writerow([
                "DateTime",
                "FocusedTime",
                "DistractedTime",
                "FocusPercentage"
            ])

        writer.writerow([
            datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            ),
            int(focused_time),
            int(distracted_time),
            int(focus_percentage)
        ])