"""Local runner for posture and attention monitoring."""

from __future__ import annotations

import argparse
import time

import cv2

from src.db.database import init_db
from src.logger import save_session
from src.serial_manager import send_alert
from src.services.session_service import SessionService
from src.services.vision_service import VisionService


def main(show_window: bool = False) -> None:
    """Run local monitoring, optionally showing an OpenCV demo window."""

    init_db()
    vision_service = VisionService()
    session_service = SessionService()
    session = session_service.start_session()
    session_id = session.session_id
    latest_metrics = None
    last_saved_at = 0.0
    save_interval_seconds = 1.0

    try:
        while True:
            metrics = vision_service.process_next_frame(draw_overlay=True)

            if metrics is None:
                break

            latest_metrics = metrics

            now = time.monotonic()
            if now - last_saved_at >= save_interval_seconds:
                session_service.save_telemetry_sample(session_id, metrics)
                last_saved_at = now

            if metrics["alert_message"]:
                send_alert(metrics["alert_message"])

            if show_window:
                cv2.imshow("Posture Monitoring System", metrics["frame"])
                if cv2.waitKey(1) == 27:
                    break
    finally:
        if latest_metrics is not None:
            save_session(
                latest_metrics["focused_time"],
                latest_metrics["distracted_time"],
                latest_metrics["focus_percentage"],
            )
            final_summary = {
                "focused_time": latest_metrics["focused_time"],
                "distracted_time": latest_metrics["distracted_time"],
                "focus_percentage": latest_metrics["focus_percentage"],
            }
            session_service.end_session(session_id, final_summary=final_summary)

        vision_service.release()
        if show_window:
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    """Parse local runner command-line options."""

    parser = argparse.ArgumentParser(description="Run local posture monitoring.")
    parser.add_argument(
        "--demo-window",
        action="store_true",
        help="Display the processed camera feed in an OpenCV window for local demos.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(show_window=args.demo_window)
